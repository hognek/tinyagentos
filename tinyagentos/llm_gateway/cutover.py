"""Move agents between LiteLLM and the gateway by retargeting one proxy device.

Every local agent container reaches its LLM at its OWN ``127.0.0.1:4000``
through the incus proxy device ``taos-proxy-litellm``. Its ``connect`` side
names a host port: the LiteLLM proxy (``server.litellm_port``, 7834 on new
installs) or, once cut over, the gateway's agent listener (7837). Changing
that one value moves the agent. Its base URL, its config files and its
process are untouched, so nothing is redeployed or restarted.

:func:`reconcile_agents` runs once at controller startup:

- gateway ON: for each agent, mint its gateway key from its LiteLLM
  ``agent_keys`` row FIRST, confirm the key is live, then point the device at
  the listener. An agent whose key cannot be read (no key, the shared master
  key, a key the local store does not hold, a key of another agent) stays on
  LiteLLM and is reported. Nothing unscoped is ever minted.
- gateway OFF (rollback): every device that points at the listener is pointed
  back at LiteLLM. The minted gateway rows are left in place; LiteLLM never
  reads them.

Both directions only ever change a device whose current value they have READ
and recognised; an unreadable or unexpected value is reported and left
alone. A second run changes nothing. Every incus call names the container's
own project (agent containers live in e.g. ``user-999``, not ``default``).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from tinyagentos import containers
from tinyagentos.litellm_keystore import LiteLLMKeyStore, default_keystore_path

logger = logging.getLogger(__name__)

DEVICE = "taos-proxy-litellm"


def _target(port: int) -> str:
    return f"tcp:127.0.0.1:{int(port)}"


def _master_key(data_dir: Path) -> str | None:
    try:
        value = (Path(data_dir) / ".litellm_master_key").read_text().strip()
    except OSError:
        return None
    return value or None


async def _container_projects() -> dict[str, str] | None:
    """``{container: project}`` across ALL incus projects, or None if unknown."""
    try:
        code, output = await containers._run(["incus", "list", "--all-projects", "-f", "json"])
    except (FileNotFoundError, OSError):
        return None
    if code != 0:
        return None
    try:
        instances = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    out: dict[str, str] = {}
    for inst in instances if isinstance(instances, list) else []:
        if isinstance(inst, dict) and isinstance(inst.get("name"), str):
            out[inst["name"]] = inst.get("project") or "default"
    return out


async def _get_connect(name: str, project: str) -> str | None:
    code, output = await containers._run(
        ["incus", "config", "device", "get", name, DEVICE, "connect", "--project", project]
    )
    if code != 0:
        return None
    value = (output or "").strip()
    return value or None


async def _set_connect(name: str, project: str, value: str) -> bool:
    code, _ = await containers._run(
        ["incus", "config", "device", "set", name, DEVICE, f"connect={value}", "--project", project]
    )
    return code == 0


def _container_name(agent: dict) -> str:
    return agent.get("container_name") or f"taos-agent-{agent.get('name')}"


def _key_problem(agent: dict, store: LiteLLMKeyStore, master: str | None) -> str | None:
    """Why this agent's LiteLLM key cannot become a gateway key, or None."""
    key = agent.get("llm_key")
    if not isinstance(key, str) or not key:
        return "no LiteLLM key recorded for this agent"
    if master is not None and key == master:
        return ("agent holds the shared LiteLLM master key, which the gateway "
                "refuses; re-key or redeploy it to move it to the gateway")
    return None


