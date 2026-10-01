"""Every extra a SHIPPED updater has requested must stay defined.

An update is run by the code already on the box, not by the code being
installed. Before #3313 the updater called ``uv sync --frozen --extra proxy``
and uv refuses an extra that pyproject does not define, so removing ``proxy``
left every existing install unable to update. An extra may be emptied but
never deleted while an updater that names it is still in the field.
"""

import os
import re
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Extras passed by updater releases that are deployed somewhere. Append only.
SHIPPED_UPDATER_EXTRAS = ("proxy", "ble")


def test_shipped_updater_extras_defined_in_pyproject():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    defined = set(data["project"]["optional-dependencies"])
    missing = [e for e in SHIPPED_UPDATER_EXTRAS if e not in defined]
    assert not missing, f"extras requested by shipped updaters are undefined: {missing}"


def test_shipped_updater_extras_in_lockfile():
    # `uv sync --frozen` reads the lock, so the lock must provide them too.
    lock = (ROOT / "uv.lock").read_text()
    m = re.search(r"^provides-extras = \[(.*?)\]", lock, re.M)
    assert m, "uv.lock has no provides-extras line"
    provided = set(re.findall(r'"([^"]+)"', m.group(1)))
    missing = [e for e in SHIPPED_UPDATER_EXTRAS if e not in provided]
    assert not missing, f"uv.lock does not provide extras shipped updaters request: {missing}"


def test_proxy_extra_stays_empty():
    # Kept only for old updaters; it must not bring LiteLLM back.
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["optional-dependencies"]["proxy"] == []


# --- Rule (a): NEVER-DELETE ---


def _git_merge_base():
    try:
        out = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/dev"],
            capture_output=True, text=True, check=True, cwd=ROOT,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def _git_show(ref: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:pyproject.toml"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    ).stdout


def _git_show_lock(ref: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:uv.lock"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    ).stdout


def test_no_extra_deleted_from_pyproject():
    merge_base = _git_merge_base()
    assert merge_base is not None, "no merge base with origin/dev"
    base_text = _git_show(merge_base)
    head_text = (ROOT / "pyproject.toml").read_text()
    base_data = tomllib.loads(base_text)
    head_data = tomllib.loads(head_text)
    base_extras = set(base_data["project"]["optional-dependencies"])
    head_extras = set(head_data["project"]["optional-dependencies"])
    deleted = sorted(base_extras - head_extras)
    assert not deleted, (
        "extras deleted from pyproject.toml: {}. "
        "Empty an extra (name = []) instead of deleting it."
    ).format(deleted)


def test_no_extra_deleted_from_lockfile():
    merge_base = _git_merge_base()
    assert merge_base is not None, "no merge base with origin/dev"
    base_text = _git_show_lock(merge_base)
    head_text = (ROOT / "uv.lock").read_text()
    base_m = re.search(r"^provides-extras = \[(.*?)\]", base_text, re.M)
    head_m = re.search(r"^provides-extras = \[(.*?)\]", head_text, re.M)
    assert base_m, "base uv.lock has no provides-extras line"
    assert head_m, "HEAD uv.lock has no provides-extras line"
    base_provided = set(re.findall(r'"([^"]+)"', base_m.group(1)))
    head_provided = set(re.findall(r'"([^"]+)"', head_m.group(1)))
    deleted = sorted(base_provided - head_provided)
    assert not deleted, (
        "extras removed from uv.lock provides-extras: {}. "
        "Empty the extra in pyproject.toml (name = []) instead."
    ).format(deleted)


# --- Rule (b): SELF-MAINTAINING LIST ---


def _pyproject_extras() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return set(data["project"]["optional-dependencies"])


def _uvlock_provides_extras() -> set[str]:
    lock = (ROOT / "uv.lock").read_text()
    m = re.search(r"^provides-extras = \[(.*?)\]", lock, re.M)
    assert m, "uv.lock has no provides-extras line"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


@pytest.mark.parametrize(
    ("device_class", "taos_extras_ble", "expected"),
    [
        ("mobile", None, ("ble",)),
        ("mobile", "1", ("ble",)),
        ("mobile", "0", ()),
        ("mobile", "true", ("ble",)),
        ("mobile", "false", ()),
        (None, None, ()),
        (None, "1", ("ble",)),
        (None, "0", ()),
        (None, "true", ("ble",)),
        (None, "false", ()),
    ],
)
def test_compute_update_extras_all_branches(device_class, taos_extras_ble, expected):
    from tinyagentos.routes.settings import _compute_update_extras

    env = {}
    if taos_extras_ble is not None:
        env["TAOS_EXTRAS_BLE"] = taos_extras_ble
    with patch("tinyagentos.routes.settings._detect_device_class", return_value=device_class):
        with patch.dict(os.environ, env, clear=True):
            result = _compute_update_extras()
    assert result == expected
    pyproject_extras = _pyproject_extras()
    lock_extras = _uvlock_provides_extras()
    for extra in result:
        assert extra in SHIPPED_UPDATER_EXTRAS, (
            f"extra {extra!r} returned by _compute_update_extras is not in SHIPPED_UPDATER_EXTRAS"
        )
        assert extra in pyproject_extras, (
            f"extra {extra!r} returned by _compute_update_extras is not defined in pyproject.toml"
        )
        assert extra in lock_extras, (
            f"extra {extra!r} returned by _compute_update_extras is not in uv.lock provides-extras"
        )
