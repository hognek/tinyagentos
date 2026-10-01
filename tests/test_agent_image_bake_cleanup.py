"""Tests for bake cleanup: failed tmp delete logging and stale tmp sweep."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tinyagentos.agent_image import _bake_scripts_into_image, ensure_image_present


class TestBakeCleanup:
    """Tests for _bake_scripts_into_image cleanup behaviour."""

    @pytest.mark.asyncio
    async def test_bake_logs_failed_tmp_delete(self, caplog):
        """When the final delete returns rc=1, a WARNING with the tmp name is logged."""
        alias = "taos-hermes-base"
        tmp_name = f"taos-bake-{alias}-tmp"
        launched = []

        async def _fake_launch(*args, **kwargs):
            launched.append(args)
            proc = MagicMock()
            # launch succeeds
            if args[:2] == ("incus", "launch"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # stop succeeds
            elif args[:2] == ("incus", "stop"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # image delete succeeds
            elif args[:2] == ("incus", "image"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # publish succeeds
            elif args[:2] == ("incus", "publish"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # FINAL delete fails with rc=1
            elif args[:2] == ("incus", "delete") and "--force" in args:
                proc.returncode = 1
                proc.communicate = AsyncMock(return_value=(b"delete failed: container busy", b""))
            else:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.wait = AsyncMock(return_value=proc.returncode)
            proc.stdout = MagicMock()
            proc.stdout.close = MagicMock()
            return proc

        with patch("asyncio.create_subprocess_exec", new=_fake_launch), \
             patch("tinyagentos.containers.push_file", new=AsyncMock()), \
             patch("tinyagentos.containers.exec_in_container", new=AsyncMock()), \
             caplog.at_level(logging.WARNING):
            await _bake_scripts_into_image(alias)

        # Verify the delete was attempted
        delete_calls = [c for c in launched if c[:2] == ("incus", "delete") and "--force" in c]
        assert len(delete_calls) == 1, "final delete should be attempted"
        assert delete_calls[0][2] == tmp_name

        # Verify WARNING is logged with the tmp container name
        warning_logs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(tmp_name in msg for msg in warning_logs), (
            f"Expected WARNING containing '{tmp_name}', got: {warning_logs}"
        )
        assert any("delete" in msg.lower() for msg in warning_logs), (
            f"Expected WARNING mentioning delete, got: {warning_logs}"
        )

    @pytest.mark.asyncio
    async def test_bake_sweeps_stale_tmp_before_launch(self):
        """When a stale tmp container exists, it is deleted before launch."""
        alias = "taos-hermes-base"
        tmp_name = f"taos-bake-{alias}-tmp"
        launched = []

        async def _fake_launch(*args, **kwargs):
            launched.append(args)
            proc = MagicMock()
            # incus list shows the stale tmp container exists
            if args[:2] == ("incus", "list"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(f"{tmp_name}\n".encode(), b""))
            # sweep delete should happen before launch
            elif args[:2] == ("incus", "delete") and "--force" in args:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # launch succeeds
            elif args[:2] == ("incus", "launch"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # stop succeeds
            elif args[:2] == ("incus", "stop"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # image delete succeeds
            elif args[:2] == ("incus", "image"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # publish succeeds
            elif args[:2] == ("incus", "publish"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # final delete succeeds
            elif args[:2] == ("incus", "delete") and "--force" in args:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.wait = AsyncMock(return_value=proc.returncode)
            proc.stdout = MagicMock()
            proc.stdout.close = MagicMock()
            return proc

        with patch("asyncio.create_subprocess_exec", new=_fake_launch), \
             patch("tinyagentos.containers.push_file", new=AsyncMock()), \
             patch("tinyagentos.containers.exec_in_container", new=AsyncMock()):
            await _bake_scripts_into_image(alias)

        # Find indices of key operations
        list_idx = next(i for i, c in enumerate(launched) if c[:2] == ("incus", "list"))
        sweep_delete_idx = next(i for i, c in enumerate(launched) if c[:2] == ("incus", "delete") and "--force" in c and c[2] == tmp_name)
        launch_idx = next(i for i, c in enumerate(launched) if c[:2] == ("incus", "launch"))

        # Sweep delete must run before launch
        assert sweep_delete_idx < launch_idx, (
            f"Sweep delete (idx {sweep_delete_idx}) must run before launch (idx {launch_idx})"
        )
        # List should run before sweep delete (to discover the stale container)
        assert list_idx < sweep_delete_idx, (
            f"incus list (idx {list_idx}) must run before sweep delete (idx {sweep_delete_idx})"
        )

    @pytest.mark.asyncio
    async def test_ensure_image_present_calls_sweep_on_startup(self):
        """ensure_image_present calls the sweep helper before bake."""
        alias = "taos-hermes-base"
        tmp_name = f"taos-bake-{alias}-tmp"
        launched = []

        async def _fake_launch(*args, **kwargs):
            launched.append(args)
            proc = MagicMock()
            # is_image_present: image not present
            if args[:3] == ("incus", "image", "list"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # curl download
            elif args[0] == "curl":
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # incus image import
            elif args[:3] == ("incus", "image", "import"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"imported\n", b""))
            # sweep: incus list shows stale tmp
            elif args[:2] == ("incus", "list"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(f"{tmp_name}\n".encode(), b""))
            # sweep delete
            elif args[:2] == ("incus", "delete") and "--force" in args:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # bake launch
            elif args[:2] == ("incus", "launch"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # bake stop
            elif args[:2] == ("incus", "stop"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # bake image delete
            elif args[:2] == ("incus", "image"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # bake publish
            elif args[:2] == ("incus", "publish"):
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            # bake final delete
            elif args[:2] == ("incus", "delete") and "--force" in args:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.wait = AsyncMock(return_value=proc.returncode)
            proc.stdout = MagicMock()
            proc.stdout.close = MagicMock()
            return proc

        with patch("asyncio.create_subprocess_exec", new=_fake_launch), \
             patch("tinyagentos.containers.push_file", new=AsyncMock()), \
             patch("tinyagentos.containers.exec_in_container", new=AsyncMock()):
            await ensure_image_present(alias=alias, url="http://example.test/img.tar.gz")

        # Find indices: sweep delete (from ensure_image_present) should run before bake launch
        sweep_delete_indices = [i for i, c in enumerate(launched) if c[:2] == ("incus", "delete") and "--force" in c and c[2] == tmp_name]
        bake_launch_idx = next(i for i, c in enumerate(launched) if c[:2] == ("incus", "launch"))

        # At least one sweep delete (from ensure_image_present path) should run before bake launch
        assert any(idx < bake_launch_idx for idx in sweep_delete_indices), (
            f"Sweep delete from ensure_image_present should run before bake launch; "
            f"sweep indices: {sweep_delete_indices}, bake launch: {bake_launch_idx}"
        )