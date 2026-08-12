import pytest
import yaml
from tinyagentos.config import load_config


@pytest.mark.asyncio
class TestConfigPage:
    async def test_get_config_api(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "yaml" in data
        parsed = yaml.safe_load(data["yaml"])
        assert parsed["server"]["port"] == 6969

    async def test_save_valid_config(self, client, tmp_data_dir):
        new_yaml = yaml.dump({
            "server": {"host": "0.0.0.0", "port": 9999},
            "backends": [],
            "qmd": {"url": "http://localhost:7832"},
            "agents": [],
            "metrics": {"poll_interval": 60, "retention_days": 7},
        })
        resp = await client.put("/api/config", json={"yaml": new_yaml})
        assert resp.status_code == 200
        config = load_config(tmp_data_dir / "config.yaml")
        assert config.server["port"] == 9999

    async def test_save_config_round_trips_lora_ingest_proxy_url(
        self, client, tmp_data_dir
    ):
        """GET returns the key, so PUTting that same YAML back must keep it.

        The config editor is a read-edit-write loop: any field the PUT handler
        forgets to rebuild is silently wiped the first time the user saves an
        unrelated setting.
        """
        new_yaml = yaml.dump({
            "server": {"host": "0.0.0.0", "port": 6969},
            "backends": [],
            "qmd": {"url": "http://localhost:7832"},
            "agents": [],
            "metrics": {"poll_interval": 60, "retention_days": 7},
            "lora_ingest_proxy_url": "http://proxy.example:3128",
        })
        resp = await client.put("/api/config", json={"yaml": new_yaml})
        assert resp.status_code == 200

        config = load_config(tmp_data_dir / "config.yaml")
        assert config.lora_ingest_proxy_url == "http://proxy.example:3128"

        # And it survives the next read of the API surface.
        resp = await client.get("/api/config")
        parsed = yaml.safe_load(resp.json()["yaml"])
        assert parsed["lora_ingest_proxy_url"] == "http://proxy.example:3128"

    async def test_save_invalid_yaml_fails(self, client):
        resp = await client.put("/api/config", json={"yaml": ": : : bad [["})
        assert resp.status_code == 400
        assert "error" in resp.json()

    async def test_save_invalid_config_fails(self, client):
        bad_config = yaml.dump({
            "server": {"host": "0.0.0.0", "port": 6969},
            "backends": [{"name": "bad", "type": "unsupported", "url": "http://x"}],
            "qmd": {"url": "http://localhost:7832"},
            "agents": [],
            "metrics": {"poll_interval": 30, "retention_days": 30},
        })
        resp = await client.put("/api/config", json={"yaml": bad_config})
        assert resp.status_code == 400

    async def test_validate_only(self, client):
        valid_config = yaml.dump({
            "server": {"host": "0.0.0.0", "port": 6969},
            "backends": [],
            "qmd": {"url": "http://localhost:7832"},
            "agents": [],
            "metrics": {"poll_interval": 30, "retention_days": 30},
        })
        resp = await client.put("/api/config?validate_only=true", json={"yaml": valid_config})
        assert resp.status_code == 200
        assert resp.json()["status"] == "valid"

    async def test_storage_api(self, client):
        resp = await client.get("/api/settings/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert "storage" in data
        assert isinstance(data["storage"], list)
        assert len(data["storage"]) >= 2
        for item in data["storage"]:
            assert "label" in item
            assert "path" in item
            assert "size" in item

    async def test_save_platform_settings(self, client, tmp_data_dir):
        resp = await client.put("/api/settings/platform", json={
            "poll_interval": 120,
            "retention_days": 14,
            "catalog_repo": "",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        config = load_config(tmp_data_dir / "config.yaml")
        assert config.metrics["poll_interval"] == 120
        assert config.metrics["retention_days"] == 14

