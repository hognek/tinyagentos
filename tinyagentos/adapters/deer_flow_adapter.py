"""DeerFlow adapter — proxies messages to the DeerFlow LangGraph runs API."""
import os
import httpx
from fastapi import FastAPI

from tinyagentos.clients.retry import with_retry

app = FastAPI()

_RETRY_KWARGS = dict(max_attempts=7, base_delay=0.5, multiplier=2.0, max_delay=60.0)


async def _controller_post(url: str, json: dict):
    # 600s timeout — DeerFlow is a long-horizon multi-step agent.
    async with httpx.AsyncClient(timeout=600) as client:
        return await client.post(url, json=json)


def _extract_text(messages) -> str:
    """Pull the assistant reply text from a list of LangGraph/LangChain messages.

    Handles both plain {"role": ..., "content": str} messages and LangChain
    {"type": "ai", "content": [...]} messages where content is a string or a
    list of {"type": "text", "text": "..."} blocks. Falls back to str() of the
    last message.
    """
    if not messages:
        return ""
    last = messages[-1]
    content = last.get("content") if isinstance(last, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    return str(last)


@app.post("/message")
async def handle_message(msg: dict):
    agent_name = os.environ.get("TAOS_AGENT_NAME", "agent")
    try:
        deer_flow_url = os.environ.get("DEER_FLOW_URL", "http://localhost:8001")
        resp = await with_retry(
            lambda: _controller_post(
                f"{deer_flow_url}/api/runs/wait",
                {
                    "input": {"messages": [{"role": "user", "content": msg.get("text", "")}]},
                    "context": {"model_name": "taos-default"},
                },
            ),
            **_RETRY_KWARGS,
        )
        if resp.status_code == 200:
            data = resp.json()
            # The body is the final serialized channel-values. The messages list
            # may sit at the top level or under output/values — try each.
            messages = (
                data.get("messages")
                or (data.get("output") or {}).get("messages")
                or (data.get("values") or {}).get("messages")
                or []
            )
            return {"content": _extract_text(messages)}
        return {"content": f"[{agent_name}] DeerFlow returned {resp.status_code}"}
    except Exception as e:
        return {"content": f"[{agent_name}] DeerFlow unavailable: {e}"}


@app.get("/health")
async def health():
    return {"status": "ok", "framework": "deer-flow"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("TAOS_ADAPTER_PORT", "9001")), log_level="warning")
