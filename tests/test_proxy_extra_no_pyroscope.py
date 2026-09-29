"""Guards against `pyroscope-io` reappearing in the `proxy` extra.

tsk-szzkro: `pyroscope-io>=0.8.16,<1.0; sys_platform != 'win32'` was removed
from `pyproject.toml`'s `proxy` extra because that version range contains
exactly one release, 0.8.16, which ships only macOS and manylinux (glibc)
wheels -- no musllinux wheel and no sdist. On any musl host (Alpine,
postmarketOS) `pip install -e ".[proxy]"` resolves to zero installable files
for that dependency and the controller install fails outright. musllinux
wheels only exist from 1.0.3, which the `<1.0` cap excluded, and nothing in
this tree imports `pyroscope` (`git grep -n pyroscope` turns up only
`pyproject.toml` and `uv.lock`), so the fix is removal, not widening the pin.

This test asserts the dependency stays out of the `proxy` extra so a future
edit cannot silently reintroduce the musl install failure.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _proxy_extra_dependencies() -> list[str]:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["optional-dependencies"]["proxy"]


def test_proxy_extra_does_not_depend_on_pyroscope_io():
    deps = _proxy_extra_dependencies()

    offending = [
        dep for dep in deps if Requirement(dep).name.lower() == "pyroscope-io"
    ]

    assert offending == [], (
        "pyroscope-io is back in the proxy extra: "
        f"{offending!r}. The only published range compatible with the old "
        "'<1.0' style cap (0.8.16) ships no musllinux wheel and no sdist, so "
        "installing the proxy extra on a musl host (Alpine, postmarketOS) "
        "fails outright. Nothing in this tree imports pyroscope -- if it is "
        "needed again, pin >=1.0.3 (first musllinux release) and re-add the "
        "import, do not restore the old range."
    )
