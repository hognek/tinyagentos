"""Tests for upstream release detection (tinyagentos/upstream_versions.py).

Covers:
- Tag selection: ignore ``latest``/non-version tags, pick the newest
  semver/calver tag matching the pinned tag's shape, from recorded
  registry JSON fixtures.
- Registry fetching: Docker Hub v2 repositories API, GHCR (token +
  v2 tags/list) and the generic Registry v2 endpoint, via a fake
  httpx client serving the recorded fixtures.
- The cached, never-network request path: upstream_info /
  compare_versions / record_upstream.
- The API field: /api/store/catalog exposes update_available,
  upstream_version, upstream_update_available and upstream_checked_at,
  and the request path never calls a registry.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tinyagentos import upstream_versions as uv


FIXTURES = Path(__file__).parent / "fixtures" / "upstream_versions"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _fixture_tags(name: str) -> list[str]:
    """Flatten a recorded registry response into its tag list."""
    data = _load_fixture(name)
    if "results" in data:  # Docker Hub v2 repositories API
        return [t["name"] for t in data["results"]]
    return data["tags"]  # Docker Registry v2 tags/list (GHCR et al.)


# --------------------------------------------------------------------------- #
# Fake httpx client serving recorded registry responses
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeRegistryClient:
    """Minimal async stand-in for httpx.AsyncClient.

    Routes requests by URL substring and records every call so tests
    can assert which registry endpoints were hit. Raises on any URL it
    was not given a fixture for, so an unexpected endpoint fails loudly.
    """

    def __init__(self, routes: dict[str, _FakeResponse]):
        self._routes = routes
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        for needle, response in self._routes.items():
            if needle in url:
                return response
        raise AssertionError(f"unexpected registry request: {url}")

    async def aclose(self):
        pass

    def urls(self) -> list[str]:
        return [c[0] for c in self.calls]

    def params_of(self, url_needle: str) -> dict | None:
        for url, params, _headers in self.calls:
            if url_needle in url:
                return params
        raise AssertionError(f"no request matched {url_needle}")


def _docker_hub_client(fixture: str, status: int = 200) -> FakeRegistryClient:
    return FakeRegistryClient({
        "hub.docker.com/v2/repositories/": _FakeResponse(status, _load_fixture(fixture)),
    })


# --------------------------------------------------------------------------- #
# Tag selection (recorded registry JSON fixtures)
# --------------------------------------------------------------------------- #


class TestTagShape:
    def test_version_shapes(self):
        assert uv.tag_shape("2024.12.0") == (False, 3)
        assert uv.tag_shape("2026.10.2") == (False, 3)
        assert uv.tag_shape("v1.13.0") == (True, 3)
        assert uv.tag_shape("1.22") == (False, 2)
        assert uv.tag_shape("20241115") == (False, 1)

    def test_non_version_tags_have_no_shape(self):
        # latest/stable/variant suffixes must never match a version pin.
        for tag in ("latest", "stable", "alpine", "bookworm", "edge"):
            assert uv.tag_shape(tag) is None, tag


class TestSelectUpstreamTag:
    def test_picks_newest_calver_and_ignores_latest(self):
        # Recorded searxng/searxng tag list: catalog pin is 2024.12.0.
        tags = _fixture_tags("dockerhub-searxng.json")
        assert "latest" in tags
        assert uv.select_upstream_tag("2024.12.0", tags) == "2026.10.2"

    def test_picks_newest_semver_of_same_shape(self):
        # Recorded uptime-kuma tag list: 2-part pin must not match the
        # 3-part or -alpine variants of a newer release.
        tags = _fixture_tags("dockerhub-uptime-kuma.json")
        assert uv.select_upstream_tag("1.22", tags) == "1.23"

    def test_v_prefix_pin_matches_only_v_prefixed_tags(self):
        tags = ["latest", "v1.13.0", "v1.14.0", "1.15.0"]
        assert uv.select_upstream_tag("v1.13.0", tags) == "v1.14.0"

    def test_ghcr_tags_newest_matching_shape(self):
        # Recorded GHCR docker-mailserver tag list.
        tags = _fixture_tags("ghcr-mailserver.json")
        assert uv.select_upstream_tag("13.2.0", tags) == "14.0.0"
        # Nothing newer than the pin in this shape: pre-release edges
        # builds do not count as newer than the GA they belong to.
        assert uv.select_upstream_tag("14.0.0", tags) == "14.0.0"

    def test_calver_date_tags(self):
        # Recorded whisper image tag list: date-shaped calver tags.
        tags = _fixture_tags("dockerhub-whisper.json")
        assert uv.select_upstream_tag("20241115", tags) == "20251208"

    def test_latest_only_returns_none(self):
        assert uv.select_upstream_tag("2024.12.0", ["latest"]) is None

    def test_no_matching_shape_returns_none(self):
        assert uv.select_upstream_tag("1.22", ["latest", "2024.12.0"]) is None

    def test_non_version_pin_returns_none(self):
        # A non-version pin (e.g. memos:stable) cannot be shape-matched.
        assert uv.select_upstream_tag("stable", ["stable", "2026.10.2"]) is None
        assert uv.select_upstream_tag("latest", ["latest", "2026.10.2"]) is None

    def test_empty_tag_list_returns_none(self):
        assert uv.select_upstream_tag("2024.12.0", []) is None


# --------------------------------------------------------------------------- #
# Registry fetching (fake client over recorded fixtures)
# --------------------------------------------------------------------------- #


class TestFetchRegistryTags:
    @pytest.mark.asyncio
    async def test_docker_hub_v2_api(self):
        fake = _docker_hub_client("dockerhub-searxng.json")
        tags = await uv.fetch_registry_tags("searxng/searxng:2024.12.0", client=fake)
        assert tags == _fixture_tags("dockerhub-searxng.json")
        url = fake.urls()[0]
        assert url.startswith("https://hub.docker.com/v2/repositories/searxng/searxng/tags")
        assert fake.params_of("repositories/searxng/searxng/tags") == {
            "ordering": "last_updated", "page_size": 100,
        }

    @pytest.mark.asyncio
    async def test_docker_hub_official_image_prefixes_library(self):
        fake = _docker_hub_client("dockerhub-uptime-kuma.json")
        await uv.fetch_registry_tags("uptime-kuma:1.22", client=fake)
        assert any("repositories/library/uptime-kuma/tags" in u for u in fake.urls())

    @pytest.mark.asyncio
    async def test_ghcr_token_then_v2_tags_list(self):
        fake = FakeRegistryClient({
            "ghcr.io/token": _FakeResponse(200, {"token": "test-token"}),
            "ghcr.io/v2/": _FakeResponse(200, _load_fixture("ghcr-mailserver.json")),
        })
        tags = await uv.fetch_registry_tags(
            "ghcr.io/docker-mailserver/docker-mailserver:13.2.0", client=fake
        )
        assert tags == _fixture_tags("ghcr-mailserver.json")
        # Token request carries the pull scope; the list request carries
        # the bearer token.
        token_params = fake.params_of("ghcr.io/token")
        assert token_params["scope"] == "repository:docker-mailserver/docker-mailserver:pull"
        list_call = next(c for c in fake.calls if "ghcr.io/v2/" in c[0])
        assert list_call[2] == {"Authorization": "Bearer test-token"}

    @pytest.mark.asyncio
    async def test_generic_registry_v2(self):
        fake = FakeRegistryClient({
            "lscr.io/v2/": _FakeResponse(200, {"tags": ["4.135.0", "latest"]}),
        })
        tags = await uv.fetch_registry_tags(
            "lscr.io/linuxserver/code-server:4.135.0", client=fake
        )
        assert tags == ["4.135.0", "latest"]
        assert fake.urls()[0] == "https://lscr.io/v2/linuxserver/code-server/tags/list"

    @pytest.mark.asyncio
    async def test_registry_error_returns_none(self):
        fake = _docker_hub_client("dockerhub-searxng.json", status=503)
        assert await uv.fetch_registry_tags("searxng/searxng:2024.12.0", client=fake) is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        class _ExplodingClient:
            async def get(self, *a, **k):
                raise uv.httpx.ConnectError("no network")

        assert await uv.fetch_registry_tags(
            "searxng/searxng:2024.12.0", client=_ExplodingClient()
        ) is None

    @pytest.mark.asyncio
    async def test_unparsable_image_ref_returns_none(self):
        # LXC-style refs (images:debian/bookworm) are not docker images.
        assert await uv.fetch_registry_tags("images:debian/bookworm") is None


# --------------------------------------------------------------------------- #
# Cached request path
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_cache():
    uv._reset_cache_for_tests()
    yield
    uv._reset_cache_for_tests()


class TestCachedRequestPath:
    def test_record_then_read(self):
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        info = uv.upstream_info("searxng")
        assert info is not None
        assert info["upstream_version"] == "2026.10.2"
        assert isinstance(info["upstream_checked_at"], float)

    def test_unknown_app_reads_none(self):
        assert uv.upstream_info("nope") is None

    def test_compare_versions(self):
        assert uv.compare_versions("2024.12.0", "2026.10.2") is True
        assert uv.compare_versions("2024.12.0", "2024.12.0") is False
        assert uv.compare_versions("2024.12.0", "2024.11.9") is False
        # Unknown upstream is None (unknown), never False ("no update").
        assert uv.compare_versions("2024.12.0", None) is None
        # Unparseable versions are unknown too.
        assert uv.compare_versions("nightly", "2026.10.2") is None

    def test_failure_records_unknown_with_retry_ttl(self):
        uv.record_upstream("searxng", None, ok=False)
        info = uv.upstream_info("searxng")
        assert info["upstream_version"] is None
        entry = uv._cache["searxng"]
        # Short TTL so the warmer retries within the hour.
        assert entry["expires_at"] - entry["checked_at"] < uv._CHECK_TTL

    def test_success_records_daily_ttl(self):
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        entry = uv._cache["searxng"]
        assert entry["expires_at"] - entry["checked_at"] == uv._CHECK_TTL

    def test_cache_persists_across_cold_boot(self, tmp_path):
        """The cache is recorded to data_dir/upstream_versions.json.

        A cold boot reuses the last known versions instead of
        reading "unknown" until the warmer's first pass.
        """
        uv.configure_persistence(tmp_path)
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        persisted = tmp_path / "upstream_versions.json"
        assert persisted.exists()
        # Simulate a restart: clear in-memory state, reload from
        # the same data dir.
        uv._reset_cache_for_tests()
        uv.configure_persistence(tmp_path)
        info = uv.upstream_info("searxng")
        assert info is not None
        assert info["upstream_version"] == "2026.10.2"


class TestCheckUpstream:
    def _docker_app(self, app_id: str, image: str, version: str = "1.0.0"):
        return SimpleNamespace(
            id=app_id, version=version,
            install={"method": "docker", "image": image},
        )

    @pytest.mark.asyncio
    async def test_docker_app_checked_against_registry(self):
        fake = _docker_hub_client("dockerhub-searxng.json")
        reached, tag = await uv.check_upstream(
            self._docker_app("searxng", "searxng/searxng:2024.12.0"), client=fake
        )
        assert reached is True
        assert tag == "2026.10.2"

    @pytest.mark.asyncio
    async def test_non_docker_app_not_checked(self):
        app = SimpleNamespace(id="gitea", version="1.0.0", install={"method": "lxc"})
        reached, tag = await uv.check_upstream(app, client=FakeRegistryClient({}))
        assert reached is True
        assert tag is None

    @pytest.mark.asyncio
    async def test_registry_failure_records_unknown(self):
        fake = _docker_hub_client("dockerhub-searxng.json", status=503)
        reached, tag = await uv.check_upstream(
            self._docker_app("searxng", "searxng/searxng:2024.12.0"), client=fake
        )
        assert reached is False
        assert tag is None


class TestWarmUpstreamCache:
    def _docker_app(self, app_id: str, image: str):
        return SimpleNamespace(
            id=app_id, version="1.0.0",
            install={"method": "docker", "image": image},
        )

    @pytest.mark.asyncio
    async def test_warm_records_newest_tag_per_app(self):
        fake = FakeRegistryClient({
            "hub.docker.com/v2/repositories/searxng/searxng/tags": _FakeResponse(
                200, _load_fixture("dockerhub-searxng.json")
            ),
            "hub.docker.com/v2/repositories/louislam/uptime-kuma/tags": _FakeResponse(
                200, _load_fixture("dockerhub-uptime-kuma.json")
            ),
        })
        apps = [
            self._docker_app("searxng", "searxng/searxng:2024.12.0"),
            self._docker_app("uptime-kuma", "louislam/uptime-kuma:1.22"),
            SimpleNamespace(id="gitea", version="1.0.0", install={"method": "lxc"}),
        ]
        await uv.warm_upstream_cache(apps, client=fake)
        assert uv.upstream_info("searxng")["upstream_version"] == "2026.10.2"
        assert uv.upstream_info("uptime-kuma")["upstream_version"] == "1.23"
        # Non-docker apps are never queried.
        assert uv.upstream_info("gitea") is None

    @pytest.mark.asyncio
    async def test_fresh_entries_are_not_rechecked(self):
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        fake = FakeRegistryClient({
            "hub.docker.com/v2/repositories/": _FakeResponse(
                200, _load_fixture("dockerhub-searxng.json")
            ),
        })
        apps = [self._docker_app("searxng", "searxng/searxng:2024.12.0")]
        await uv.warm_upstream_cache(apps, client=fake)
        assert fake.calls == []
        assert uv.upstream_info("searxng")["upstream_version"] == "2026.10.2"

    @pytest.mark.asyncio
    async def test_network_failure_is_unknown_not_no_update(self):
        fake = FakeRegistryClient({
            "hub.docker.com/v2/repositories/": _FakeResponse(503, {"detail": "down"}),
        })
        apps = [self._docker_app("searxng", "searxng/searxng:2024.12.0")]
        await uv.warm_upstream_cache(apps, client=fake)
        info = uv.upstream_info("searxng")
        assert info["upstream_version"] is None
        assert uv.compare_versions("2024.12.0", info["upstream_version"]) is None


# --------------------------------------------------------------------------- #
# API field: /api/store/catalog
# --------------------------------------------------------------------------- #


def _fake_manifest(app_id: str, version: str, install: dict):
    a = MagicMock()
    a.id = app_id
    a.name = app_id
    a.type = "service"
    a.category = ""
    a.version = version
    a.description = ""
    a.icon = ""
    a.homepage = ""
    a.requires = {}
    a.install = install
    a.hardware_tiers = {}
    a.variants = []
    return a


def _fake_docker_manifest(app_id: str, version: str, image: str):
    return _fake_manifest(app_id, version, {"method": "docker", "image": image})


def _patch_registry(app, apps, installed_rows):
    installed_ids = {r.get("id") for r in installed_rows}
    reg = MagicMock()
    reg.list_available = MagicMock(return_value=apps)
    reg.list_installed = MagicMock(return_value=installed_rows)
    reg.is_installed = MagicMock(side_effect=lambda app_id: app_id in installed_ids)
    app.state.registry = reg
    app.state.installation_state = None


def _explode_on_live_fetch(monkeypatch):
    """Make any registry call from the request path blow up.

    The catalog route must serve the cached upstream state only; if it
    ever queried a registry, this would raise and the test would fail.
    """
    async def _boom(*a, **k):
        raise AssertionError("request path must not query a registry")

    monkeypatch.setattr(uv, "fetch_registry_tags", _boom)


class TestCatalogApiUpstreamFields:
    @pytest.mark.asyncio
    async def test_upstream_update_surfaces_in_catalog(self, client, monkeypatch):
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [{"id": "searxng", "version": "2024.12.0", "state": "installed"}],
        )
        # Simulate the background warmer's cached result: upstream
        # 2026.10.2 is newer than the 2024.12.0 catalog pin.
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        assert res.status_code == 200
        entry = res.json()[0]
        assert entry["update_available"] is True
        assert entry["upstream_version"] == "2026.10.2"
        assert entry["upstream_update_available"] is True
        assert isinstance(entry["upstream_checked_at"], float)

    @pytest.mark.asyncio
    async def test_upstream_only_update_with_same_installed_version(self, client, monkeypatch):
        """The stale-pin case: installed == catalog pin, upstream is newer.

        update_available must flip true purely from the upstream signal.
        """
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [{"id": "searxng", "version": "2024.12.0", "state": "installed"}],
        )
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["upstream_update_available"] is True
        assert entry["update_available"] is True

    @pytest.mark.asyncio
    async def test_failed_check_is_unknown_not_no_update(self, client, monkeypatch):
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [{"id": "searxng", "version": "2024.12.0", "state": "installed"}],
        )
        # The warmer's last check failed: unknown, so no update claim.
        uv.record_upstream("searxng", None, ok=False)
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["upstream_version"] is None
        assert entry["upstream_update_available"] is None
        assert entry["update_available"] is False

    @pytest.mark.asyncio
    async def test_never_checked_is_unknown(self, client, monkeypatch):
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [{"id": "searxng", "version": "2024.12.0", "state": "installed"}],
        )
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["upstream_version"] is None
        assert entry["upstream_update_available"] is None
        assert entry["update_available"] is False

    @pytest.mark.asyncio
    async def test_stale_catalog_pin_still_flags_update(self, client, monkeypatch):
        """Classic update: installed row is older than the catalog pin.

        Works with no upstream info at all (non-docker app).
        """
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_manifest("gitea", "1.22.0", {"method": "docker", "image": "gitea/gitea:1.22"})],
            [{"id": "gitea", "version": "1.21.0", "state": "installed"}],
        )
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["update_available"] is True
        assert entry["upstream_update_available"] is None

    @pytest.mark.asyncio
    async def test_not_installed_is_never_an_update(self, client, monkeypatch):
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [],
        )
        uv.record_upstream("searxng", "2026.10.2", ok=True)
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["installed"] is False
        assert entry["update_available"] is False
        # Upstream state is still reported for the detail view.
        assert entry["upstream_update_available"] is True

    @pytest.mark.asyncio
    async def test_upstream_older_than_pin_is_no_update(self, client, monkeypatch):
        app = client._transport.app
        _patch_registry(
            app,
            [_fake_docker_manifest("searxng", "2024.12.0", "searxng/searxng:2024.12.0")],
            [{"id": "searxng", "version": "2024.12.0", "state": "installed"}],
        )
        uv.record_upstream("searxng", "2024.11.0", ok=True)
        _explode_on_live_fetch(monkeypatch)

        res = await client.get("/api/store/catalog")
        entry = res.json()[0]
        assert entry["upstream_update_available"] is False
        assert entry["update_available"] is False
