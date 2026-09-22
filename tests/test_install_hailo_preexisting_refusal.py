"""Gate: install-hailo.sh must REFUSE (exit 3, not 0) when it finds a
pre-existing hailo-ollama already serving the upstream :8000 port.

Background (taOS #2083): ``detect_preexisting_hailoollama()`` ends in ``exit 0``
when it detects a pre-existing instance. Both auto-install callers
(install-server.sh / install-worker.sh) chain into install-hailo.sh with
``|| warn``, which only fires on a non-zero exit — so the whole chained install
reports silent success while leaving the box with no taOS backend on :7836 and
the user's own instance untouched on :8000. The fix is a distinct exit 3 that
the callers key off to tell the operator why nothing was installed.

The gate extracts ``detect_preexisting_hailoollama()`` verbatim from the real
install-hailo.sh (so a regression in the production function fails this gate),
points ``curl`` at a stub, and asserts the function exits 3 on a "models"
payload and 0 on an empty /api/tags response.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "install-hailo.sh"


def _extract_detect_function() -> str:
    """Return the body of detect_preexisting_hailoollama() from install-hailo.sh,
    from the opening line through the matching closing brace. Deliberately work
    on the real script so a regression in the production function fails this
    gate."""
    text = SCRIPT.read_text()
    m = re.search(r"^detect_preexisting_hailoollama\(\)\s*\{", text, re.MULTILINE)
    assert m, "detect_preexisting_hailoollama() not found in install-hailo.sh"
    start = m.start()
    depth = 0
    i = m.end() - 1  # at the '{'
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise AssertionError(
        "could not find matching closing brace of detect_preexisting_hailoollama()"
    )


def _write_wrapper(tmp_path: Path, curl_body: str, function_body: str) -> Path:
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        "log()  { printf '[hailo] %s\\n' \"$*\"; }\n"
        "warn() { printf '[hailo] %s\\n' \"$*\" >&2; }\n"
        "die()  { printf '[hailo] %s\\n' \"$*\" >&2; exit 1; }\n"
        f"curl() {{\n{curl_body}\n}}\n"
        "HAILO_OLLAMA_PORT=\"7836\"\n"
        + function_body
        + "\ndetect_preexisting_hailoollama\n"
    )
    wrapper.chmod(0o755)
    return wrapper


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_refuses_exit_3_when_preexisting_instance_serves(tmp_path: Path) -> None:
    """A pre-existing hailo-ollama answering /api/tags with a 'models' payload
    must make the function exit 3 (REFUSAL), not 0. exit 0 is the #2083 bug:
    the chained installer walks away reporting success."""
    function_body = _extract_detect_function()
    payload = '{"models":[{"name":"qwen2-vl-2b:latest"}]}'
    curl_body = f"    printf '%s' '{payload}\\n'\n    return 0\n"
    wrapper = _write_wrapper(tmp_path, curl_body, function_body)

    result = subprocess.run(
        ["/usr/bin/env", "bash", str(wrapper)],
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 3, (
        "detect_preexisting_hailoollama must exit 3 when a pre-existing "
        "hailo-ollama answers /api/tags; exit 0 is the #2083 silent-success "
        "regression.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "pre-existing" in combined, (
        f"refusal output does not mention a pre-existing instance; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_returns_clean_when_no_preexisting_instance(tmp_path: Path) -> None:
    """Sanity: an empty /api/tags response (nothing pre-existing) must NOT
    trigger the refusal — the function returns and the installer proceeds
    with exit 0."""
    function_body = _extract_detect_function()
    curl_body = "    return 0\n"
    wrapper = _write_wrapper(tmp_path, curl_body, function_body)

    result = subprocess.run(
        ["/usr/bin/env", "bash", str(wrapper)],
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, (
        "detect_preexisting_hailoollama must return cleanly (0) when nothing "
        "is pre-existing; it should not refuse on an empty /api/tags.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )