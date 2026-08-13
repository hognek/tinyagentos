from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "check_doc_gate",
    REPO_ROOT / "scripts" / "check_doc_gate.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
evaluate_rules = _MOD.evaluate_rules


def _base_config() -> dict:
    return {
        "gate": {"trailer": "Docs-Reviewed:"},
        "rules": [
            {
                "name": "test_route",
                "on_modify": True,
                "when_changed": ["tinyagentos/routes/themes.py"],
                "require_doc": ["CHANGELOG.md"],
                "hint": "a route module was modified",
            }
        ],
    }


class TestEvaluateRulesOnModify:
    """Five cases required by the task."""

    def test_m_only_no_doc_fails(self):
        """(a) An M-only change matching an on_modify rule with no doc edit FAILS."""
        config = _base_config()
        changed = [("M", "tinyagentos/routes/themes.py")]
        commit_messages: list[str] = []
        failures = evaluate_rules(changed, commit_messages, config)
        assert len(failures) == 1
        assert "CHANGELOG.md" in failures[0]

    def test_m_only_with_doc_passes(self):
        """(b) The same change WITH the required doc edited PASSES."""
        config = _base_config()
        changed = [
            ("M", "tinyagentos/routes/themes.py"),
            ("M", "CHANGELOG.md"),
        ]
        commit_messages: list[str] = []
        failures = evaluate_rules(changed, commit_messages, config)
        assert failures == []

    def test_m_only_with_trailer_passes(self):
        """(c) The same change with a Docs-Reviewed trailer PASSES."""
        config = _base_config()
        changed = [("M", "tinyagentos/routes/themes.py")]
        commit_messages = ["Fix themes\n\nDocs-Reviewed: reviewed the change"]
        failures = evaluate_rules(changed, commit_messages, config)
        assert failures == []

    def test_m_only_without_on_modify_passes(self):
        """(d) An M-only change matching a rule WITHOUT on_modify still passes,
        proving the default did not change."""
        config = {
            "gate": {"trailer": "Docs-Reviewed:"},
            "rules": [
                {
                    "name": "test_route_default",
                    "when_changed": ["tinyagentos/routes/themes.py"],
                    "require_doc": ["CHANGELOG.md"],
                    "hint": "a route module was modified",
                }
            ],
        }
        changed = [("M", "tinyagentos/routes/themes.py")]
        commit_messages: list[str] = []
        failures = evaluate_rules(changed, commit_messages, config)
        assert failures == []

    def test_ad_triggering_still_works(self):
        """(e) A/D triggering still works as before."""
        config = _base_config()
        # A triggers
        failures = evaluate_rules([("A", "tinyagentos/routes/themes.py")], [], config)
        assert len(failures) == 1
        # D triggers
        failures = evaluate_rules([("D", "tinyagentos/routes/themes.py")], [], config)
        assert len(failures) == 1
        # A with doc edited passes
        failures = evaluate_rules(
            [("A", "tinyagentos/routes/themes.py"), ("A", "CHANGELOG.md")],
            [],
            config,
        )
        assert failures == []


class TestEvaluateRulesEdgeCases:
    """Additional coverage for the on_modify implementation."""

    def test_test_paths_excluded_even_with_on_modify(self):
        """Test paths must stay excluded from triggering, as now.

        The rule glob deliberately MATCHES the test path, so only the
        test-path exclusion keeps it from firing -- without that exclusion
        this test goes red.
        """
        config = _base_config()
        config["rules"][0]["when_changed"] = ["tests/routes/*.py"]
        changed = [("M", "tests/routes/test_themes.py")]
        commit_messages: list[str] = []
        failures = evaluate_rules(changed, commit_messages, config)
        assert failures == []

    def test_multiple_rules_mixed_on_modify(self):
        """Only rules with on_modify=true fire on M; others do not."""
        config = {
            "gate": {"trailer": "Docs-Reviewed:"},
            "rules": [
                {
                    "name": "route_mod",
                    "on_modify": True,
                    "when_changed": ["tinyagentos/routes/themes.py"],
                    "require_doc": ["CHANGELOG.md"],
                    "hint": "route modified",
                },
                {
                    "name": "catalog_add",
                    "when_changed": ["app-catalog/**"],
                    "require_doc": ["README.md"],
                    "hint": "catalog added",
                },
            ],
        }
        changed = [
            ("M", "tinyagentos/routes/themes.py"),
            # Matches catalog_add's glob, so that rule is genuinely exercised:
            # it must NOT fire on a plain modification without on_modify.
            ("M", "app-catalog/foo/app.yml"),
        ]
        failures = evaluate_rules(changed, [], config)
        assert len(failures) == 1
        assert "route_mod" in failures[0]

    def test_on_modify_false_explicit_still_default(self):
        """Explicit on_modify = false behaves the same as omitting it."""
        config = {
            "gate": {"trailer": "Docs-Reviewed:"},
            "rules": [
                {
                    "name": "route_explicit_false",
                    "on_modify": False,
                    "when_changed": ["tinyagentos/routes/themes.py"],
                    "require_doc": ["CHANGELOG.md"],
                    "hint": "route modified",
                }
            ],
        }
        changed = [("M", "tinyagentos/routes/themes.py")]
        failures = evaluate_rules(changed, [], config)
        assert failures == []


