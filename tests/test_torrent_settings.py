import json
from pathlib import Path

import pytest

from tinyagentos.torrent_settings import TorrentSettings, TorrentSettingsStore


class TestTorrentSettings:
    def test_defaults(self):
        s = TorrentSettings()
        assert s.seed_enabled is True
        assert s.upload_rate_limit_kbps == 5000
        assert s.max_active_seeds == 20

    def test_to_dict(self):
        s = TorrentSettings(seed_enabled=False, upload_rate_limit_kbps=1000, max_active_seeds=5)
        d = s.to_dict()
        assert d == {"seed_enabled": False, "upload_rate_limit_kbps": 1000, "max_active_seeds": 5}

    def test_to_dict_roundtrip(self):
        s = TorrentSettings(seed_enabled=False, upload_rate_limit_kbps=2048, max_active_seeds=3)
        d = s.to_dict()
        s2 = TorrentSettings(**d)
        assert s2.seed_enabled is False
        assert s2.upload_rate_limit_kbps == 2048
        assert s2.max_active_seeds == 3


class TestTorrentSettingsStore:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        store = TorrentSettingsStore(tmp_path / "nonexistent" / "torrent_settings.json")
        s = store.load()
        assert s == TorrentSettings()

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        store = TorrentSettingsStore(path)
        settings = TorrentSettings(seed_enabled=False, upload_rate_limit_kbps=1024, max_active_seeds=5)
        store.save(settings)
        loaded = store.load()
        assert loaded == settings

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "dir" / "torrent_settings.json"
        store = TorrentSettingsStore(path)
        store.save(TorrentSettings())
        assert path.exists()

    def test_save_writes_valid_json(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        store = TorrentSettingsStore(path)
        store.save(TorrentSettings(seed_enabled=True, upload_rate_limit_kbps=8000, max_active_seeds=50))
        raw = json.loads(path.read_text())
        assert raw == {"seed_enabled": True, "upload_rate_limit_kbps": 8000, "max_active_seeds": 50}

    def test_load_corrupt_json_returns_defaults(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text("not{{{json")
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s == TorrentSettings()

    def test_load_empty_file_returns_defaults(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text("")
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s == TorrentSettings()

    def test_load_partial_fields_uses_defaults_for_missing(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text(json.dumps({"seed_enabled": False}))
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s.seed_enabled is False
        assert s.upload_rate_limit_kbps == 5000
        assert s.max_active_seeds == 20

    def test_load_coerces_types(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text(json.dumps({
            "seed_enabled": 0,
            "upload_rate_limit_kbps": "3000",
            "max_active_seeds": "10",
        }))
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s.seed_enabled is False
        assert s.upload_rate_limit_kbps == 3000
        assert s.max_active_seeds == 10

    def test_load_extra_fields_ignored(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text(json.dumps({
            "seed_enabled": True,
            "upload_rate_limit_kbps": 5000,
            "max_active_seeds": 20,
            "extra_field": "ignored",
        }))
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s == TorrentSettings()

    def test_load_truncated_json_returns_defaults(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        path.write_text('{"seed_enabled": true, "upload_rate_limit_kbps":')
        store = TorrentSettingsStore(path)
        s = store.load()
        assert s == TorrentSettings()

    def test_multiple_saves_overwrite(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        store = TorrentSettingsStore(path)
        store.save(TorrentSettings(seed_enabled=True, upload_rate_limit_kbps=1000, max_active_seeds=1))
        store.save(TorrentSettings(seed_enabled=False, upload_rate_limit_kbps=2000, max_active_seeds=2))
        loaded = store.load()
        assert loaded.seed_enabled is False
        assert loaded.upload_rate_limit_kbps == 2000
        assert loaded.max_active_seeds == 2

    def test_path_stored_as_pathlib(self, tmp_path):
        path = tmp_path / "torrent_settings.json"
        store = TorrentSettingsStore(path)
        assert isinstance(store.path, Path)

    def test_init_accepts_string_path(self, tmp_path):
        path_str = str(tmp_path / "torrent_settings.json")
        store = TorrentSettingsStore(path_str)
        assert isinstance(store.path, Path)
        store.save(TorrentSettings())
        assert (tmp_path / "torrent_settings.json").exists()
