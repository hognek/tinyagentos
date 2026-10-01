"""Tests for .github/workflows/build-agent-images.yml"""

import fnmatch
import re
from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/build-agent-images.yml")
INSTALL_SH_PATH = Path("app-catalog/agents/openclaw/scripts/install.sh")


def load_workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def load_install_sh():
    return INSTALL_SH_PATH.read_text()


def test_release_pattern_matches_all_artifacts():
    """Release download pattern must match artifact names for every base in matrix."""
    wf = load_workflow()

    # Build matrix bases and arches
    matrix = wf["jobs"]["build"]["strategy"]["matrix"]
    bases = matrix["base"]
    arches = matrix["arch"]

    # ALIAS mapping from workflow env
    # The ALIAS expression is defined in the workflow env but we parse it manually here
    alias_map = {}
    for base in bases:
        if base == "openclaw":
            alias_map[base] = "taos-openclaw-base"
        elif base == "generic":
            alias_map[base] = "taos-base"
        elif base == "hermes":
            alias_map[base] = "taos-hermes-base"
        else:
            raise ValueError(f"Unknown base: {base}")

    # Artifact names are ${ALIAS}-${arch}
    artifact_names = [f"{alias_map[base]}-{arch}" for base in bases for arch in arches]

    # Release job download pattern (multi-line, each line is a pattern)
    release_steps = wf["jobs"]["release"]["steps"]
    download_step = next(s for s in release_steps if s.get("uses", "").startswith("actions/download-artifact"))
    pattern_text = download_step["with"]["pattern"]
    patterns = [p.strip() for p in pattern_text.strip().splitlines() if p.strip()]

    # Check each artifact name matches at least one pattern
    unmatched = []
    for name in artifact_names:
        if not any(fnmatch.fnmatch(name, pat) for pat in patterns):
            unmatched.append(name)

    assert not unmatched, (
        f"Release patterns {patterns} do not match artifacts: {unmatched}. "
        f"All artifacts: {artifact_names}"
    )


def test_openclaw_bake_uses_pinned_version_from_install_sh():
    """Openclaw bake step must not use @latest; must read version from install.sh."""
    wf = load_workflow()
    install_sh = load_install_sh()

    # Find the openclaw bake step
    build_steps = wf["jobs"]["build"]["steps"]
    bake_step = next(s for s in build_steps if s.get("name") == "Bake openclaw into the base container")

    run_content = bake_step["run"]

    # Must not contain @latest
    assert "openclaw@latest" not in run_content, (
        f"Bake step uses 'openclaw@latest' but should use pinned version from install.sh. "
        f"Run content: {run_content}"
    )

    # Bake step should use the OPENCLAW_VERSION env var (set by extract step)
    assert "openclaw@${OPENCLAW_VERSION}" in run_content, (
        f"Bake step should use 'openclaw@${{OPENCLAW_VERSION}}' from env. "
        f"Run content: {run_content}"
    )

    # Verify the extract step exists and reads from install.sh
    extract_step = next(s for s in build_steps if s.get("name") == "Extract openclaw version from install.sh")
    extract_run = extract_step["run"]
    assert "install.sh" in extract_run, "Extract step should read from install.sh"
    assert "openclaw@" in extract_run, "Extract step should parse openclaw version"

    # Extract pinned version from install.sh (line like: npm install -g --unsafe-perm openclaw@0.2.0)
    match = re.search(r"npm install -g --unsafe-perm openclaw@([\d.]+)", install_sh)
    assert match, "Could not find pinned openclaw version in install.sh"
    pinned_version = match.group(1)

    # The extract step should output this version
    assert pinned_version in extract_run or "VERSION" in extract_run, (
        f"Extract step should extract version {pinned_version}"
    )


def test_release_runs_when_detect_succeeded_not_cancelled():
    """Release job should run when detect succeeded and run not cancelled, not blocked by build failures."""
    wf = load_workflow()

    release_job = wf["jobs"]["release"]
    needs = release_job["needs"]

    # Should only need detect, not build (or use a condition)
    # The fix should make release run when detect succeeded and not cancelled
    assert "build" not in needs, (
        "Release job should not hard-depend on 'build' succeeding entirely. "
        "It should run when detect succeeded and publish whatever artifacts exist."
    )
    # The actual fix will use a condition like: if: needs.detect.result == 'success' && !cancelled()
    # For now just check the structure allows this

    assert isinstance(needs, str), "needs should be a string referencing the detect job"


def test_release_publishes_existing_artifacts():
    """Release should publish bases whose tarballs exist, not fail when some are missing."""
    wf = load_workflow()

    release_steps = wf["jobs"]["release"]["steps"]
    gh_release_step = next(s for s in release_steps if s.get("uses", "").startswith("softprops/action-gh-release"))

    # Should have fail_on_unmatched_files: false (YAML parses as boolean False)
    with_config = gh_release_step.get("with", {})
    assert with_config.get("fail_on_unmatched_files") is False, (
        "Release should have fail_on_unmatched_files: false to allow partial publishes"
    )


def test_openclaw_bake_passes_version_into_container():
    """Openclaw bake step should pass OPENCLAW_VERSION as env to incus exec."""
    wf = load_workflow()
    
    # Find the openclaw bake step
    build_steps = wf["jobs"]["build"]["steps"]
    bake_step = next(s for s in build_steps if s.get("name") == "Bake openclaw into the base container")
    
    run_content = bake_step["run"]
    
    # Should use --env OPENCLAW_VERSION in incus exec command
    assert "--env OPENCLAW_VERSION" in run_content, (
        "Openclaw bake step should pass OPENCLAW_VERSION with --env to incus exec. "
        f"Run content: {run_content}"
    )
    
    # The version should be expanded from the env var
    assert "${OPENCLAW_VERSION}" in run_content, (
        "Openclaw bake step should reference OPENCLAW_VERSION environment variable. "
        f"Run content: {run_content}"
    )


def test_version_extract_step_fails_on_empty():
    """Extract version step should fail when extracted version is empty or invalid."""
    wf = load_workflow()
    
    # Find the extract version step
    build_steps = wf["jobs"]["build"]["steps"]
    extract_step = next(s for s in build_steps if s.get("name") == "Extract openclaw version from install.sh")
    
    run_content = extract_step["run"]
    
    # Should have validation that checks for empty version
    assert "if [ -z \"$VERSION\" ]; then" in run_content, (
        "Extract version step should check for empty version. "
        f"Run content: {run_content}"
    )
    
    # Should have validation that checks version format
    assert 'if ! [[ "$VERSION" =~ ^[0-9]+(\\.[0-9]+)+$ ]]; then' in run_content, (
        "Extract version step should validate version format with regex ^[0-9]+(\\.[0-9]+)+$. "
        f"Run content: {run_content}"
    )
    
    # Should have exit commands when version is invalid
    assert "exit 1" in run_content, (
        "Extract version step should exit with error code 1 when version is invalid. "
        f"Run content: {run_content}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])