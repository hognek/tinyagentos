"""Regression tests for the 2026-08-21 account-store wipe.

An unclean power-off left ``data/.auth_user.json`` as 901 NUL bytes with its
size and mtime intact.  ``_read_users`` swallowed the parse error, returned
an empty store, and every onboarding gate concluded this was a fresh install
— so the box served the create-your-account form to anyone who asked, and
submitting it would have overwritten the real accounts.

Two independent defects, tested separately:
  * the read path must not turn "corrupt" into "fresh install"
  * the write path must not be able to produce a half-written file
"""
from __future__ import annotations

import json
import os
import stat

import pytest

from tinyagentos.atomic_io import atomic_write_text
from tinyagentos.auth import AuthManager, AuthStoreCorruptError


def _store(tmp_path):
    return AuthManager(tmp_path), tmp_path / ".auth_user.json"


def _real_users_file(mgr, users_file):
    mgr.setup_user("jay", "Jay", "jay@example.com", "correct horse battery")
    return json.loads(users_file.read_text())


class TestCorruptStoreFailsClosed:
    def test_nul_filled_store_is_not_reported_as_unconfigured(self, tmp_path):
        """The exact on-disk shape the Pi came back with: right size, all NULs."""
        mgr, users_file = _store(tmp_path)
        original = _real_users_file(mgr, users_file)
        size = len(json.dumps(original, indent=2))
        users_file.write_bytes(b"\0" * size)

        assert users_file.stat().st_size == size
        assert mgr.is_configured() is True
        assert mgr.needs_onboarding() is False

    def test_missing_store_still_onboards(self, tmp_path):
        """The other half: a genuinely fresh install must still be offered setup."""
        mgr, users_file = _store(tmp_path)
        assert not users_file.exists()
        assert mgr.is_configured() is False
        assert mgr.needs_onboarding() is True

    @pytest.mark.parametrize(
        "payload",
        [b"\0" * 901, b"", b"{ truncated", b'["not", "an", "object"]'],
        ids=["nul-filled", "empty", "truncated-json", "wrong-toplevel-type"],
    )
    def test_read_raises_rather_than_returning_empty(self, tmp_path, payload):
        mgr, users_file = _store(tmp_path)
        _real_users_file(mgr, users_file)
        users_file.write_bytes(payload)
        with pytest.raises(AuthStoreCorruptError):
            mgr._read_users()

    def test_setup_refuses_to_overwrite_a_corrupt_store(self, tmp_path):
        """The damaging half: claiming the box must not clobber the accounts."""
        mgr, users_file = _store(tmp_path)
        _real_users_file(mgr, users_file)
        corrupt = b"\0" * 901
        users_file.write_bytes(corrupt)

        with pytest.raises(AuthStoreCorruptError):
            mgr.setup_user("attacker", "A", "a@example.com", "hunter2hunter2")
        # Still exactly as we left it — recoverable from a backup.
        assert users_file.read_bytes() == corrupt

    def test_multi_user_hint_degrades_instead_of_raising(self, tmp_path):
        mgr, users_file = _store(tmp_path)
        _real_users_file(mgr, users_file)
        users_file.write_bytes(b"\0" * 901)
        assert mgr.is_multi_user() is False


class TestAtomicWrite:
    def test_replaces_content_and_leaves_no_temp_files(self, tmp_path):
        target = tmp_path / "state.json"
        atomic_write_text(target, '{"v": 1}')
        atomic_write_text(target, '{"v": 2}')
        assert target.read_text() == '{"v": 2}'
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_applies_requested_mode_before_the_rename(self, tmp_path):
        target = tmp_path / "secret"
        atomic_write_text(target, "token", mode=0o600)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_preserves_existing_mode_when_none_requested(self, tmp_path):
        target = tmp_path / "secret"
        atomic_write_text(target, "one", mode=0o600)
        atomic_write_text(target, "two")
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_failed_write_leaves_the_original_intact(self, tmp_path, monkeypatch):
        target = tmp_path / "state.json"
        atomic_write_text(target, "original")

        def boom(fd, data):
            raise OSError("ENOSPC")

        monkeypatch.setattr(os, "write", boom)
        with pytest.raises(OSError):
            atomic_write_text(target, "replacement")

        assert target.read_text() == "original"
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


class TestAuthWritesGoThroughAtomicIo:
    def test_users_file_is_written_atomically_and_0600(self, tmp_path, monkeypatch):
        calls = []
        import tinyagentos.auth as auth_mod

        real = auth_mod.atomic_write_text

        def spy(path, text, **kw):
            calls.append((os.path.basename(str(path)), kw.get("mode")))
            return real(path, text, **kw)

        monkeypatch.setattr(auth_mod, "atomic_write_text", spy)
        mgr, users_file = _store(tmp_path)
        mgr.setup_user("jay", "Jay", "jay@example.com", "correct horse battery")

        assert (".auth_user.json", 0o600) in calls
        assert stat.S_IMODE(users_file.stat().st_mode) == 0o600

    def test_sessions_file_is_written_atomically_and_0600(self, tmp_path):
        mgr, _ = _store(tmp_path)
        mgr.setup_user("jay", "Jay", "jay@example.com", "correct horse battery")
        mgr.create_session(user_id="u1")
        sessions = tmp_path / ".auth_sessions"
        assert sessions.exists()
        assert stat.S_IMODE(sessions.stat().st_mode) == 0o600
        assert not list(tmp_path.glob(".*.tmp*"))
