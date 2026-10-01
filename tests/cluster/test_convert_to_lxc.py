"""T9: Tests for convert_to_lxc — flat-mode to worker-LXC migration."""
import types
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


@pytest.mark.asyncio
async def test_redeploy_agents_handles_extra_config_in_row_without_typeerror(monkeypatch, tmp_path):
    """An agents.json row that carries extra_config must not raise TypeError.

    Build the DeployRequest kwargs from cfg WITHOUT extra_config, then pass
    the merged extra_config. On BASE this FAILS with TypeError because
    DeployRequest(**cfg, extra_config=extra_config) sees extra_config twice.
    """
    from tinyagentos.deployer import DeployRequest, deploy_agent

    captured_req = {}

    async def fake_deploy(req):
        captured_req["extra_config"] = req.extra_config
        return {"success": True}

    monkeypatch.setattr("tinyagentos.deployer.deploy_agent", fake_deploy)

    # Row carrying extra_config (the agents.json shape).
    await redeploy_agents([
        {
            "name": "agent-a",
            "framework": "openclaw",
            "model": "gpt-4o",
            "data_dir": tmp_path,
            "extra_config": {"llm_gateway_port": 7838},
        }
    ])

    assert captured_req["extra_config"]["llm_gateway_port"] == 7838


@pytest.mark.asyncio
async def test_convert_to_lxc_queries_controller_for_gateway_port_and_redeploys(
    monkeypatch, tmp_path
):
    """The CLI must obtain the verified agent-listener port from the RUNNING
    controller and pass it to redeploy_agents so each agent deploys with a
    minted key. On BASE this FAILS with 'listener is not verified' because
    llm_gateway_port is never passed and the real deploy_agent refuses.
    """
    from tinyagentos.cli.worker import _convert_to_lxc

    # Mock incus enumeration so drain phase is skipped.
    monkeypatch.setattr(
        "tinyagentos.cli.worker.list_flat_mode_agents",
        lambda: [],
    )

    # install-worker.sh succeeds.
    fake_run = types.SimpleNamespace(returncode=0)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_run)

    # Data dir and config.
    monkeypatch.setattr(
        "tinyagentos.cli.worker.resolve_data_dir",
        lambda: tmp_path,
    )
    fake_config = types.SimpleNamespace(server={"litellm_port": 7834})
    monkeypatch.setattr(
        "tinyagentos.cli.worker.load_config",
        lambda path: fake_config,
    )

    # Controller API returns a verified port.
    class FakeControllerClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            return types.SimpleNamespace(
                status_code=200,
                json=lambda: {"port": 7838, "running": True},
                raise_for_status=lambda: None,
            )

    monkeypatch.setattr("httpx.AsyncClient", FakeControllerClient)

    # Track container creation to verify the deploy actually ran.
    created = []

    async def fake_create_container(name, **kwargs):
        created.append(name)
        return {"success": True, "name": name}

    async def fake_exec(name, cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "hostname" in cmd_str and "-I" in cmd_str:
            return (0, "10.0.0.5")
        return (0, "ok")

    async def fake_add_proxy_device(*a, **k):
        return {"success": True, "output": ""}

    monkeypatch.setattr("tinyagentos.deployer.create_container", fake_create_container)
    monkeypatch.setattr("tinyagentos.deployer.exec_in_container", fake_exec)
    monkeypatch.setattr("tinyagentos.deployer.push_file", lambda *a, **k: (0, ""))
    monkeypatch.setattr(
        "tinyagentos.deployer.add_proxy_device",
        fake_add_proxy_device,
    )

    # One agent row (no extra_config here; the controller query is the B1 fix).
    monkeypatch.setattr(
        "tinyagentos.cli.worker._load_agents_json",
        lambda: [
            {
                "name": "test-agent",
                "framework": "openclaw",
                "model": "gpt-4o",
                "data_dir": tmp_path,
            }
        ],
    )

    args = types.SimpleNamespace(controller_url="http://controller:6969", yes=True)
    rc = await _convert_to_lxc(args)
    assert rc == 0
    assert len(created) == 1
    assert created[0] == "taos-agent-test-agent"


@pytest.mark.asyncio
async def test_convert_to_lxc_exits_nonzero_when_redeploy_fails(monkeypatch, tmp_path):
    """_convert_to_lxc must return non-zero when any redeploy fails.

    On BASE it returns 0 and prints 'Convert-to-LXC complete.' regardless.
    """
    from tinyagentos.cli.worker import _convert_to_lxc

    monkeypatch.setattr(
        "tinyagentos.cli.worker.list_flat_mode_agents",
        lambda: [],
    )
    fake_run = types.SimpleNamespace(returncode=0)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_run)

    monkeypatch.setattr(
        "tinyagentos.cli.worker.resolve_data_dir",
        lambda: tmp_path,
    )
    fake_config = types.SimpleNamespace(server={"litellm_port": 7834})
    monkeypatch.setattr(
        "tinyagentos.cli.worker.load_config",
        lambda path: fake_config,
    )

    # Controller returns a verified port.
    class FakeControllerClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            return types.SimpleNamespace(
                status_code=200,
                json=lambda: {"port": 7838, "running": True},
                raise_for_status=lambda: None,
            )

    monkeypatch.setattr("httpx.AsyncClient", FakeControllerClient)

    # redeploy_agents reports one failed agent.
    async def fake_redeploy(*args, **kwargs):
        return ["test-agent"]

    monkeypatch.setattr(
        "tinyagentos.cli.worker.redeploy_agents",
        fake_redeploy,
    )

    monkeypatch.setattr(
        "tinyagentos.cli.worker._load_agents_json",
        lambda: [{"name": "test-agent", "framework": "openclaw", "model": "gpt-4o", "data_dir": tmp_path}],
    )

    args = types.SimpleNamespace(controller_url="http://controller:6969", yes=True)
    rc = await _convert_to_lxc(args)
    assert rc != 0
