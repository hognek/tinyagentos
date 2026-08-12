"""Tests for the BaseStore wiring guard (scripts/check_store_wiring.py).

Each integration test builds a synthetic git repo in a temp directory,
merges a PR branch into base to produce the merge result, checks out the
merge commit, and then calls check_store_wiring() directly against the
pre-merge base tip. This proves the check goes RED (fails), GREEN (passes),
and that the Store-Unwired-Intentionally trailer waives a named class.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import check_store_wiring as csw  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "branch", "-M", "main")


def _write(repo: Path, rel_path: str, content: str) -> None:
    full = repo / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _commit(repo: Path, rel_path: str, content: str, message: str) -> None:
    _write(repo, rel_path, content)
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", message)


def _branch(repo: Path, name: str) -> None:
    _git(repo, "branch", name)


def _checkout(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-q", name)


def _get_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _setup_base_repo(repo: Path) -> str:
    _init_repo(repo)
    _commit(repo, "tinyagentos/__init__.py", "", "init: package root")
    _commit(
        repo, "tinyagentos/base_store.py",
        "class BaseStore:\n    SCHEMA = ''\n    MIGRATIONS = []\n",
        "feat: add BaseStore",
    )
    _commit(
        repo, "tinyagentos/metrics_store.py",
        "from tinyagentos.base_store import BaseStore\n\n"
        "class MetricsStore(BaseStore):\n"
        "    SCHEMA = 'CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY);'\n"
        "    MIGRATIONS = []\n",
        "feat: add MetricsStore",
    )
    _commit(
        repo, "tinyagentos/app.py",
        "from tinyagentos.base_store import BaseStore\n"
        "from tinyagentos.metrics_store import MetricsStore\n\n"
        "metrics_store = MetricsStore('/tmp/metrics.db')\n\n"
        "async def lifespan(app):\n"
        "    await metrics_store.init()\n"
        "    app.state.metrics = metrics_store\n",
        "feat: wire MetricsStore in app",
    )
    return _get_head(repo)


# ---------------------------------------------------------------------------
# Core logic unit tests (no git required)
# ---------------------------------------------------------------------------


class TestFindBaseStoreSubclasses:
    def test_direct_subclass(self):
        source = (
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class Foo(BaseStore):\n"
            "    pass\n"
        )
        all_classes = {"BaseStore": set(), "Foo": {"BaseStore"}}
        result = csw.find_base_store_subclasses_in_file(source, all_classes)
        assert result == {"Foo"}

    def test_transitive_subclass(self):
        source = (
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class Parent(BaseStore):\n"
            "    pass\n"
            "\n"
            "class Child(Parent):\n"
            "    pass\n"
        )
        all_classes = {
            "BaseStore": set(),
            "Parent": {"BaseStore"},
            "Child": {"Parent"},
        }
        result = csw.find_base_store_subclasses_in_file(source, all_classes)
        assert result == {"Parent", "Child"}

    def test_non_subclass_ignored(self):
        source = "class NotAStore:\n    pass\n"
        all_classes = {"BaseStore": set(), "NotAStore": set()}
        result = csw.find_base_store_subclasses_in_file(source, all_classes)
        assert result == set()

    def test_syntax_error_returns_empty(self):
        result = csw.find_base_store_subclasses_in_file("def (:\n", {"BaseStore": set()})
        assert result == set()


class TestParseWaivedClasses:
    def test_parses_single_class(self):
        body = "Store-Unwired-Intentionally: StrikeStore, test fixture"
        assert csw.parse_waived_classes(body) == {"StrikeStore"}

    def test_no_trailer_returns_empty(self):
        assert csw.parse_waived_classes("just a description") == set()

    def test_none_body_returns_empty(self):
        assert csw.parse_waived_classes(None) == set()

    def test_trailer_with_reason(self):
        body = "Store-Unwired-Intentionally: Foo, test-only fixture"
        assert csw.parse_waived_classes(body) == {"Foo"}

    def test_multiple_trailer_lines(self):
        body = "Store-Unwired-Intentionally: Foo\n\nStore-Unwired-Intentionally: Bar"
        assert csw.parse_waived_classes(body) == {"Foo", "Bar"}


class TestClassDefInAddedLines:
    def test_new_class_in_new_file(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        _commit(repo, "tinyagentos/app.py", "x = 1\n", "init")
        base_tip = _get_head(repo)
        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/strike_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class StrikeStore(BaseStore):\n"
            "    pass\n",
            "feat: add StrikeStore",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        assert csw._class_def_in_added_lines(
            "tinyagentos/strike_store.py", "StrikeStore", base_tip, repo,
        )

    def test_existing_class_not_flagged_as_new(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        _commit(
            repo, "tinyagentos/orphan_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class OrphanStore(BaseStore):\n"
            "    pass\n",
            "feat: add OrphanStore",
        )
        base_tip = _get_head(repo)
        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/orphan_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class OrphanStore(BaseStore):\n"
            "    pass\n"
            "\n"
            "    async def new_method(self):\n"
            "        pass\n",
            "refactor: add method to OrphanStore",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        assert not csw._class_def_in_added_lines(
            "tinyagentos/orphan_store.py", "OrphanStore", base_tip, repo,
        )


# ---------------------------------------------------------------------------
# Integration tests with synthetic git repos (merge-result model)
# ---------------------------------------------------------------------------


class TestCheckStoreWiring:
    def test_new_unwired_store_fails(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/strike_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class StrikeStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS strikes (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add StrikeStore (#2172)",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert len(violations) == 1
        v = violations[0]
        assert v.class_name == "StrikeStore"
        assert v.file_path == "tinyagentos/strike_store.py"
        assert waived == set()

    def test_new_wired_store_passes(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/wired_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class WiredStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS wired (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add WiredStore",
        )
        _commit(
            repo, "tinyagentos/app.py",
            "from tinyagentos.base_store import BaseStore\n"
            "from tinyagentos.metrics_store import MetricsStore\n"
            "from tinyagentos.wired_store import WiredStore\n\n"
            "metrics_store = MetricsStore('/tmp/metrics.db')\n"
            "wired_store = WiredStore('/tmp/wired.db')\n\n"
            "async def lifespan(app):\n"
            "    await metrics_store.init()\n"
            "    await wired_store.init()\n"
            "    app.state.metrics = metrics_store\n"
            "    app.state.wired_store = wired_store\n",
            "feat: wire WiredStore in app",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert violations == []
        assert waived == set()

    def test_existing_unwired_store_not_flagged(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        _commit(repo, "tinyagentos/__init__.py", "", "init: package root")
        _commit(
            repo, "tinyagentos/base_store.py",
            "class BaseStore:\n    SCHEMA = ''\n    MIGRATIONS = []\n",
            "feat: add BaseStore",
        )
        _commit(
            repo, "tinyagentos/orphan_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class OrphanStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS orphans (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add OrphanStore (unwired)",
        )
        _commit(
            repo, "tinyagentos/app.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "async def lifespan(app):\n"
            "    pass\n",
            "feat: minimal app",
        )
        base_tip = _get_head(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/orphan_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class OrphanStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS orphans (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n"
            "\n"
            "    async def new_method(self):\n"
            "        pass\n",
            "refactor: add method to existing OrphanStore",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert violations == []
        assert waived == set()

    def test_unwired_intentionally_trailer_waives(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/unwired_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class UnwiredStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS unwired (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add UnwiredStore (test-only)",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        pr_body = "Store-Unwired-Intentionally: UnwiredStore, used only in CLI tests"
        violations, waived = csw.check_store_wiring(base_tip, repo, pr_body=pr_body)

        assert violations == []
        assert waived == {"UnwiredStore"}

    def test_transitive_subclass_flagged(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/child_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class ParentStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS parents (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n"
            "\n"
            "class ChildStore(ParentStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS children (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add ParentStore and ChildStore",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert len(violations) == 2
        names = {v.class_name for v in violations}
        assert names == {"ParentStore", "ChildStore"}
        assert waived == set()

    def test_comment_only_mention_fails_ast(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/comment_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class CommentStore(BaseStore):\n"
            "    SCHEMA = ''\n"
            "    MIGRATIONS = []\n",
            "feat: add CommentStore",
        )
        _commit(
            repo, "tinyagentos/app.py",
            "from tinyagentos.base_store import BaseStore\n"
            "from tinyagentos.metrics_store import MetricsStore\n\n"
            "# CommentStore is not wired here\n"
            "metrics_store = MetricsStore('/tmp/metrics.db')\n\n"
            "async def lifespan(app):\n"
            "    await metrics_store.init()\n"
            "    app.state.metrics = metrics_store\n",
            "feat: mention CommentStore in comment",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert len(violations) == 1
        assert violations[0].class_name == "CommentStore"
        assert violations[0].file_path == "tinyagentos/comment_store.py"
        assert violations[0].reason == "unwired"

    def test_unwired_store_in_renamed_file_fails(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _git(repo, "mv", "tinyagentos/metrics_store.py", "tinyagentos/metrics_v2_store.py")
        _write(
            repo, "tinyagentos/metrics_v2_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class MetricsV2Store(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS metrics_v2 (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
        )
        _git(repo, "add", "tinyagentos/metrics_v2_store.py")
        _git(repo, "commit", "-m", "feat: rename and add MetricsV2Store")
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert len(violations) == 1
        assert violations[0].class_name == "MetricsV2Store"
        assert violations[0].file_path == "tinyagentos/metrics_v2_store.py"

    def test_new_class_added_to_existing_file_fails(self, tmp_path: Path):
        repo = tmp_path / "repo"
        base_tip = _setup_base_repo(repo)

        _branch(repo, "pr")
        _checkout(repo, "pr")
        _commit(
            repo, "tinyagentos/metrics_store.py",
            "from tinyagentos.base_store import BaseStore\n"
            "\n"
            "class MetricsStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n"
            "\n"
            "\n"
            "class NewStore(BaseStore):\n"
            "    SCHEMA = 'CREATE TABLE IF NOT EXISTS new_store (id INTEGER PRIMARY KEY);'\n"
            "    MIGRATIONS = []\n",
            "feat: add NewStore alongside MetricsStore",
        )
        _checkout(repo, "main")
        _git(repo, "merge", "pr", "--no-edit")

        violations, waived = csw.check_store_wiring(base_tip, repo)

        assert len(violations) == 1
        assert violations[0].class_name == "NewStore"
        assert violations[0].file_path == "tinyagentos/metrics_store.py"
