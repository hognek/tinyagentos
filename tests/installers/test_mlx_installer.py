"""Tests for the MLX (Apple Silicon) backend installer.

The macOS/MLX branch is never exercised by CI (Linux runners), so these
tests pin the three things that decide whether an MLX install is honest:
the Apple-Silicon gate, the `mlx-lm` runtime step, and the delegation of
the actual weight download into the shared ``~/models/mlx/`` layout.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tinyagentos.installers.mlx_installer import (
    DEFAULT_PORT,
    MLXInstaller,
    is_apple_silicon,
    metal_available,
    mlx_lm_installed,
)

MLX_VARIANT = {
    "id": "mlx-4bit",
    "hf_repo": "mlx-community/Qwen2.5-3B-Instruct-4bit",
    "size_mb": 1900,
}


def _fake_apple(monkeypatch, *, arm64: bool = True) -> None:
    """Make the platform probes report an Apple Silicon host."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "tinyagentos.installers.mlx_installer.platform.machine",
        lambda: "arm64" if arm64 else "x86_64",
    )


def _patch_hf_downloader():
    """Patch the HF multi-file downloader used for repo-backed variants."""
    fake_cls = MagicMock()
    fake_cls.return_value.install = AsyncMock(
        return_value={"success": True, "target_dir": "/models/mlx/qwen2.5/qwen2.5-3b"}
    )
    return patch("tinyagentos.installers.mlx_installer.HFMultiInstaller", fake_cls), fake_cls


def _patch_download_downloader():
    """Patch the single-file DownloadInstaller used for URL-backed variants."""
    fake_cls = MagicMock()
    fake_cls.return_value.install = AsyncMock(
        return_value={"success": True, "path": "/models/mlx/qwen2.5/qwen2.5-3b/model.gguf"}
    )
    return patch("tinyagentos.installers.mlx_installer.DownloadInstaller", fake_cls), fake_cls


