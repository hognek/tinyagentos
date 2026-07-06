"""Tests for tinyagentos.worker.skald_manifest — sidecar manifest parser."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tinyagentos.worker.skald_manifest import (
    DEFAULT_MANIFEST_PATH,
    SOFTWARE_TO_BACKEND_TYPE,
    load_manifest,
)


# ---------------------------------------------------------------------------
# SOFTWARE_TO_BACKEND_TYPE mapping
# ---------------------------------------------------------------------------

class TestSoftwareToBackendType:
    def test_llamacpp_maps_to_llama_cpp(self):
        assert SOFTWARE_TO_BACKEND_TYPE["llamacpp"] == "llama-cpp"

    def test_embed_maps_to_llama_cpp(self):
        assert SOFTWARE_TO_BACKEND_TYPE["embed"] == "llama-cpp"

    def test_kokoro_maps_to_kokoro(self):
        assert SOFTWARE_TO_BACKEND_TYPE["kokoro"] == "kokoro"

    def test_whisper_maps_to_whisper(self):
        assert SOFTWARE_TO_BACKEND_TYPE["whisper"] == "whisper"

    def test_unknown_software_raises_keyerror(self):
        with pytest.raises(KeyError):
            _ = SOFTWARE_TO_BACKEND_TYPE["nonexistent-software"]


# ---------------------------------------------------------------------------
# load_manifest — happy paths
# ---------------------------------------------------------------------------

MANIFEST_FIXTURE = {
    "resource_id": "gtx1080",
    "models": [
        {
            "model_id": "qwen3.6-35b-a3b",
            "capability": "llm-chat",
            "software": "llamacpp",
            "port": 9090,
            "vram_required_gb": 7.2,
            "health_url": "http://127.0.0.1:9090/health",
        },
        {
            "model_id": "qwen3-embedding-8b",
            "capability": "embedding",
            "software": "embed",
            "port": 8081,
            "vram_required_gb": 4.5,
            "health_url": "http://127.0.0.1:8081/health",
        },
        {
            "model_id": "whisper-large-v3",
            "capability": "stt",
            "software": "whisper",
            "port": 0,
            "vram_required_gb": 1.5,
            "health_url": "",
        },
    ],
}


class TestLoadManifestHappy:
    def test_loads_valid_manifest_file(self, tmp_path: Path):
        manifest_path = tmp_path / "skald-models.json"
        manifest_path.write_text(json.dumps(MANIFEST_FIXTURE))

        result = load_manifest(str(manifest_path))
        assert result["resource_id"] == "gtx1080"
        assert len(result["models"]) == 3
        assert result["models"][0]["model_id"] == "qwen3.6-35b-a3b"

    def test_returns_model_fields(self, tmp_path: Path):
        manifest_path = tmp_path / "skald-models.json"
        manifest_path.write_text(json.dumps(MANIFEST_FIXTURE))

        result = load_manifest(str(manifest_path))
        m0 = result["models"][0]
        assert m0["capability"] == "llm-chat"
        assert m0["software"] == "llamacpp"
        assert m0["port"] == 9090
        assert m0["vram_required_gb"] == 7.2
        assert m0["health_url"] == "http://127.0.0.1:9090/health"

    def test_env_var_overrides_path(self, tmp_path: Path, monkeypatch):
        manifest_path = tmp_path / "custom-manifest.json"
        manifest_path.write_text(json.dumps(MANIFEST_FIXTURE))
        monkeypatch.setenv("TAOS_SKALD_MANIFEST", str(manifest_path))

        result = load_manifest()
        assert result["resource_id"] == "gtx1080"


# ---------------------------------------------------------------------------
# load_manifest — missing file
# ---------------------------------------------------------------------------

class TestLoadManifestAbsent:
    def test_missing_file_returns_empty_manifest(self, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist.json"
        result = load_manifest(str(nonexistent))
        assert result == {"resource_id": "", "models": []}

    def test_default_path_absent_returns_empty(self, monkeypatch):
        # Ensure env var is unset and default path doesn't exist
        monkeypatch.delenv("TAOS_SKALD_MANIFEST", raising=False)
        # Patch Path.exists to return False for the default path
        with patch.object(Path, "exists", return_value=False):
            result = load_manifest()
            assert result == {"resource_id": "", "models": []}


# ---------------------------------------------------------------------------
# load_manifest — edge cases
# ---------------------------------------------------------------------------

class TestLoadManifestEdgeCases:
    def test_empty_models_list(self, tmp_path: Path):
        manifest = {"resource_id": "gtx1080", "models": []}
        manifest_path = tmp_path / "empty.json"
        manifest_path.write_text(json.dumps(manifest))

        result = load_manifest(str(manifest_path))
        assert result["resource_id"] == "gtx1080"
        assert result["models"] == []

    def test_no_resource_id(self, tmp_path: Path):
        manifest = {"models": [{"model_id": "test"}]}
        manifest_path = tmp_path / "no-resource.json"
        manifest_path.write_text(json.dumps(manifest))

        result = load_manifest(str(manifest_path))
        # JSON parsing succeeds; missing keys aren't added
        assert "resource_id" not in result  # it won't be added by load_manifest
        assert len(result["models"]) == 1

    def test_invalid_json_raises(self, tmp_path: Path):
        manifest_path = tmp_path / "bad.json"
        manifest_path.write_text("not valid json {{{")

        with pytest.raises(json.JSONDecodeError):
            load_manifest(str(manifest_path))

    def test_none_path_falls_back_to_env(self, tmp_path: Path, monkeypatch):
        manifest_path = tmp_path / "from-env.json"
        manifest_path.write_text(json.dumps(MANIFEST_FIXTURE))
        monkeypatch.setenv("TAOS_SKALD_MANIFEST", str(manifest_path))

        result = load_manifest(None)
        assert result["resource_id"] == "gtx1080"

    def test_no_models_key_returns_empty_models(self, tmp_path: Path):
        """A valid JSON doc without a 'models' key — treated as empty."""
        manifest = {"resource_id": "bare"}
        manifest_path = tmp_path / "bare.json"
        manifest_path.write_text(json.dumps(manifest))

        result = load_manifest(str(manifest_path))
        assert result["resource_id"] == "bare"
        # load_manifest doesn't add missing keys, consumer code checks .get("models")
        assert "models" not in result