class TestEvaluateRulesRenameCopy:
    """Rename (R) and copy (C) must trigger rules but must not satisfy require_doc."""

    def test_rename_triggers_rule_by_name(self):
        """A rename of a when_changed path must trigger the rule."""
        config = _base_config()
        changed = [("R", "tinyagentos/routes/themes.py")]
        failures = evaluate_rules(changed, [], config)
        assert len(failures) == 1
        assert "test_route" in failures[0]

    def test_copy_triggers_rule_by_name(self):
        """A copy of a when_changed path must trigger the rule."""
        config = _base_config()
        changed = [("C", "tinyagentos/routes/themes.py")]
        failures = evaluate_rules(changed, [], config)
        assert len(failures) == 1
        assert "test_route" in failures[0]

    def test_deletion_still_triggers_rule(self):
        """A deletion of a when_changed path must still trigger the rule (pinning)."""
        config = _base_config()
        changed = [("D", "tinyagentos/routes/themes.py")]
        failures = evaluate_rules(changed, [], config)
        assert len(failures) == 1
        assert "test_route" in failures[0]

    def test_rename_does_not_satisfy_require_doc(self):
        """Renaming the require_doc does NOT satisfy it (pinning).

        If the satisfaction set were widened to include R, this would pass
        silently and the assertion below would fail.
        """
        config = _base_config()
        changed = [
            ("R", "tinyagentos/routes/themes.py"),
            ("R", "CHANGELOG.md"),
        ]
        failures = evaluate_rules(changed, [], config)
        assert len(failures) == 1
        assert "test_route" in failures[0]

    def test_rename_with_doc_added_passes(self):
        """A route rename with the required doc added passes."""
        config = _base_config()
        changed = [
            ("R", "tinyagentos/routes/themes.py"),
            ("A", "CHANGELOG.md"),
        ]
        failures = evaluate_rules(changed, [], config)
        assert failures == []


class TestReferencedPathsScan:
    """Invariants layer: glob expansion, tombstones, extractor precision."""

    def _write(self, root: Path, rel: str, text: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_glob_scan_targets_are_expanded(self, tmp_path):
        """docs/runbooks/*.md style entries must scan every matching file."""
        self._write(tmp_path, "docs/runbooks/one.md", "see tinyagentos/nope.py")
        self._write(tmp_path, "docs/runbooks/two.md", "all good here")
        fails = _MOD.check_referenced_paths(
            tmp_path, ["docs/runbooks/*.md"], {}
        )
        assert len(fails) == 1 and "docs/runbooks/one.md" in fails[0]

    def test_ignore_tokens_tombstone(self, tmp_path):
        """A doc explaining a removal may name the removed file - but ONLY
        the listed tombstone is exempt, other dead paths still fail."""
        self._write(
            tmp_path, "docs/guide.md",
            "docs/STATUS.md was removed. Also see tinyagentos/gone.py",
        )
        cfg = {"invariants": {"ignore_tokens": ["docs/STATUS.md"]}}
        fails = _MOD.check_referenced_paths(tmp_path, ["docs/guide.md"], cfg)
        assert len(fails) == 1 and "tinyagentos/gone.py" in fails[0]
        # Red half: without the tombstone the STATUS.md mention fails too.
        fails = _MOD.check_referenced_paths(tmp_path, ["docs/guide.md"], {})
        assert len(fails) == 2

    def test_missing_scan_target_is_skipped(self, tmp_path):
        """A local-only (gitignored) doc absent from the tree is skipped."""
        fails = _MOD.check_referenced_paths(tmp_path, ["docs/AGENT_HANDOFF.md"], {})
        assert fails == []

    def test_extractor_strips_symbol_suffix(self):
        toks = _MOD.extract_path_tokens(
            "wire it in tinyagentos/routes/__init__.py::register_all_routers()"
        )
        assert toks == ["tinyagentos/routes/__init__.py"]

    def test_extractor_ignores_hyphen_glued_prefix(self):
        """A repo prefix embedded in a home-dir slug is not a repo path."""
        toks = _MOD.extract_path_tokens(
            "read ~/.claude/projects/-home-x-tinyagentos/memory/MEMORY.md at start"
        )
        assert toks == []