class TestAvailabilityProbes:
    def test_not_apple_silicon_off_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "tinyagentos.installers.mlx_installer.platform.machine", lambda: "x86_64"
        )
        assert is_apple_silicon() is False
        assert metal_available() is False

    def test_intel_mac_is_not_metal(self, monkeypatch):
        """Darwin/x86_64 (Intel Mac) has no unified-memory GPU — CPU only."""
        _fake_apple(monkeypatch, arm64=False)
        assert is_apple_silicon() is False
        assert metal_available() is False

    def test_apple_silicon_reports_metal(self, monkeypatch):
        _fake_apple(monkeypatch)
        assert is_apple_silicon() is True
        assert metal_available() is True

    def test_mlx_lm_installed_reads_the_interpreter(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        assert mlx_lm_installed() is False
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        assert mlx_lm_installed() is True


@pytest.mark.asyncio
class TestMLXInstallerInstall:
    async def test_rejects_non_apple_silicon_host(self, monkeypatch):
        """No MLX on Linux/Intel: fail loudly instead of 'installing' a file
        the runtime can never load."""
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "tinyagentos.installers.mlx_installer.platform.machine", lambda: "x86_64"
        )
        with patch("tinyagentos.installers.mlx_installer.HFMultiInstaller") as hf:
            result = await MLXInstaller().install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=MLX_VARIANT
            )
        assert result["success"] is False
        assert "Apple Silicon" in result["error"]
        hf.assert_not_called()

    async def test_requires_a_variant(self, monkeypatch):
        _fake_apple(monkeypatch)
        result = await MLXInstaller().install("qwen2.5-3b", install_config={})
        assert result["success"] is False
        assert "variant" in result["error"]

    async def test_requires_a_repo_or_download_url(self, monkeypatch):
        _fake_apple(monkeypatch)
        result = await MLXInstaller().install(
            "qwen2.5-3b", install_config={}, variant={"id": "empty"}
        )
        assert result["success"] is False
        assert "mlx_repo" in result["error"]

    async def test_hf_repo_variant_goes_through_the_multi_file_downloader(
        self, monkeypatch, tmp_path
    ):
        _fake_apple(monkeypatch)
        patcher, fake_cls = _patch_hf_downloader()
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b",
                install_config={"backend": "mlx"},
                variant=MLX_VARIANT,
            )

        assert result["success"] is True
        assert fake_cls.call_args.kwargs["_root_override"] == tmp_path
        call = fake_cls.return_value.install.await_args
        assert call.args[0] == "qwen2.5-3b"
        assert call.kwargs["variant"]["hf_repo"] == MLX_VARIANT["hf_repo"]
        # The dispatcher's backend marker survives, so the repo lands under
        # ~/models/mlx/... rather than the huggingface default.
        assert call.kwargs["install_config"]["backend"] == "mlx"

    async def test_hf_repo_variant_defaults_backend_to_mlx(self, monkeypatch, tmp_path):
        """A direct (non-dispatcher) call still writes into the mlx tree."""
        _fake_apple(monkeypatch)
        patcher, fake_cls = _patch_hf_downloader()
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={}, variant=MLX_VARIANT
            )
        call = fake_cls.return_value.install.await_args
        assert call.kwargs["install_config"]["backend"] == "mlx"

    async def test_mlx_repo_overrides_hf_repo(self, monkeypatch, tmp_path):
        """A manifest can aim the MLX variant at a pre-quantised repo while
        keeping its GGUF hf_repo for the other backends."""
        _fake_apple(monkeypatch)
        patcher, fake_cls = _patch_hf_downloader()
        variant = dict(MLX_VARIANT, mlx_repo="mlx-community/Qwen3-4B-8bit")
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=variant
            )
        call = fake_cls.return_value.install.await_args
        assert call.kwargs["variant"]["hf_repo"] == "mlx-community/Qwen3-4B-8bit"

    async def test_blank_mlx_repo_falls_back_to_hf_repo(self, monkeypatch, tmp_path):
        """A whitespace-only mlx_repo is not "set" — it must not shadow a valid
        hf_repo and reject the install."""
        _fake_apple(monkeypatch)
        patcher, fake_cls = _patch_hf_downloader()
        variant = dict(MLX_VARIANT, mlx_repo="   ")
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=variant
            )
        assert result["success"] is True
        call = fake_cls.return_value.install.await_args
        assert call.kwargs["variant"]["hf_repo"] == MLX_VARIANT["hf_repo"]

    async def test_single_file_variant_falls_back_to_download_installer(
        self, monkeypatch, tmp_path
    ):
        _fake_apple(monkeypatch)
        patcher, fake_cls = _patch_download_downloader()
        variant = {"id": "gguf", "download_url": "https://example/q4.gguf"}
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=variant
            )
        assert result["success"] is True
        call = fake_cls.return_value.install.await_args
        assert call.kwargs["variant"] == variant

    async def test_result_reports_mlx_runtime_endpoint(self, monkeypatch, tmp_path):
        _fake_apple(monkeypatch)
        patcher, _ = _patch_hf_downloader()
        with patcher, patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ):
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=MLX_VARIANT
            )
        assert result["endpoint"] == f"http://127.0.0.1:{DEFAULT_PORT}"
        assert result["runtime_location"]["backend"] == "mlx"
        assert result["runtime_location"]["port"] == DEFAULT_PORT
        # Names the interpreter that received mlx-lm rather than claiming an
        # importability we cannot measure for a TAOS_MLX_PYTHON override.
        assert result["mlx_python"] == sys.executable

    async def test_download_failure_is_passed_through(self, monkeypatch, tmp_path):
        _fake_apple(monkeypatch)
        with patch.object(
            MLXInstaller, "_ensure_mlx_lm", AsyncMock(return_value=(True, ""))
        ), patch("tinyagentos.installers.mlx_installer.HFMultiInstaller") as hf:
            hf.return_value.install = AsyncMock(
                return_value={"success": False, "error": "download failed for repo"}
            )
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=MLX_VARIANT
            )
        assert result["success"] is False
        assert "download failed" in result["error"]


