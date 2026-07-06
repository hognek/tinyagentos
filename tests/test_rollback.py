import subprocess

import pytest

from tinyagentos.rollback import ROLLBACK_FILE, read_rollback_target, record_pre_update


def test_record_then_read_roundtrip(tmp_path):
    record_pre_update(tmp_path, branch="dev", sha="abc123def", ts=1700000000)
    target = read_rollback_target(tmp_path)
    assert target == {"branch": "dev", "sha": "abc123def", "ts": "1700000000"}


def test_record_overwrites(tmp_path):
    record_pre_update(tmp_path, branch="dev", sha="aaa", ts=1)
    record_pre_update(tmp_path, branch="feat/x", sha="bbb", ts=2)
    assert read_rollback_target(tmp_path) == {"branch": "feat/x", "sha": "bbb", "ts": "2"}


def test_read_none_when_absent(tmp_path):
    assert read_rollback_target(tmp_path) is None


def test_file_is_shell_sourceable(tmp_path):
    """scripts/rollback.sh sources this file, so bash must read the same values."""
    record_pre_update(tmp_path, branch="feat/odd-name", sha="deadbeef", ts=42)
    out = subprocess.check_output(
        ["bash", "-c", f"source '{tmp_path / ROLLBACK_FILE}' && echo \"$prev_branch|$prev_sha|$prev_ts\""],
        text=True,
    ).strip()
    assert out == "feat/odd-name|deadbeef|42"


def test_quote_injection_is_safe(tmp_path):
    # A branch name with a quote must not break the sourceable file.
    record_pre_update(tmp_path, branch="a'b", sha="c", ts=1)
    assert read_rollback_target(tmp_path)["branch"] == "a'b"
    out = subprocess.check_output(
        ["bash", "-c", f"source '{tmp_path / ROLLBACK_FILE}' && printf '%s' \"$prev_branch\""],
        text=True,
    )
    assert out == "a'b"


@pytest.mark.asyncio
async def test_update_records_rollback_target(tmp_path, monkeypatch):
    """update_to_master records the pre-update branch + sha before mutating."""
    import tinyagentos.update_runner as ur

    calls = {"n": 0}

    async def fake_run(args, cwd):
        # Simulate: fetch ok, on branch 'dev', HEAD sha, clean tree, ff-merge ok.
        joined = " ".join(args)
        if "rev-parse --abbrev-ref" in joined:
            return (0, "dev\n")
        if "rev-parse HEAD" in joined:
            return (0, "abc1234567\n")
        if "status --porcelain" in joined:
            return (0, "")  # clean
        return (0, "")

    monkeypatch.setattr(ur, "_run", fake_run)
    await ur.update_to_master(tmp_path)
    target = read_rollback_target(tmp_path)
    assert target is not None
    assert target["branch"] == "dev"
    assert target["sha"] == "abc1234567"
