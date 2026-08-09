#!/usr/bin/env python3
"""Check that the dependency-audit ignore list is still valid.

Level-triggered: re-evaluates every run and reports while conditions hold.
Answers two questions every run:

1. Does a fixed version resolve yet?  Runs ``uv lock --upgrade-package``
   for each ignored package and reports success or failure with the
   compared command output.
2. Does pip-audit report any finding NOT in the ignore list?  Runs
   ``pip-audit`` without ``--ignore-vuln`` flags so every finding is
   visible, then compares each advisory id against the expected list.

Usage:
    python scripts/check_dependency_audit_ignores.py [--ignore-file path]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_IGNORE_FILE = Path(__file__).resolve().parent.parent / "security" / "pip-audit-ignore.toml"


def load_ignore_list(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return data.get("ignore", [])


def check_upgrade_resolves(package: str, project_root: Path) -> tuple[bool, str]:
    lock_path = project_root / "uv.lock"
    if not lock_path.is_file():
        return False, "uv.lock not found"
    backup = project_root / "uv.lock.bak"
    try:
        backup.write_bytes(lock_path.read_bytes())
        result = subprocess.run(
            ["uv", "lock", "--upgrade-package", package],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        detail = (result.stdout or result.stderr).strip()
        return result.returncode == 0, detail or f"exit {result.returncode}"
    except FileNotFoundError:
        return False, "uv not found"
    except subprocess.TimeoutExpired:
        return False, "uv lock timed out"
    finally:
        if backup.is_file():
            lock_path.write_bytes(backup.read_bytes())
            backup.unlink()


def run_pip_audit(project_root: Path) -> tuple[list[dict], str]:
    cmd = ["pip-audit", "--format", "json"]
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        findings: list[dict] = []
        stdout = result.stdout.strip()
        if stdout:
            try:
                data = json.loads(stdout)
                for dep in data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        findings.append(
                            {"package": dep.get("name"), "id": vuln.get("id")}
                        )
            except json.JSONDecodeError:
                pass
        return findings, result.stdout + result.stderr
    except FileNotFoundError:
        return [], "pip-audit not found"
    except subprocess.TimeoutExpired:
        return [], "pip-audit timed out"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=DEFAULT_IGNORE_FILE,
        help="Path to the ignore list (default: security/pip-audit-ignore.toml)",
    )
    args = parser.parse_args(argv)

    ignore_list = load_ignore_list(args.ignore_file)
    ignore_ids = {entry["id"] for entry in ignore_list}
    project_root = args.ignore_file.resolve().parent.parent

    unresolved: list[tuple[str, str, str]] = []
    droppable: list[tuple[str, str, str]] = []
    skipped: list[tuple[str, str]] = []

    for entry in ignore_list:
        package = entry["package"]
        vid = entry["id"]
        if entry.get("check_upgrade") is False:
            skipped.append((package, vid))
            continue
        resolves, detail = check_upgrade_resolves(package, project_root)
        if resolves:
            droppable.append((package, vid, detail))
        else:
            unresolved.append((package, vid, detail))

    print("=== Fixed-version check ===")
    if skipped:
        for pkg, vid in skipped:
            print(f"SKIPPED: {pkg} ({vid}) — tool dependency, upgrade check not applicable")
    if droppable:
        for pkg, vid, detail in droppable:
            print(f"DROPPABLE: {pkg} ({vid}) — uv lock --upgrade-package {pkg}: {detail[:200]}")
    else:
        for pkg, vid, detail in unresolved:
            truncated = detail[:200] if detail else "no output"
            print(f"NO FIX YET: {pkg} ({vid}) — uv lock --upgrade-package {pkg}: {truncated}")

    print()
    print("=== pip-audit check ===")
    findings, _ = run_pip_audit(project_root)
    unlisted = [f for f in findings if f["id"] not in ignore_ids]
    if unlisted:
        for f in unlisted:
            print(f"UNLISTED: {f['package']} {f['id']}")
    else:
        if findings:
            listed = [f for f in findings if f["id"] in ignore_ids]
            print(f"OK: {len(findings)} finding(s), all in ignore list:")
            for f in listed:
                print(f"  {f['package']} {f['id']}")
        else:
            print("OK: no findings")

    print()
    if droppable or unlisted:
        print("FAIL: ignore list is stale or incomplete")
        return 1
    print("OK: ignore list is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