@pytest.mark.asyncio
class TestMLXInstallerRuntime:
    async def test_pip_installs_mlx_lm_when_missing(self, monkeypatch):
        installer = MLXInstaller(pip_python=sys.executable)
        run_cmd = AsyncMock(return_value=(0, "Successfully installed mlx-lm"))
        with patch("tinyagentos.installers.mlx_installer.mlx_lm_installed", lambda: False), \
                patch("tinyagentos.installers.mlx_installer.run_cmd", run_cmd):
            ok, err = await installer._ensure_mlx_lm()
        assert ok is True and err == ""
        assert run_cmd.await_args_list[0].args[0] == [
            sys.executable, "-m", "pip", "install", "mlx-lm"
        ]

    async def test_pip_success_is_verified_by_importing_the_runtime(self):
        """pip exit 0 is not proof the package is importable — the check runs in
        the interpreter that will serve the model."""
        installer = MLXInstaller(pip_python=sys.executable)
        run_cmd = AsyncMock(return_value=(0, ""))
        with patch("tinyagentos.installers.mlx_installer.mlx_lm_installed", lambda: False), \
                patch("tinyagentos.installers.mlx_installer.run_cmd", run_cmd):
            ok, err = await installer._ensure_mlx_lm()
        assert ok is True and err == ""
        assert run_cmd.await_args_list[1].args[0] == [sys.executable, "-c", "import mlx_lm"]

    async def test_unimportable_after_pip_is_a_failure(self):
        installer = MLXInstaller(pip_python=sys.executable)
        run_cmd = AsyncMock(side_effect=[(0, "Successfully installed mlx-lm"), (1, "ModuleNotFoundError")])
        with patch("tinyagentos.installers.mlx_installer.mlx_lm_installed", lambda: False), \
                patch("tinyagentos.installers.mlx_installer.run_cmd", run_cmd):
            ok, err = await installer._ensure_mlx_lm()
        assert ok is False
        assert "not importable" in err
        assert "ModuleNotFoundError" in err

    async def test_pip_is_skipped_when_runtime_present(self):
        installer = MLXInstaller(pip_python=sys.executable)
        run_cmd = AsyncMock(return_value=(0, ""))
        with patch("tinyagentos.installers.mlx_installer.mlx_lm_installed", lambda: True), \
                patch("tinyagentos.installers.mlx_installer.run_cmd", run_cmd):
            ok, err = await installer._ensure_mlx_lm()
        assert ok is True and err == ""
        run_cmd.assert_not_called()

    async def test_pip_failure_surfaces_the_output(self):
        installer = MLXInstaller(pip_python=sys.executable)
        run_cmd = AsyncMock(return_value=(1, "ERROR: no matching distribution"))
        with patch("tinyagentos.installers.mlx_installer.mlx_lm_installed", lambda: False), \
                patch("tinyagentos.installers.mlx_installer.run_cmd", run_cmd):
            ok, err = await installer._ensure_mlx_lm()
        assert ok is False
        assert "mlx-lm" in err
        assert "no matching distribution" in err

    async def test_install_stops_when_the_runtime_cannot_be_installed(self, monkeypatch, tmp_path):
        _fake_apple(monkeypatch)
        with patch.object(
            MLXInstaller, "_ensure_mlx_lm",
            AsyncMock(return_value=(False, "pip install mlx-lm failed")),
        ), patch("tinyagentos.installers.mlx_installer.HFMultiInstaller") as hf:
            result = await MLXInstaller(models_dir=tmp_path).install(
                "qwen2.5-3b", install_config={"backend": "mlx"}, variant=MLX_VARIANT
            )
        assert result["success"] is False
        assert "mlx-lm" in result["error"]
        hf.assert_not_called()

    async def test_port_honours_env_override(self, monkeypatch):
        monkeypatch.setenv("TAOS_MLX_PORT", "7899")
        assert MLXInstaller().port == 7899


@pytest.mark.asyncio
class TestMLXInstallerUninstall:
    async def test_removes_only_this_manifests_mlx_directory(self, tmp_path):
        target = tmp_path / "mlx" / "qwen2.5" / "qwen2.5-3b"
        target.mkdir(parents=True)
        (target / "config.json").write_text("{}")
        other = tmp_path / "llama-cpp" / "qwen2.5" / "qwen2.5-3b"
        other.mkdir(parents=True)
        (other / "qwen.gguf").write_text("weights")

        result = await MLXInstaller(models_dir=tmp_path).uninstall("qwen2.5-3b")

        assert result["success"] is True
        assert not target.exists()
        assert (other / "qwen.gguf").exists(), "other backends' copies are untouched"

    async def test_missing_directory_is_not_an_error(self, tmp_path):
        result = await MLXInstaller(models_dir=tmp_path).uninstall("qwen2.5-3b")
        assert result["success"] is True
        assert result["deleted"] == 0

    async def test_refuses_an_app_id_that_escapes_the_mlx_root(self, monkeypatch, tmp_path):
        """Both the download and the recursive delete must fail closed on a
        traversal app_id."""
        _fake_apple(monkeypatch)
        outside = tmp_path / "keep-me"
        outside.mkdir(parents=True)
        (outside / "important.txt").write_text("do not delete")

        installer = MLXInstaller(models_dir=tmp_path)
        ensure_runtime = AsyncMock(return_value=(True, ""))
        with patch.object(MLXInstaller, "_ensure_mlx_lm", ensure_runtime), patch(
            "tinyagentos.installers.mlx_installer.HFMultiInstaller"
        ) as hf:
            install_result = await installer.install(
                "../keep-me", install_config={"backend": "mlx"}, variant=MLX_VARIANT
            )
        assert install_result["success"] is False
        assert "refusing to install" in install_result["error"]
        # Rejected before the runtime step: an escaping id must not even reach
        # the pip install.
        ensure_runtime.assert_not_awaited()
        hf.assert_not_called()

        uninstall_result = await installer.uninstall("../keep-me")
        assert uninstall_result["success"] is False
        assert "refusing to remove" in uninstall_result["error"]
        assert (outside / "important.txt").exists()
