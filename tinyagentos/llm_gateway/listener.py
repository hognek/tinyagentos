"""The agent listener: the gateway at the base URL agents already use.

Agents call ``http://127.0.0.1:4000/v1/...`` (openclaw: ``.../chat/completions``
with no ``/v1``). Once the cutover retargets their proxy device, those
requests land here, on the host's ``127.0.0.1:<agent port>`` (7837), not on
the controller's main port: there ``/v1/chat/completions`` is Agent-as-a-Model,
a different API.

- ``/v1/models``, ``/v1/chat/completions`` and their un-prefixed forms are
  rewritten to ``/api/llm/v1/...`` and handed to the MAIN app object, so the
  auth middleware exemptions and ``gateway_caller`` run exactly as for any
  other gateway call. No other main-app route is reachable from here.
- Every other path goes, byte for byte, to the LiteLLM proxy, which still
  runs in cutover stage 1: embeddings (``TAOS_EMBEDDING_URL``) and anything
  else the gateway does not serve yet keep working through the same device.

Bound to loopback only by ``__main__``. It has no lifespan of its own.
"""
from __future__ import annotations

import logging

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from tinyagentos.llm_gateway.router import PREFIX

logger = logging.getLogger(__name__)

GATEWAY_PATHS = {
    "/v1/models": f"{PREFIX}/models",
    "/models": f"{PREFIX}/models",
    "/v1/chat/completions": f"{PREFIX}/chat/completions",
    "/chat/completions": f"{PREFIX}/chat/completions",
}

_HOP_BY_HOP = frozenset({
    b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization",
    b"te", b"trailer", b"transfer-encoding", b"upgrade", b"host",
})
_PASSTHROUGH_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)


async def _passthrough(scope, receive, send, litellm_port: int) -> None:
    """Relay one request to LiteLLM on ``127.0.0.1:<litellm_port>`` unchanged."""
    request = Request(scope, receive)
    body = await request.body()
    headers = [(k, v) for k, v in scope.get("headers") or [] if k.lower() not in _HOP_BY_HOP]
    url = f"http://127.0.0.1:{int(litellm_port)}{scope['path']}"
    query = scope.get("query_string") or b""
    if query:
        url += "?" + query.decode("latin-1")
    client = httpx.AsyncClient(timeout=_PASSTHROUGH_TIMEOUT)
    try:
        upstream = await client.send(
            client.build_request(scope["method"], url, headers=headers, content=body),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("llm gateway listener: LiteLLM passthrough failed: %s", type(exc).__name__)
        await JSONResponse(
            {"error": {"message": "the LiteLLM proxy is not reachable",
                       "type": "api_error", "param": None, "code": "upstream_unavailable"}},
            status_code=502,
        )(scope, receive, send)
        return
    try:
        out_headers = [(k, v) for k, v in upstream.headers.raw if k.lower() not in _HOP_BY_HOP]
        await send({"type": "http.response.start", "status": upstream.status_code,
                    "headers": out_headers})
        async for chunk in upstream.aiter_raw():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    finally:
        await upstream.aclose()
        await client.aclose()


def create_agent_listener_app(main_app, *, litellm_port: int):
    """ASGI app for the agent listener, wrapping the controller's ``main_app``."""

    async def app(scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if kind != "http":
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        target = GATEWAY_PATHS.get(scope.get("path", ""))
        if target is not None:
            rewritten = dict(scope)
            rewritten["path"] = target
            rewritten["raw_path"] = target.encode("ascii")
            await main_app(rewritten, receive, send)
            return
        await _passthrough(scope, receive, send, litellm_port)

    return app
