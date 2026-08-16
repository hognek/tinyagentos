#!/usr/bin/env python3
"""CI check: fail a PR whose new tests ALL SKIP (green that asserts nothing).

Scans test files the PR adds/modifies and fails if every test in a file
is skipped (via pytest.importorskip or pytest.skip).  An escape hatch
trailer in the PR body waives the check.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def find_changed_test_files(base_ref: str) -> list[str]:
    """Return test files (test_*.py) changed between base_ref and HEAD."""
    # git diff --name-only <base>..HEAD
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"::error::git diff failed: {result.stderr}")
        sys.exit(1)

    all_changed = result.stdout.strip().splitlines()
    test_files = [f for f in all_changed if os.path.basename(f).startswith("test_") and f.endswith(".py")]
    return test_files


def get_test_outcomes(test_files: list[str]) -> dict[str, dict]:
    """Run pytest -rs on each test file and return skip/pass/fail counts.

    Returns: {filename: {"total": int, "skipped": int, "passed": int, "failed": int,
                       "skip_reasons": [str], "import_guards": [str]}}
    """
    results: dict[str, dict] = {}

    for filepath in test_files:
        # Run pytest on just this file with -rs (short summary + result)
        # Also use --tb=no to truncate tracebacks, -q for quiet
        cmd = [
            "uv", "run", "--no-sync",
            "pytest", filepath, "-rs", "--tb=no", "-q",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        # Parse stdout for summary lines like "4 passed, 2 skipped, 1 failed"
        # and individual test outcomes like "test_name SKIPPED"
        output = proc.stdout + proc.stderr

        total = 0
        skipped = 0
        passed = 0
        failed = 0
        skip_reasons: list[str] = []
        import_guards: list[str] = []

        # Count from summary line: "X passed, Y skipped, Z failed"
        m = re.search(r"(\d+)\s+passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+skipped", output)
        if m:
            skipped = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", output)
        if m:
            failed = int(m.group(1))
        total = passed + skipped + failed

        # Also count from individual test outcome lines: "test_name SKIPPED"
        # Pattern: word characters, dash, underscore, followed by SKIPPED/FAILED/PASSED
        outcome_lines = re.findall(
            r"^([\w\.-]+)\s+(SKIPPED|FAILED|PASSED)\s*$",
            output,
            re.MULTILINE,
        )
        # Always parse guards from the test file, independent of outcome line matching
        file_guards = _parse_guards_from_file(filepath)
        import_guards.extend(file_guards)

        for _name, outcome in outcome_lines:
            total += 1
            if outcome == "SKIPPED":
                skipped += 1
            elif outcome == "FAILED":
                failed += 1
            elif outcome == "PASSED":
                passed += 1

        # If we couldn't parse total from summary, use outcome lines
        if total == 0:
            total = len(outcome_lines)
            skipped = sum(1 for _o, o in outcome_lines if o == "SKIPPED")
            passed = sum(1 for _o, o in outcome_lines if o == "PASSED")
            failed = sum(1 for _o, o in outcome_lines if o == "FAILED")

        results[filepath] = {
            "total": total,
            "skipped": skipped,
            "passed": passed,
            "failed": failed,
            "skip_reasons": skip_reasons,
            "import_guards": import_guards,
        }

    return results


def _parse_guards_from_file(filepath: str) -> list[str]:
    """Parse a test file to find importorskip targets and pytest.skip reasons.

    Returns list of guard strings like 'importorskip: module_name' or 'skip: reason'.
    """
    guards: list[str] = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return guards

    for match in re.finditer(r"importorskip\(['\"]([^'\"]+)['\"]\)", content):
        guards.append(f"importorskip:{match.group(1)}")

    for match in re.finditer(r"pytest\.skip\(['\"]([^'\"]*)['\"]\)", content):
        reason = match.group(1).strip()
        guards.append(f"skip:{reason}")

    # Also catch multi-line pytest.skip with string after
    # e.g., pytest.skip("reason")
    for match in re.finditer(r"pytest\.skip\([^)]*\)", content):
        # Already handled above if simple string; skip complex cases
        pass

    return guards


def get_pr_body() -> str:
    """Return the PR body from GitHub context."""
    # GITHUB_EVENT_PATH is set in the GitHub Actions environment
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        # Fallback: try to read from local file for testing
        event_path = "/tmp/github_event.json"
        if os.path.exists(event_path):
            with open(event_path, "r") as f:
                event = json.load(f)
                return event.get("pull_request", {}).get("body", "")

    try:
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
        return event.get("pull_request", {}).get("body", "")
    except Exception:
        return ""


def has_escape_hatch(pr_body: str, filepath: str) -> bool:
    """Check if the PR body has a Tests-Skipped-Intentionally trailer for this file.

    Expected format: Tests-Skipped-Intentionally: <file>, <why>
    The file path must match (basename match is sufficient).
    """
    # Look for the trailer pattern at the end of the PR body or on its own line
    # Pattern: "Tests-Skipped-Intentionally: <file>, <why>"
    basename = os.path.basename(filepath)

    # Search for the trailer in the PR body
    lines = pr_body.splitlines()
    # Check last few lines for the trailer
    for line in lines:
        stripped = line.strip()
        m = re.match(r"Tests-Skipped-Intentionally:\s*(.+)", stripped)
        if m:
            trailer_claim = m.group(1).strip()
            # The trailer claims a file and why; if it mentions this file's basename, waive it
            if basename in trailer_claim:
                return True
    return False


def main() -> int:
    base_ref = os.environ.get("BASE_REF", "")
    if not base_ref:
        # Try to detect from git
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        head_ref = result.stdout.strip()
        # For PRs, the base is typically the branch name from the event
        # Try common patterns
        result2 = subprocess.run(
            ["git", "log", "--format=%D", "-1"],
            capture_output=True, text=True,
        )
        print(f"HEAD: {head_ref}, REMOTE: {result2.stdout}")
        # Default to origin/dev if we can't determine
        base_ref = "origin/dev"

    print(f"Using base reference: {base_ref}")

    # Find changed test files
    test_files = find_changed_test_files(base_ref)
    print(f"Changed test files: {test_files}")

    if not test_files:
        print("No test files changed — nothing to check.")
        return 0

    # Get test outcomes
    results = get_test_outcomes(test_files)

    # Get PR body for escape hatch
    pr_body = get_pr_body()
    print(f"PR body length: {len(pr_body)} chars")

    any_fail = False

    for filepath, info in results.items():
        skip_count = info["skipped"]
        total = info["total"]
        guards = info["import_guards"]

        if total == 0:
            print(f"WARNING: {filepath} has 0 test outcomes, skipping check")
            continue

        if skip_count == total:
            # All tests skip — check for escape hatch
            if has_escape_hatch(pr_body, filepath):
                print(
                    f"WAIVED: {filepath} — all {skip_count} tests skip, "
                    f"escape hatch present in PR body. Guards: {guards}"
                )
            else:
                print(
                    f"FAIL: {filepath} — all {skip_count} of {total} tests skip "
                    f"(guards: {', '.join(guards) or 'none detected'}). "
                    f"This PR would manufacture coverage with no real tests."
                )
                any_fail = True
        else:
            # Only some skip — v1 scope: we only fail on ALL skip
            print(
                f"OK: {filepath} — {skip_count}/{total} tests skip (partial, v1 scope). "
                f"Guards: {', '.join(guards) or 'none detected'}"
            )

    # Report summary in PR check output
    total_changed = len(test_files)
    all_skip_files = sum(
        1 for info in results.values() if info["total"] > 0 and info["skipped"] == info["total"]
    )

    if any_fail:
        print(f"\n::error:: {all_skip_files} file(s) have all tests skipping — see above for details")
        return 1

    print(f"\nOK: {total_changed} test file(s) checked, no all-skip violations")
    if all_skip_files > 0:
        print(f"  ({all_skip_files} file(s) have all tests skip but waived via escape hatch)")
    return 0


if __name__ == "__main__":
    sys.exit(main())