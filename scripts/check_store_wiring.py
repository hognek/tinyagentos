#!/usr/bin/env python3
"""BaseStore wiring guard.

Detects PRs that add a new BaseStore subclass but never wire it into
tinyagentos/app.py. Routes reach stores ONLY via request.app.state, so a
store that is never assigned to app.state is unreachable.

Algorithm:
  1. Scan the PR diff for Python files under tinyagentos/.
  2. For each newly added file, find classes that subclass BaseStore
     (directly or transitively).
  3. For each modified file, find classes whose ``class Foo(BaseStore)``
     definition line appears in the added diff lines.
  4. For each newly-added store class, check that its class name appears
     somewhere in tinyagentos/app.py (name-level check).
  5. A "Store-Unwired-Intentionally: <ClassName>, <why>" trailer in the PR
     body waives a named class and logs it.

Usage:
    python scripts/check_store_wiring.py
    python scripts/check_store_wiring.py --base origin/dev
    python scripts/check_store_wiring.py --base origin/dev --pr-body "..."
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAILER = "Store-Unwired-Intentionally:"


@dataclass
class Violation:
    class_name: str
    file_path: str


def _run_git(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return result.stdout


def _parse_name_status(output: str) -> list[tuple[str, str]]:
    changed: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        changed.append((status[0], path))
    return changed


def _git_changed(base_ref: str, repo_root: Path) -> list[tuple[str, str]]:
    out = _run_git(["diff", "--name-status", f"{base_ref}...HEAD"], repo_root)
    return _parse_name_status(out)


def _get_file_at_ref(file_path: str, ref: str, repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _class_def_in_added_lines(
    file_path: str, class_name: str, base_ref: str, repo_root: Path,
) -> bool:
    """Return True if the class definition is newly added in the PR."""
    base_content = _get_file_at_ref(file_path, base_ref, repo_root)
    if base_content is not None:
        try:
            base_tree = ast.parse(base_content)
            for node in ast.walk(base_tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return False
        except SyntaxError:
            pass

    diff = _run_git(["diff", f"{base_ref}...HEAD", "--", file_path], repo_root)
    pattern = re.compile(rf"^\+.*class\s+{re.escape(class_name)}\s*\(", re.MULTILINE)
    return bool(pattern.search(diff))


def build_class_hierarchy(repo_root: Path) -> dict[str, set[str]]:
    """Build a map of class_name -> set of direct base class names."""
    classes: dict[str, set[str]] = {}
    tinyagentos_dir = repo_root / "tinyagentos"
    if not tinyagentos_dir.is_dir():
        return classes
    for py_file in sorted(tinyagentos_dir.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = set()
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.add(base.id)
                classes[node.name] = bases
    return classes


def _inherits_base_store(
    class_name: str,
    classes: dict[str, set[str]],
    visited: set[str] | None = None,
) -> bool:
    if visited is None:
        visited = set()
    if class_name == "BaseStore":
        return True
    if class_name in visited:
        return False
    visited.add(class_name)
    for base in classes.get(class_name, set()):
        if _inherits_base_store(base, classes, visited):
            return True
    return False


def find_base_store_subclasses_in_file(
    source: str, all_classes: dict[str, set[str]],
) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    classes_in_file: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes_in_file.add(node.name)

    return {
        name for name in classes_in_file
        if _inherits_base_store(name, all_classes)
    }


def parse_waived_classes(pr_body: str | None) -> set[str]:
    """Parse Store-Unwired-Intentionally trailer from PR body text.

    Expected format: ``Store-Unwired-Intentionally: <ClassName>, <why>``
    Only the first comma-delimited token is treated as the class name; the
    remainder is the human-readable reason.
    """
    waived: set[str] = set()
    if not pr_body:
        return waived
    for line in pr_body.splitlines():
        line = line.strip()
        if line.startswith(TRAILER):
            classes_str = line[len(TRAILER):].strip()
            cls = classes_str.split(",", 1)[0].strip()
            if cls:
                waived.add(cls)
    return waived


def check_store_wiring(
    base_ref: str,
    repo_root: Path = REPO_ROOT,
    pr_body: str | None = None,
) -> tuple[list[Violation], set[str]]:
    changed = _git_changed(base_ref, repo_root)

    app_py_path = repo_root / "tinyagentos" / "app.py"
    app_py_content = ""
    if app_py_path.exists():
        app_py_content = app_py_path.read_text(encoding="utf-8", errors="ignore")

    all_classes = build_class_hierarchy(repo_root)

    violations: list[Violation] = []
    waived: set[str] = set()
    waived.update(parse_waived_classes(pr_body))

    for status, file_path in changed:
        if not file_path.startswith("tinyagentos/") or not file_path.endswith(".py"):
            continue
        if status.startswith("D"):
            continue
        if not (status.startswith("A") or status.startswith("M")):
            continue

        abs_path = repo_root / file_path
        if not abs_path.exists():
            continue

        source = abs_path.read_text(encoding="utf-8", errors="ignore")
        store_classes = find_base_store_subclasses_in_file(source, all_classes)
        if not store_classes:
            continue

        for class_name in sorted(store_classes):
            is_new = False
            if status.startswith("A"):
                is_new = True
            elif status.startswith("M"):
                is_new = _class_def_in_added_lines(
                    file_path, class_name, base_ref, repo_root,
                )

            if not is_new:
                continue

            if class_name in waived:
                waived.add(class_name)
                continue

            if not re.search(rf"\b{re.escape(class_name)}\b", app_py_content):
                violations.append(Violation(
                    class_name=class_name,
                    file_path=file_path,
                ))

    return violations, waived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="Target branch ref (e.g. origin/dev)")
    parser.add_argument("--pr-body", default=None, help="PR body text (for Store-Unwired-Intentionally trailer)")
    args = parser.parse_args(argv)

    base_ref = args.base
    if base_ref is None:
        base_ref = os.environ.get("BASE_REF", "origin/dev")

    pr_body = args.pr_body
    if pr_body is None:
        pr_body = os.environ.get("PR_BODY")

    violations, waived_classes = check_store_wiring(base_ref, REPO_ROOT, pr_body)

    if waived_classes:
        for cls in sorted(waived_classes):
            print(f"store-wiring-guard: waived via Store-Unwired-Intentionally: {cls}")

    if violations:
        print(
            f"STORE-WIRING FAIL: {len(violations)} new BaseStore subclass(es) are not wired "
            f"into tinyagentos/app.py. Routes reach stores ONLY via request.app.state, "
            f"so an unwired store is unreachable:"
        )
        for v in violations:
            print(f"  - {v.class_name} in {v.file_path}")
        return 1

    print("store-wiring-guard: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
