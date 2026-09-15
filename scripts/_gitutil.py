#!/usr/bin/env python3
"""Shared git utilities for the script gate checks."""

import subprocess


def run_git(args: list[str], cwd=None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout


def diff_name_status_z(
    repo_root,
    base_ref: str | None = None,
    cached: bool = False,
) -> list[tuple[str, str]]:
    args = ["-c", "core.quotePath=false", "diff", "-z", "--name-status"]
    if cached:
        args.append("--cached")
    else:
        args.append(f"{base_ref}...HEAD")
    out = run_git(args, cwd=repo_root)
    return parse_name_status(out)


def parse_name_status(output: str) -> list[tuple[str, str]]:
    changed: list[tuple[str, str]] = []
    if "\x00" in output:
        parts = output.split("\x00")
        i = 0
        while i < len(parts):
            part = parts[i].strip()
            if not part:
                i += 1
                continue
            status = part
            i += 1
            if i >= len(parts):
                break
            path = parts[i].strip()
            i += 1
            if status[0] in ("R", "C") and i < len(parts):
                new_path = parts[i].strip()
                i += 1
                if new_path:
                    path = new_path
            changed.append((status[0], path))
    else:
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status = parts[0]
            path = parts[-1]
            changed.append((status[0], path))
    return changed
