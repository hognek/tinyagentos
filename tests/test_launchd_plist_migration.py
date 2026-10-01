"""Tests for the macOS launchd plist migration function.

The migration rewrites old bare-uvicorn plists (from pre-#3313 installs) to use
the package entrypoint `python -m tinyagentos`, which starts the LLM gateway
agent listener. Without this, local agent deploys are refused because a
bare-uvicorn controller has no verified gateway port.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


def _make_old_uvicorn_plist(
    install_dir: str = "/Users/test/tinyagentos",
    host: str = "0.0.0.0",
    port: int = 6969,
) -> bytes:
    """Create a plist with bare uvicorn ProgramArguments (old installer format)."""
    plist = {
        "Label": "com.tinyagentos.controller",
        "ProgramArguments": [
            f"{install_dir}/.venv/bin/python",
            "-m",
            "uvicorn",
            "tinyagentos.app:create_app",
            f"--host={host}",
            f"--port={port}",
        ],
        "WorkingDirectory": install_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": f"{install_dir}/controller.log",
        "StandardErrorPath": f"{install_dir}/controller.err",
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "TAOS_BROWSER_PROXY_PORT": "6970",
            "TAOS_SPA_DIR": f"{install_dir}/static/desktop",
        },
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


def _make_migrated_plist(
    install_dir: str = "/Users/test/tinyagentos",
    host: str = "0.0.0.0",
    port: int = 6969,
) -> bytes:
    """Create a plist already using the new entrypoint (idempotent test)."""
    plist = {
        "Label": "com.tinyagentos.controller",
        "ProgramArguments": [
            f"{install_dir}/.venv/bin/python",
            "-m",
            "tinyagentos",
        ],
        "WorkingDirectory": install_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": f"{install_dir}/controller.log",
        "StandardErrorPath": f"{install_dir}/controller.err",
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "TAOS_HOST": host,
            "TAOS_PORT": str(port),
            "TAOS_BROWSER_PROXY_PORT": "6970",
            "TAOS_SPA_DIR": f"{install_dir}/static/desktop",
        },
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


def _make_plist_with_tinyagentos_app_module(
    install_dir: str = "/Users/test/tinyagentos",
    host: str = "0.0.0.0",
    port: int = 6969,
) -> bytes:
    """Create a plist with uvicorn and tinyagentos.app: module reference (another old pattern)."""
    plist = {
        "Label": "com.tinyagentos.controller",
        "ProgramArguments": [
            f"{install_dir}/.venv/bin/python",
            "-m",
            "uvicorn",
            "tinyagentos.app:app",
            f"--host={host}",
            f"--port={port}",
        ],
        "WorkingDirectory": install_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": f"{install_dir}/controller.log",
        "StandardErrorPath": f"{install_dir}/controller.err",
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "TAOS_BROWSER_PROXY_PORT": "6970",
            "TAOS_SPA_DIR": f"{install_dir}/static/desktop",
        },
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


class TestMigrateLaunchdPlist:
    """Tests for the pure migration function."""

    @pytest.mark.asyncio
    async def test_old_uvicorn_plist_migrates_to_module_entrypoint(self):
        """An old bare-uvicorn plist migrates to `-m tinyagentos` with TAOS_HOST/PORT."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        old_plist = _make_old_uvicorn_plist()
        result = migrate_launchd_plist(old_plist, install_dir="/Users/test/tinyagentos")

        assert result is not None, "migration should return new plist bytes"
        parsed = plistlib.loads(result)

        # ProgramArguments rewritten to module entrypoint
        assert parsed["ProgramArguments"] == [
            "/Users/test/tinyagentos/.venv/bin/python",
            "-m",
            "tinyagentos",
        ], f"ProgramArguments: {parsed['ProgramArguments']}"

        # EnvironmentVariables has TAOS_HOST and TAOS_PORT from old --host/--port args
        env = parsed["EnvironmentVariables"]
        assert env["TAOS_HOST"] == "0.0.0.0"
        assert env["TAOS_PORT"] == "6969"

        # Other env vars preserved
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env["TAOS_BROWSER_PROXY_PORT"] == "6970"
        assert env["TAOS_SPA_DIR"] == "/Users/test/tinyagentos/static/desktop"

        # All other keys preserved
        assert parsed["Label"] == "com.tinyagentos.controller"
        assert parsed["WorkingDirectory"] == "/Users/test/tinyagentos"
        assert parsed["RunAtLoad"] is True
        assert parsed["KeepAlive"] is True
        assert parsed["StandardOutPath"] == "/Users/test/tinyagentos/controller.log"
        assert parsed["StandardErrorPath"] == "/Users/test/tinyagentos/controller.err"

    @pytest.mark.asyncio
    async def test_plist_with_tinyagentos_app_module_reference_migrates(self):
        """A plist with `uvicorn tinyagentos.app:app` also migrates."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        old_plist = _make_plist_with_tinyagentos_app_module()
        result = migrate_launchd_plist(old_plist, install_dir="/Users/test/tinyagentos")

        assert result is not None
        parsed = plistlib.loads(result)

        assert parsed["ProgramArguments"] == [
            "/Users/test/tinyagentos/.venv/bin/python",
            "-m",
            "tinyagentos",
        ]

        env = parsed["EnvironmentVariables"]
        assert env["TAOS_HOST"] == "0.0.0.0"
        assert env["TAOS_PORT"] == "6969"

    @pytest.mark.asyncio
    async def test_already_migrated_plist_returns_none_idempotent(self):
        """An already-migrated plist returns None (idempotent)."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        migrated_plist = _make_migrated_plist()
        result = migrate_launchd_plist(migrated_plist, install_dir="/Users/test/tinyagentos")

        assert result is None, "already-migrated plist should return None"

    @pytest.mark.asyncio
    async def test_non_tinyagentos_plist_returns_none(self):
        """A plist for a different service returns None (no-op)."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        other_plist = {
            "Label": "com.other.service",
            "ProgramArguments": ["/usr/bin/python", "-m", "uvicorn", "app:app"],
        }
        result = migrate_launchd_plist(plistlib.dumps(other_plist), install_dir="/any/path")
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_all_other_keys_and_env_vars(self):
        """All keys and env vars not explicitly migrated are preserved."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        # Add extra custom keys and env vars
        plist = {
            "Label": "com.tinyagentos.controller",
            "ProgramArguments": [
                "/Users/test/tinyagentos/.venv/bin/python",
                "-m",
                "uvicorn",
                "tinyagentos.app:create_app",
                "--host=127.0.0.1",
                "--port=8080",
            ],
            "WorkingDirectory": "/Users/test/tinyagentos",
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": "/Users/test/tinyagentos/controller.log",
            "StandardErrorPath": "/Users/test/tinyagentos/controller.err",
            "EnvironmentVariables": {
                "PYTHONUNBUFFERED": "1",
                "TAOS_BROWSER_PROXY_PORT": "6970",
                "TAOS_SPA_DIR": "/Users/test/tinyagentos/static/desktop",
                "CUSTOM_VAR": "custom_value",
                "ANOTHER_VAR": "another_value",
            },
            "CustomKey": "custom_value",
            "AnotherKey": 42,
        }
        old_bytes = plistlib.dumps(plist, fmt=plistlib.FMT_XML)
        result = migrate_launchd_plist(old_bytes, install_dir="/Users/test/tinyagentos")

        assert result is not None
        parsed = plistlib.loads(result)

        # Custom env vars preserved
        assert parsed["EnvironmentVariables"]["CUSTOM_VAR"] == "custom_value"
        assert parsed["EnvironmentVariables"]["ANOTHER_VAR"] == "another_value"

        # Custom top-level keys preserved
        assert parsed["CustomKey"] == "custom_value"
        assert parsed["AnotherKey"] == 42

    @pytest.mark.asyncio
    async def test_invalid_plist_returns_none_no_crash(self):
        """Invalid plist bytes return None without raising (safety)."""
        from tinyagentos.launchd_migration import migrate_launchd_plist

        result = migrate_launchd_plist(b"not a valid plist", install_dir="/any/path")
        assert result is None


