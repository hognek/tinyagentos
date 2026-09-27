"""MLX installer — Apple Silicon models via the `mlx-lm` runtime (taOS #329).

MLX is Apple's array framework for Apple Silicon and `mlx-lm` is the LLM
runtime on top of it. It is what the taOS `mlx` backend adapter talks to
(``backend_adapters.py`` maps ``mlx`` to the OpenAI-compatible adapter, and
``mlx_lm.server`` speaks exactly that API).

Unlike the CUDA/ROCm backends there is no daemon to install and no
``active.gguf`` symlink to flip: `mlx_lm.load` / `mlx_lm.server` take either
an MLX HuggingFace repo id or a local model directory. So this installer:

1. Verifies the host is Apple Silicon. MLX exists only on ``darwin``/``arm64``;
   everywhere else we fail with a clear message instead of letting the generic
   download fallback drop a file the runtime can never load.
2. Makes sure the `mlx-lm` runtime is importable, running
   ``pip install mlx-lm`` in the serving interpreter when it is not.
3. Downloads the model into the shared layout at
   ``~/models/mlx/<family>/<manifest_id>/`` by delegating to
   ``HFMultiInstaller`` (a repo of safetensors + config + tokenizer) or
   ``DownloadInstaller`` (a single file), so MLX weights sit next to every
   other backend's copies and the Models app can size/clean them uniformly.

Manifest variant fields:

    mlx_repo: mlx-community/Qwen2.5-3B-Instruct-4bit   # preferred
    hf_repo:  ...                                      # accepted fallback
    download_url: ...                                  # single-file fallback

``mlx_repo`` wins over ``hf_repo`` so one variant can point MLX at a
pre-quantised ``mlx-community`` repo while keeping its GGUF ``hf_repo`` for
the other backends. A variant with neither ``mlx_repo``/``hf_repo`` nor
``download_url`` is rejected rather than silently "succeeding" with nothing.

Configuration via env vars:

- ``TAOS_MLX_PYTHON`` — interpreter that gets `mlx-lm` (default:
  ``sys.executable``, the taOS service interpreter, which is the one that
  will serve the model).
- ``TAOS_MLX_PORT`` — port the OpenAI-compatible MLX server is expected on
  (default ``7837``; reserved in ``port_allocator.RESERVED_PORTS``).
- ``TAOS_MODELS_ROOT`` — shared model tree root (honoured by
  ``model_paths.models_root()``).
"""
from __future__ import annotations

import importlib.util
import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from tinyagentos.installers.base import AppInstaller, run_cmd
from tinyagentos.installers.download_installer import DownloadInstaller
from tinyagentos.installers.hf_multi_installer import HFMultiInstaller
from tinyagentos.installers.model_paths import (
    family_from_manifest,
    models_root,
)

logger = logging.getLogger(__name__)

BACKEND_ID = "mlx"

# Scheduler resource name for the Apple Silicon GPU. Apple Silicon has exactly
# one GPU (unified memory), so the name is unindexed — matching the resource
# table in docs/design/resource-scheduler.md — while CUDA/ROCm hosts keep
# gpu-cuda-N. Defined here because Metal availability and the resource name are
# the same fact; the controller's discovery, the worker's advertised inventory
# and the A2A lease default all import it so the three cannot drift apart.
METAL_RESOURCE_NAME = "gpu-metal"

# Package providing the runtime; `mlx` itself arrives as its dependency.
# The pip name (mlx-lm) differs from the import name (mlx_lm) — the post-install
# check imports the module.
MLX_LM_PACKAGE = "mlx-lm"
_MLX_LM_MODULE = "mlx_lm"

# taOS default port for the MLX OpenAI-compatible server (mlx_lm.server).
# Reserved next to 7833 (rkllama), 7834 (LiteLLM), 7835 (llama.cpp) and 7836
# (hailo-ollama) in installers/port_allocator.RESERVED_PORTS so a Store app
# host-port can never squat it.
DEFAULT_PORT = 7837


def _default_port() -> int:
    """Resolve the MLX server port from TAOS_MLX_PORT or DEFAULT_PORT."""
    raw = os.environ.get("TAOS_MLX_PORT", str(DEFAULT_PORT))
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "TAOS_MLX_PORT=%r is not an integer; using default %d",
            raw,
            DEFAULT_PORT,
        )
        return DEFAULT_PORT


