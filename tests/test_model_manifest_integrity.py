"""Sweep test for model-catalog manifest integrity.

Ensures every variant in app-catalog/models/*/manifest.yaml satisfies the
resolver schema contract: non-empty backends with known targets, a 64-char
lowercase hex sha256, a non-empty https download_url, and a positive size_mb.

A per-manifest allowlist tracks pre-existing sha256 debt until the catalog
is filled in.  The intent is zero entries.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import yaml

# Known target enums -- the resolver only accepts values produced by
# hardware_to_targets in tinyagentos/cluster/capabilities.py.
KNOWN_TARGETS = {
    "apple-silicon",
    "x86-cuda",
    "x86-vulkan",
    "arm-vulkan",
    "rockchip",
    "cpu",
}

# Pre-existing debt: every model manifest ships without sha256 (None or
# empty string).  IDs listed here are exempt from the sha256 rule until
# the upstream catalog is filled in.  The intent is zero entries.
_SHA256_ALLOWLIST: set[str] = {
    "4x-ultrasharp",
    "auraflow-v0.3",
    "bge-large-en-v1.5",
    "bge-m3",
    "bge-reranker-v2-m3",
    "bge-small-en-v1.5",
    "birefnet",
    "codeformer",
    "command-r-35b",
    "controlnet-canny",
    "controlnet-depth",
    "controlnet-openpose",
    "controlnet-openpose-sdxl",
    "deepseek-coder-v2-lite",
    "deepseek-r1-14b",
    "dreamshaper-8-lcm",
    "florence-2-base",
    "flux-dev-gguf",
    "flux-schnell-gguf",
    "flux-schnell-unsloth",
    "gemma-2-2b",
    "gemma-2-9b",
    "gemma-3-12b",
    "gemma-3-1b",
    "gemma-3-4b",
    "gemma-4-e2b-gguf",
    "gemma-4-e2b-uncensored-gguf",
    "gemma-4-e4b-gguf",
    "gemma-4-e4b-uncensored-gguf",
    "gfpgan-v1.4",
    "granite-3.1-2b",
    "granite-3.1-8b",
    "jina-embeddings-v3",
    "kokoro-tts",
    "kolors",
    "lcm-dreamshaper-v7",
    "llama-3-70b",
    "llama-3.1-8b",
    "llama-3.2-1b",
    "llama-3.2-3b",
    "llama-3.3-70b",
    "llava-1.6-mistral-7b",
    "llava-phi-3-mini",
    "ltx-video",
    "minicpm-v-2.6",
    "ministral-3b",
    "mistral-7b-v0.3",
    "mistral-nemo-12b",
    "mixtral-8x7b",
    "moondream2",
    "mxbai-embed-large",
    "nemotron-mini-4b",
    "nomic-embed-text-v1.5",
    "paligemma-2",
    "parakeet-tdt-0.6b",
    "pelochus-qwen-1.8b-rkllm",
    "phi-3.5-mini",
    "phi-4",
    "phi-4-mini",
    "piper-en-lessac",
    "pixart-sigma-512",
    "playground-v2.5",
    "qwen2-vl-7b",
    "qwen2.5-vl-7b",
    "qwen2.5-0.5b",
    "qwen2.5-1.5b",
    "qwen2.5-1.5b-rkllm",
    "qwen2.5-14b",
    "qwen2.5-14b-rkllm",
    "qwen2.5-32b",
    "qwen2.5-3b",
    "qwen2.5-3b-rkllm",
    "qwen2.5-72b",
    "qwen2.5-7b",
    "qwen2.5-7b-rkllm",
    "qwen2.5-coder-1.5b-rkllm",
    "qwen2.5-coder-14b",
    "qwen2.5-coder-14b-rkllm",
    "qwen2.5-coder-7b",
    "qwen2.5-coder-7b-rkllm",
    "qwen2.5-math-1.5b-rkllm",
    "qwen2.5-math-7b-rkllm",
    "qwen3-1.7b",
    "qwen3-1.7b-rkllm",
    "qwen3-14b",
    "qwen3-30b-a3b",
    "qwen3-32b",
    "qwen3-4b",
    "qwen3-4b-rkllm",
    "qwen3-8b",
    "qwen3-embedding-0.6b",
    "qwen3-reranker-0.6b",
    "qwen3-vl-2b-rkllm",
    "qwen3-vl-4b-rkllm",
    "real-esrgan-x4",
    "rmbg-1.4",
    "sd-v1.5-lcm",
    "sd3.5-large-turbo-gguf",
    "sdxl-lightning",
    "sdxl-turbo",
    "sdxs-512",
    "smollm2",
    "smollm2-135m",
    "smollm2-360m",
    "smolvlm",
    "snowflake-arctic-embed-m",
    "snowflake-arctic-embed-s",
    "stable-cascade",
    "tinyllama-1.1b",
    "whisper-base",
    "whisper-large-v3",
    "whisper-large-v3-turbo",
    "whisper-medium",
    "whisper-small",
    "whisper-tiny",
}


def test_model_manifests_are_resolvable_and_integrity_pinned():
    root = Path(__file__).resolve().parent.parent / "app-catalog"
    errors: list[str] = []
    for path in sorted(glob.glob(str(root / "models" / "*" / "manifest.yaml"))):
        with open(path) as f:
            manifest = yaml.safe_load(f)
        mid = manifest.get("id") or Path(path).parent.name
        allowed_sha256 = mid in _SHA256_ALLOWLIST
        for variant in manifest.get("variants") or []:
            vid = variant.get("id", "<missing>")
            # Rule 1: requires.backends non-empty; every entry has non-empty
            # targets whose values are drawn from the known enum set.
            backends = ((variant.get("requires") or {}).get("backends")) or []
            if not backends:
                errors.append(f"{mid}/{vid}: requires.backends is empty")
                continue
            for backend in backends:
                targets = backend.get("targets") or []
                if not targets:
                    errors.append(
                        f"{mid}/{vid}: backend {backend.get('id')!r} has empty targets"
                    )
                else:
                    unknown = [t for t in targets if t not in KNOWN_TARGETS]
                    if unknown:
                        errors.append(
                            f"{mid}/{vid}: backend {backend.get('id')!r} has unknown targets {unknown}"
                        )
            # Rule 2: sha256 is a 64-char lowercase hex string.
            sha256 = variant.get("sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
                if not allowed_sha256:
                    errors.append(
                        f"{mid}/{vid}: sha256 must be a 64-char lowercase hex string (got {sha256!r})"
                    )
            # Rule 3: download_url is non-empty and parses as https.
            url = variant.get("download_url", "")
            if not url or not url.startswith("https://"):
                errors.append(
                    f"{mid}/{vid}: download_url must be a non-empty https URL (got {url!r})"
                )
            # Rule 4: size_mb is a positive int.
            size_mb = variant.get("size_mb")
            if not isinstance(size_mb, int) or size_mb <= 0:
                errors.append(
                    f"{mid}/{vid}: size_mb must be a positive int (got {size_mb!r})"
                )
    assert errors == [], (
        "model manifest integrity failures:\n" + "\n".join(errors)
    )