async def reconcile_agents(
    *,
    agents: Iterable[dict],
    data_dir: Path,
    gateway_on: bool,
    gateway_port: int,
    litellm_port: int,
    listener_ready: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Point each local agent's LLM proxy device where the flag says.

    Returns ``{"repointed": [...], "unchanged": [...], "skipped": [...]}``,
    each item ``{"agent", ...}``; skipped items carry a ``reason``.
    """
    report: dict[str, list[dict[str, Any]]] = {"repointed": [], "unchanged": [], "skipped": []}
    gw, lite = _target(gateway_port), _target(litellm_port)
    agents = [a for a in agents if isinstance(a, dict) and a.get("name")]
    if not agents:
        return report

    def skip(name: str, reason: str) -> None:
        report["skipped"].append({"agent": name, "reason": reason})

    if gw == lite:
        for a in agents:
            skip(a["name"], "gateway listener port equals the LiteLLM port")
        return report

    projects = await _container_projects()
    store = LiteLLMKeyStore(default_keystore_path(data_dir)) if gateway_on else None
    master = _master_key(data_dir) if gateway_on else None

    for agent in agents:
        name = agent["name"]
        if agent.get("remote"):
            skip(name, "remote agent: no proxy device (it reaches LiteLLM over the network)")
            continue
        container = _container_name(agent)
        if projects is None:
            skip(name, "incus unavailable: container project unknown")
            continue
        project = projects.get(container)
        if project is None:
            skip(name, f"container {container} not found in any incus project")
            continue
        current = await _get_connect(container, project)
        if current is None:
            skip(name, f"could not read {DEVICE} connect on {container} (project {project})")
            continue

        if not gateway_on:
            if current == lite:
                report["unchanged"].append({"agent": name, "connect": current})
            elif current == gw:
                if await _set_connect(container, project, lite):
                    report["repointed"].append({"agent": name, "connect": lite})
                else:
                    skip(name, f"incus refused to set {DEVICE} connect back to LiteLLM")
            else:
                skip(name, f"unexpected {DEVICE} connect {current!r}: left alone")
            continue

        # Gateway ON. The key comes first, whatever the device says.
        problem = _key_problem(agent, store, master)
        if problem is None:
            if store.mint_mirror(name, agent["llm_key"]) is None:
                problem = ("its LiteLLM key is not a local key-store row of this agent "
                           "(unknown, another agent's, or a LiteLLM Postgres virtual key)")
            elif not store.live_mirror(name, agent["llm_key"]):
                problem = "minted gateway key is not live"
        if current == gw:
            # Already on the gateway (an earlier run). Nothing to move; say so
            # loudly if its key no longer checks out.
            if problem is not None:
                logger.warning("llm gateway cutover: %s is on the gateway but %s", name, problem)
            report["unchanged"].append({"agent": name, "connect": current})
            continue
        if current != lite:
            skip(name, f"unexpected {DEVICE} connect {current!r}: left alone")
            continue
        if problem is not None:
            skip(name, problem)
            continue
        if not listener_ready:
            skip(name, "gateway agent listener is not reachable: left on LiteLLM")
            continue
        if await _set_connect(container, project, gw):
            report["repointed"].append({"agent": name, "connect": gw})
        else:
            skip(name, f"incus refused to set {DEVICE} connect to the gateway")

    return report


async def wait_for_listener(port: int, *, attempts: int = 30, delay: float = 1.0) -> bool:
    """True once something accepts TCP on ``127.0.0.1:port``."""
    if not port:
        return False
    for _ in range(max(1, attempts)):
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 2.0)
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(delay)
            continue
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
    return False


def llm_gateway_live_port(state) -> int:
    """The agent listener port new deploys may target, or 0 (stay on LiteLLM).

    Non-zero only after the startup reconcile SAW the listener accept a
    connection; a configured-but-dead listener is never handed to an agent.
    """
    if not getattr(state, "llm_gateway_listener_ready", False):
        return 0
    return int(getattr(state, "llm_gateway_agent_port", 0) or 0)


async def run_startup_reconcile(state) -> dict | None:
    """Lifespan hook: reconcile every configured agent once, log the result.

    Runs only when ``__main__`` recorded the agent listener port on the app
    state (so tests and embedded apps never touch incus).
    """
    from tinyagentos import llm_gateway

    port = getattr(state, "llm_gateway_agent_port", None)
    if port is None:
        return None
    # Listener disabled (port 0) counts as OFF: agents go back to LiteLLM,
    # recognised by the default listener port.
    on = llm_gateway.enabled() and bool(port)
    ready = await wait_for_listener(port) if on else False
    state.llm_gateway_listener_ready = ready
    if on and not ready:
        logger.error(
            "llm gateway: agent listener on 127.0.0.1:%s never accepted a connection; "
            "agents stay on LiteLLM", port,
        )
    config = getattr(state, "config", None)
    agents = list(getattr(config, "agents", None) or [])
    if not agents:
        return None
    proxy = getattr(state, "llm_proxy", None)
    litellm_port = int(getattr(proxy, "port", None) or 7834)
    try:
        report = await reconcile_agents(
            agents=agents,
            data_dir=Path(state.data_dir),
            gateway_on=on,
            gateway_port=port or llm_gateway.DEFAULT_AGENT_PORT,
            litellm_port=litellm_port,
            listener_ready=ready,
        )
    except Exception:
        logger.exception("llm gateway cutover: reconcile failed; agents left where they were")
        return None
    state.llm_gateway_cutover_report = report
    direction = "gateway" if on else "LiteLLM"
    for item in report["repointed"]:
        logger.warning("llm gateway cutover: %s now on %s (%s)", item["agent"], direction, item["connect"])
    for item in report["skipped"]:
        logger.warning("llm gateway cutover: %s left as is: %s", item["agent"], item["reason"])
    logger.info(
        "llm gateway cutover (%s): %d repointed, %d unchanged, %d skipped",
        direction, len(report["repointed"]), len(report["unchanged"]), len(report["skipped"]),
    )
    return report