def is_apple_silicon() -> bool:
    """True on Darwin/arm64 — the only hardware MLX runs on.

    The machine check matters as much as the OS check: an x86_64 Python under
    Rosetta reports ``darwin``/``x86_64`` and cannot load MLX at all, so it is
    the honest gate rather than "is this macOS".
    """
    return sys.platform == "darwin" and platform.machine() == "arm64"


def metal_available() -> bool:
    """True when this host has a Metal GPU taOS can schedule onto.

    Metal is present on every Apple Silicon machine (M1-M5). Intel Macs also
    report Metal, but without unified memory there is no GPU worth registering,
    so taOS treats them as CPU-only — consistent with
    ``scheduler/discovery.py``, which registers this host's GPU as the
    ``gpu-metal`` resource (docs/design/resource-scheduler.md).
    """
    return is_apple_silicon()


def mlx_lm_installed() -> bool:
    """True when the `mlx-lm` runtime is importable in this interpreter."""
    return importlib.util.find_spec("mlx_lm") is not None


class MLXInstaller(AppInstaller):
    """Install MLX models for serving via `mlx-lm` on Apple Silicon."""

    def __init__(
        self,
        *,
        pip_python: str | None = None,
        models_dir: Path | str | None = None,
        port: int | None = None,
        pip_timeout: int = 1800,
    ):
        # Interpreter that receives `mlx-lm`. Defaults to the interpreter taOS
        # itself runs under — that is the one that will exec mlx_lm.server.
        self.pip_python = pip_python or os.environ.get("TAOS_MLX_PYTHON") or sys.executable
        # Tests pass a tmp root; production leaves it None so model_paths'
        # models_root() (TAOS_MODELS_ROOT) decides.
        self._models_dir = Path(models_dir) if models_dir else None
        self.port = port if port is not None else _default_port()
        self.pip_timeout = pip_timeout

    def _root(self) -> Path:
        return self._models_dir if self._models_dir is not None else models_root()

    def _target_dir(self, app_id: str) -> Path:
        """Install dir for *app_id* in the shared ``<root>/mlx/<family>/<id>`` layout."""
        return self._root() / BACKEND_ID / family_from_manifest(app_id) / app_id

    def _contained(self, target: Path) -> Path | None:
        """Resolved *target* when it stays inside the MLX backend root, else None.

        ``app_id`` arrives from a catalog manifest, but a model download writes
        through this path and uninstall deletes it recursively, so it is
        validated at the boundary rather than trusted.
        """
        backend_root = (self._root() / BACKEND_ID).resolve()
        resolved = target.resolve()
        return resolved if resolved.is_relative_to(backend_root) else None

    async def _ensure_mlx_lm(self) -> tuple[bool, str]:
        """Make `mlx-lm` importable by the serving interpreter.

        Returns ``(ok, error)``. A user-supplied ``TAOS_MLX_PYTHON`` is not
        introspectable from this process, so it always gets an (idempotent)
        ``pip install``; the default interpreter is only touched when the
        runtime is genuinely missing, so re-installing a model never upgrades
        the runtime under a running server.
        """
        if self.pip_python == sys.executable and mlx_lm_installed():
            return True, ""
        code, output = await run_cmd(
            [self.pip_python, "-m", "pip", "install", MLX_LM_PACKAGE],
            timeout=self.pip_timeout,
        )
        if code != 0:
            return False, (
                f"pip install {MLX_LM_PACKAGE} failed (exit {code}): "
                f"{output.strip()[-500:]}"
            )
        # pip's exit code is not proof the runtime is usable (a broken wheel, a
        # stale egg-link, an externally-managed-environment shim that "succeeds"
        # without installing). Verify in the interpreter that will serve, which
        # is also the only way to check a TAOS_MLX_PYTHON override.
        check_code, check_out = await run_cmd(
            [self.pip_python, "-c", f"import {_MLX_LM_MODULE}"],
            timeout=60,
        )
        if check_code != 0:
            return False, (
                f"{MLX_LM_PACKAGE} installed but not importable by "
                f"{self.pip_python}: {check_out.strip()[-300:]}"
            )
        return True, ""

    async def install(
        self,
        app_id: str,
        install_config: dict,
        variant: dict | None = None,
        **kwargs: Any,
    ) -> dict:
        if not variant:
            return {"success": False, "error": "MLX install requires a variant"}

        if not is_apple_silicon():
            return {
                "success": False,
                "error": (
                    "MLX requires Apple Silicon (macOS on arm64); this host is "
                    f"{sys.platform}/{platform.machine()}. Install a variant for a "
                    "backend this machine has (llama-cpp, ollama, ...)."
                ),
            }

        # First non-blank of mlx_repo / hf_repo wins. Stripping before the
        # choice matters: a whitespace-only mlx_repo is truthy, and treating it
        # as "set" would discard a perfectly good hf_repo and then reject the
        # install.
        repo = ""
        for key in ("mlx_repo", "hf_repo"):
            candidate = str(variant.get(key) or "").strip()
            if candidate:
                repo = candidate
                break
        if not repo and not variant.get("download_url"):
            return {
                "success": False,
                "error": (
                    f"variant {variant.get('id')!r} has neither mlx_repo/hf_repo "
                    "(a HuggingFace MLX repo) nor download_url to install from"
                ),
            }

        # Everything this installer writes must land inside the mlx backend
        # root — the same guard uninstall applies before it deletes. Checked
        # before the runtime step so an escaping app_id cannot trigger a pip
        # install as a side effect of being rejected.
        target = self._target_dir(app_id)
        if self._contained(target) is None:
            return {
                "success": False,
                "error": f"refusing to install {app_id!r}: target {target} is outside the mlx root",
            }

        ok, err = await self._ensure_mlx_lm()
        if not ok:
            return {"success": False, "error": err}

        # The dispatcher injects "backend" into install_config; default it so a
        # direct call still writes into the shared mlx tree rather than the
        # huggingface default one.
        install_config = dict(install_config or {})
        install_config.setdefault("backend", BACKEND_ID)

        if repo:
            # MLX repos are ordinary HF directories (config.json, tokenizer,
            # *.safetensors), so reuse the multi-file downloader — overriding
            # the repo so an explicit mlx_repo wins over the variant's hf_repo.
            dl_variant = dict(variant)
            dl_variant["hf_repo"] = repo
            result = await HFMultiInstaller(_root_override=self._models_dir).install(
                app_id,
                install_config=install_config,
                variant=dl_variant,
                **kwargs,
            )
        else:
            result = await DownloadInstaller(models_dir=self._models_dir).install(
                app_id,
                install_config=install_config,
                variant=variant,
                **kwargs,
            )

        if not result.get("success"):
            return result

        # Endpoint metadata: mlx_lm.server serves the OpenAI-compatible API the
        # `mlx` backend adapter expects. Reported alongside the download result
        # so the store records where the model landed and how to reach it.
        # `mlx_python` names the interpreter that received `mlx-lm` — with a
        # TAOS_MLX_PYTHON override we cannot introspect it from here, so we
        # report it rather than claiming an importability we did not measure.
        result["mlx_repo"] = repo
        result["mlx_python"] = self.pip_python
        result["endpoint"] = f"http://127.0.0.1:{self.port}"
        result["runtime_location"] = {
            "host": "127.0.0.1",
            "port": self.port,
            "backend": BACKEND_ID,
        }
        return result

    async def uninstall(self, app_id: str, **kwargs: Any) -> dict:
        """Remove this manifest's own directory from the mlx backend root.

        Scoped to ``<root>/mlx/<family>/<manifest_id>`` — a manifest installed
        on several backends keeps its copies for the others.
        """
        backend_root = (self._root() / BACKEND_ID).resolve()
        target = self._contained(self._target_dir(app_id))
        # The recursive delete below must never escape the mlx backend root,
        # whatever the caller passes as app_id ("../..", an absolute path).
        if target is None:
            return {
                "success": False,
                "error": (
                    f"refusing to remove {self._target_dir(app_id)}: "
                    f"outside {backend_root}"
                ),
            }
        if not target.exists():
            return {"success": True, "deleted": 0, "target_dir": str(target)}
        try:
            shutil.rmtree(target)
        except OSError as exc:
            return {
                "success": False,
                "error": f"failed to remove {target}: {exc}",
                "target_dir": str(target),
            }
        return {"success": True, "deleted": 1, "target_dir": str(target)}
