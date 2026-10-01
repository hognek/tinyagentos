"""T9: Tests for convert_to_lxc — flat-mode to worker-LXC migration."""
from unittest.mock import AsyncMock, patch
import pytest

from tinyagentos.cluster.convert_to_lxc import (
    list_flat_mode_agents,
    drain_and_delete_agents,
    redeploy_agents,
)


def test_list_flat_mode_agents_filters_taos_agent_prefix():
    fake_output = "taos-agent-foo,RUNNING\ntaos-agent-bar,STOPPED\nrandom-thing,RUNNING\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = fake_output
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        agents = list_flat_mode_agents()
    assert agents == [
        {"name": "taos-agent-foo", "state": "RUNNING"},
        {"name": "taos-agent-bar", "state": "STOPPED"},
    ]


def test_list_flat_mode_agents_returns_empty_on_incus_error():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "incus not found"
        mock_run.return_value.stdout = ""
        assert list_flat_mode_agents() == []


@pytest.mark.asyncio
async def test_drain_and_delete_agents_calls_stop_then_delete():
    calls = []

    async def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch("tinyagentos.cluster.convert_to_lxc._run_async", fake_run):
        await drain_and_delete_agents([
            {"name": "taos-agent-foo", "state": "RUNNING"},
            {"name": "taos-agent-bar", "state": "STOPPED"},
        ])
    assert ["incus", "stop", "taos-agent-foo"] in calls
    assert ["incus", "delete", "--force", "taos-agent-foo"] in calls
    assert ["incus", "delete", "--force", "taos-agent-bar"] in calls
    assert ["incus", "stop", "taos-agent-bar"] not in calls


@pytest.mark.asyncio
async def test_redeploy_agents_calls_deployer_for_each(monkeypatch):
    deployed = []

    async def fake_deploy(req):
        deployed.append(req.name)
        return {"success": True}

    class FakeDeployRequest:
        def __init__(self, **kw):
            self.name = kw["name"]

    monkeypatch.setattr("tinyagentos.deployer.deploy_agent", fake_deploy)
    monkeypatch.setattr("tinyagentos.deployer.DeployRequest", FakeDeployRequest)

    await redeploy_agents([
        {"name": "agent-a", "framework": "openclaw", "model": "gpt-4o"},
        {"name": "agent-b", "framework": "openclaw", "model": "claude"},
    ])
    assert deployed == ["agent-a", "agent-b"]


@pytest.mark.asyncio
async def test_redeploy_agents_passes_llm_proxy_in_extra_config(monkeypatch):
    """redeploy_agents must pass llm_proxy in extra_config so deploy_agent mints a scoped key."""
    captured_req = {}

    async def fake_deploy(req):
        captured_req["extra_config"] = req.extra_config
        return {"success": True}

    class FakeDeployRequest:
        def __init__(self, **kw):
            self.name = kw["name"]
            self.framework = kw.get("framework")
            self.model = kw.get("model")
            self.data_dir = kw.get("data_dir")
            self.extra_config = kw.get("extra_config")
            self.fallback_models = kw.get("fallback_models", [])
            self.color = kw.get("color", "#888888")
            self.emoji = kw.get("emoji")
            self.memory_limit = kw.get("memory_limit")
            self.cpu_limit = kw.get("cpu_limit")
            self.can_read_user_memory = kw.get("can_read_user_memory", False)
            self.secrets_store = kw.get("secrets_store")
            self.remote = kw.get("remote")
            self.taos_host = kw.get("taos_host", "127.0.0.1")
            self.taos_port = kw.get("taos_port", 6969)
            self.root_size_gib = kw.get("root_size_gib", 40)
            self.memory_mode = kw.get("memory_mode", "both")

    mock_proxy = AsyncMock()
    mock_proxy.create_agent_key = AsyncMock(return_value="sk-test-key")

    monkeypatch.setattr("tinyagentos.deployer.deploy_agent", fake_deploy)
    monkeypatch.setattr("tinyagentos.deployer.DeployRequest", FakeDeployRequest)

    await redeploy_agents(
        [{"name": "agent-a", "framework": "openclaw", "model": "gpt-4o"}],
        llm_proxy=mock_proxy,
    )

    assert captured_req["extra_config"]["llm_proxy"] is mock_proxy