class TestDarwinGate:
    """Tests that the migration is only called on Darwin."""

    def test_update_calls_migration_only_on_darwin(self, monkeypatch):
        """The update path calls _maybe_migrate_launchd_plist only when sys.platform == 'darwin'."""
        from unittest.mock import patch

        # Track calls to the internal migrate function
        calls = []

        def fake_migrate(plist_bytes, install_dir):
            calls.append((plist_bytes, install_dir))
            return None  # already migrated

        # Monkeypatch sys.platform
        for platform in ("darwin", "linux", "win32"):
            calls.clear()
            monkeypatch.setattr("sys.platform", platform)

            with patch(
                "tinyagentos.launchd_migration.migrate_launchd_plist",
                new=fake_migrate,
            ):
                # Simulate the update path calling the migration
                from tinyagentos.launchd_migration import _maybe_migrate_launchd_plist

                # This function wraps the platform check
                _maybe_migrate_launchd_plist(b"dummy", "/install/dir")

            if platform == "darwin":
                assert len(calls) == 1, f"migration should be called on {platform}"
            else:
                assert len(calls) == 0, f"migration should NOT be called on {platform}"


class TestApplyLaunchdMigrationNoSubprocess:
    """apply_launchd_migration must not call launchctl from the controller process."""

    def test_apply_launchd_migration_spawns_no_launchctl(self, tmp_path, monkeypatch):
        """apply_launchd_migration on an old plist must NOT call any launchctl subprocess."""
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock

        plist_path = tmp_path / "com.tinyagentos.controller.plist"
        old_plist = _make_old_uvicorn_plist(install_dir="/tmp/test")
        plist_path.write_bytes(old_plist)

        monkeypatch.setattr(
            "tinyagentos.launchd_migration.PLIST_PATH",
            plist_path,
        )
        monkeypatch.setattr("sys.platform", "darwin")

        subprocess_calls = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            subprocess_calls.append(args)
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.wait = AsyncMock()
            return mock_proc

        from tinyagentos.launchd_migration import apply_launchd_migration

        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            result = asyncio.run(apply_launchd_migration("/tmp/test"))

        launchctl_calls = [c for c in subprocess_calls if c and c[0] == "launchctl"]
        assert len(launchctl_calls) == 0, (
            f"Expected no launchctl calls, got: {launchctl_calls}"
        )


class TestAtomicWrite:
    """Atomic write must not clobber the live plist on failure."""

    def test_write_failure_leaves_original_plist_in_place(self, tmp_path, monkeypatch):
        """If the atomic write fails, the original plist must not be touched."""
        plist_path = tmp_path / "com.tinyagentos.controller.plist"
        original_plist = _make_old_uvicorn_plist(install_dir="/tmp/test")
        plist_path.write_bytes(original_plist)

        monkeypatch.setattr(
            "tinyagentos.launchd_migration.PLIST_PATH",
            plist_path,
        )
        monkeypatch.setattr("sys.platform", "darwin")

        # Import atomic_write_bytes to patch it where it's actually used
        from tinyagentos.launchd_migration import atomic_write_bytes

        original_atomic_write_bytes = atomic_write_bytes

        def fake_atomic_write_bytes(path, data, *, mode=None):
            # Simulate a write failure
            raise OSError("simulated write failure")

        with patch("tinyagentos.launchd_migration.atomic_write_bytes", side_effect=fake_atomic_write_bytes):
            from tinyagentos.launchd_migration import apply_launchd_migration
            import asyncio

            result = asyncio.run(apply_launchd_migration("/tmp/test"))

        assert plist_path.read_bytes() == original_plist, (
            "Original plist was modified despite write failure"
        )


# Helper to run RED-FIRST: we write a stub that returns None
# The tests above will fail until the real implementation exists.
# We also need the _maybe_migrate_launchd_plist function in settings.py

if __name__ == "__main__":
    pytest.main([__file__, "-v"])