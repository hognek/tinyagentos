"""Unit tests for scripts/check_doc_gate.py.

These call evaluate_rules() and check_referenced_paths() directly with
synthetic inputs -- no shelling out to git, no dependence on the state of
this checkout's actual history.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; make it importable the same way the other
# scripts/*.py unit tests do (see tests/test_kv_quant_validator.py).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import check_doc_gate as dg  # noqa: E402 -- path manipulation must precede


APPS_RULE_CONFIG = {
    "gate": {"trailer": "Docs-Reviewed:"},
    "rules": [
        {
            "name": "apps",
            "when_changed": ["desktop/src/apps/*/**"],
            "require_doc": ["README.md"],
            "hint": "a desktop app was added or removed",
        },
        {
            "name": "routes",
            "when_changed": ["tinyagentos/routes/*.py"],
            "require_doc": ["docs/agent-coordination.md", "docs/AGENT_HANDOFF.md"],
            "hint": "an API route module was added or removed",
        },
    ],
}


class TestEvaluateRules:
    def test_no_changes_passes(self):
        assert dg.evaluate_rules([], [], APPS_RULE_CONFIG) == []

    def test_added_app_file_no_doc_no_trailer_fails(self):
        changed = [("A", "desktop/src/apps/Foo/Foo.tsx")]
        failures = dg.evaluate_rules(changed, [], APPS_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("apps -- ")

    def test_added_app_file_with_readme_edit_passes(self):
        changed = [
            ("A", "desktop/src/apps/Foo/Foo.tsx"),
            ("M", "README.md"),
        ]
        assert dg.evaluate_rules(changed, [], APPS_RULE_CONFIG) == []

    def test_added_app_file_with_trailer_passes(self):
        changed = [("A", "desktop/src/apps/Foo/Foo.tsx")]
        messages = ["feat: add Foo app\n\nDocs-Reviewed: reworded the apps table\n"]
        assert dg.evaluate_rules(changed, messages, APPS_RULE_CONFIG) == []

    def test_trailer_with_no_text_after_it_does_not_satisfy(self):
        changed = [("A", "desktop/src/apps/Foo/Foo.tsx")]
        messages = ["feat: add Foo app\n\nDocs-Reviewed:\n"]
        failures = dg.evaluate_rules(changed, messages, APPS_RULE_CONFIG)
        assert len(failures) == 1

    def test_plain_modification_does_not_trigger(self):
        """Editing an existing route file (status M) must not fire the
        'routes' rule -- only structural add/delete counts, to keep the gate
        precise."""
        changed = [("M", "tinyagentos/routes/agents.py")]
        assert dg.evaluate_rules(changed, [], APPS_RULE_CONFIG) == []

    def test_added_test_file_does_not_trigger_structural_rule(self):
        """Adding a co-located test under an app dir is not a structural app
        change and must not fire the 'apps' rule (#171). Same for a new Python
        test module vs the 'routes' rule."""
        changed = [
            ("A", "desktop/src/apps/__tests__/SettingsApp.test.tsx"),
            ("A", "desktop/src/apps/Foo/Foo.test.tsx"),
            ("A", "tests/test_new_route.py"),
        ]
        assert dg.evaluate_rules(changed, [], APPS_RULE_CONFIG) == []

    def test_deleted_route_file_triggers_routes_rule(self):
        changed = [("D", "tinyagentos/routes/old_routes.py")]
        failures = dg.evaluate_rules(changed, [], APPS_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("routes -- ")

    def test_unrelated_rule_is_unaffected_by_other_rule_satisfaction(self):
        """Two rules fire in the same changeset; satisfying only one (via a
        doc edit that doesn't match the other rule's require_doc) still
        leaves the other rule failing."""
        changed = [
            ("A", "desktop/src/apps/Foo/Foo.tsx"),
            ("A", "tinyagentos/routes/new_routes.py"),
            ("M", "README.md"),
        ]
        failures = dg.evaluate_rules(changed, [], APPS_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("routes -- ")


class TestGlobMatch:
    def test_single_star_stays_within_segment(self):
        assert dg._glob_match("tinyagentos/routes/settings.py", "tinyagentos/routes/*.py")
        assert not dg._glob_match(
            "tinyagentos/routes/desktop_browser/__init__.py",
            "tinyagentos/routes/*.py",
        )

    def test_double_star_crosses_segments(self):
        assert dg._glob_match(
            "desktop/src/apps/Foo/sub/x.ts", "desktop/src/apps/*/**"
        )

    def test_trailing_star_matches_within_segment(self):
        assert dg._glob_match("scripts/install-server.sh", "scripts/install*")

    def test_double_star_matches_nested_manifest(self):
        assert dg._glob_match("app-catalog/foo/bar.json", "app-catalog/**")


class TestEvaluateRulesRoutesGlobPrecision:
    def test_nested_route_file_does_not_trigger_routes_rule(self):
        changed = [("A", "tinyagentos/routes/desktop_browser/newmod.py")]
        assert dg.evaluate_rules(changed, [], APPS_RULE_CONFIG) == []

    def test_top_level_route_file_triggers_routes_rule(self):
        changed = [("A", "tinyagentos/routes/newroute.py")]
        failures = dg.evaluate_rules(changed, [], APPS_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("routes -- ")


class TestGetTrailer:
    def test_returns_configured_trailer(self):
        config = {"gate": {"trailer": "Docs-Reviewed:"}}
        assert dg.get_trailer(config) == "Docs-Reviewed:"

    def test_falls_back_to_default_when_missing(self):
        assert dg.get_trailer({}) == dg.DEFAULT_TRAILER


class TestCheckReferencedPaths:
    def test_dead_path_token_fails(self, tmp_path: Path):
        readme = tmp_path / "README.md"
        readme.write_text("See `scripts/nope.sh` for details.\n")
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert len(failures) == 1
        assert "scripts/nope.sh" in failures[0]

    def test_only_real_paths_passes(self, tmp_path: Path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "real.sh").write_text("#!/bin/sh\n")
        readme = tmp_path / "README.md"
        readme.write_text("See `scripts/real.sh` for details.\n")
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []

    def test_missing_scan_target_is_skipped_not_failed(self, tmp_path: Path):
        """A configured scan target that doesn't exist on disk (e.g. a
        local-only, gitignored doc absent from a fresh checkout) must not
        itself be treated as a failure."""
        failures = dg.check_referenced_paths(tmp_path, ["docs/AGENT_HANDOFF.md"], {})
        assert failures == []

    def test_glob_and_placeholder_tokens_are_ignored(self, tmp_path: Path):
        readme = tmp_path / "README.md"
        readme.write_text(
            "Wildcard install scripts live under `scripts/install*`.\n"
            "Per-framework bridges: `tinyagentos/scripts/install_<framework>.sh`.\n"
        )
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []

    def test_file_line_citation_is_ignored(self, tmp_path: Path):
        """A file:line citation like `scripts/foo.sh:123` must not be treated as
        a nonexistent path; the line-number suffix is stripped before the
        existence check."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "foo.sh").write_text("#!/bin/sh\n")
        readme = tmp_path / "README.md"
        readme.write_text("See `scripts/foo.sh:123` for details.\n")
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []

    @pytest.mark.parametrize(
        "prose",
        [
            "See scripts/foo.sh:123. That is the place.",   # sentence-ending stop
            "In scripts/foo.sh:123, the loop starts.",       # list/apposition comma
            "grep hit at scripts/foo.sh:12:34 today",        # file:line:col
            "the range (scripts/foo.sh:12-20) covers it",    # paren-closed range
            "multi scripts/foo.sh:1,5-9 selection",          # comma range list
        ],
    )
    def test_citation_shapes_with_punctuation_are_ignored(self, tmp_path: Path, prose):
        """The four shapes that false-positived when the suffix strip ran
        BEFORE the trailing-punct loop (lead block on #2307): the punct
        defeats an end-anchored regex. Each proved red on the pre-reorder
        commit."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "foo.sh").write_text("#!/bin/sh\n")
        (tmp_path / "README.md").write_text(prose + "\n")
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []

    def test_colon_in_real_filename_is_preserved(self, tmp_path: Path):
        """A path legitimately containing a colon is NOT truncated - only
        numeric line-citation suffixes are stripped."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "weird:name.md").write_text("x\n")
        (tmp_path / "README.md").write_text("See docs/weird:name.md here.\n")
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []

    def test_markdown_link_url_not_consumed_as_path(self, tmp_path: Path):
        """A markdown link whose URL points to another repo must not have the
        URL consumed as part of the path token."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "agent-manual.md").write_text("# Agent Manual\n")
        readme = tmp_path / "README.md"
        readme.write_text(
            "See [docs/agent-manual.md]"
            "(https://github.com/other/repo/blob/main/docs/agent-manual.md).\n"
        )
        failures = dg.check_referenced_paths(tmp_path, ["README.md"], {})
        assert failures == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


def test_glob_double_star_matches_bare_parent():
    """A trailing `/**` matches the bare parent path as well as anything under
    it (folds a Kilo review note that `**` was one-or-more, not zero-or-more)."""
    from check_doc_gate import _glob_match

    assert _glob_match("app-catalog", "app-catalog/**") is True
    assert _glob_match("app-catalog/foo/bar.json", "app-catalog/**") is True
    # A single `*` still does not cross a separator.
    assert _glob_match("tinyagentos/routes/desktop_browser/__init__.py",
                       "tinyagentos/routes/*.py") is False


# ---------------------------------------------------------------------------
# Changelog fragments: a new changelog.d/*.md file satisfies the changelog rule
# instead of editing CHANGELOG.md, so concurrent PRs cannot conflict on the
# shared [Unreleased] anchor. The gate must NOT go inert in the process.
# ---------------------------------------------------------------------------

CHANGELOG_RULE_CONFIG = {
    "gate": {"trailer": "Docs-Reviewed:"},
    "rules": [
        {
            "name": "user-visible-changelog",
            "on_modify": True,
            "when_changed": [
                "tinyagentos/routes/*.py",
                "desktop/src/apps/*/**",
                "desktop/src/App.tsx",
                "desktop/src/components/**",
                "desktop/src/stores/**",
                "tinyagentos/installers/*",
            ],
            "require_doc": ["CHANGELOG.md", "changelog.d/*.md"],
            "hint": "user-visible behaviour changed",
        },
    ],
}


class TestChangelogFragments:
    def test_fragment_satisfies_the_changelog_rule(self):
        changed = [
            ("M", "tinyagentos/routes/notifications.py"),
            ("A", "changelog.d/2291-notes.md"),
        ]
        assert dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG) == []

    def test_editing_changelog_directly_still_satisfies_it(self):
        """Additive, not a migration - the old path must keep working."""
        changed = [
            ("M", "tinyagentos/routes/notifications.py"),
            ("M", "CHANGELOG.md"),
        ]
        assert dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG) == []

    def test_neither_fragment_nor_changelog_nor_trailer_STILL_FAILS(self):
        """The point is fewer conflicts, NOT a weaker gate.

        If this ever passes the rule has gone inert and user-visible changes
        ship undocumented. This is the case that caught a real mistake while
        the feature was being built: putting the convention README inside
        changelog.d/ made it match the glob, so the gate went green here.
        """
        changed = [("M", "tinyagentos/routes/notifications.py")]
        failures = dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("user-visible-changelog -- ")

    def test_fragment_in_a_subdirectory_does_not_count(self):
        """One segment deep on purpose: a stray markdown file nested under
        changelog.d/ must not silently satisfy the rule."""
        changed = [
            ("M", "tinyagentos/routes/notifications.py"),
            ("A", "changelog.d/archive/old.md"),
        ]
        assert len(dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)) == 1

    def test_non_markdown_fragment_does_not_count(self):
        changed = [
            ("M", "tinyagentos/routes/notifications.py"),
            ("A", "changelog.d/2291-notes.txt"),
        ]
        assert len(dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)) == 1

    def test_desktop_app_shell_triggers_changelog_rule(self):
        changed = [("M", "desktop/src/App.tsx")]
        failures = dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("user-visible-changelog -- ")

    def test_desktop_component_triggers_changelog_rule(self):
        changed = [("M", "desktop/src/components/Desktop.tsx")]
        failures = dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("user-visible-changelog -- ")

    def test_desktop_store_triggers_changelog_rule(self):
        changed = [("M", "desktop/src/stores/theme-store.ts")]
        failures = dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG)
        assert len(failures) == 1
        assert failures[0].startswith("user-visible-changelog -- ")

    def test_desktop_shell_fragment_satisfies_rule(self):
        changed = [
            ("M", "desktop/src/App.tsx"),
            ("A", "changelog.d/2303-reduce-effects.md"),
        ]
        assert dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG) == []

    def test_desktop_shell_test_file_does_not_trigger(self):
        changed = [
            ("A", "desktop/src/components/__tests__/Desktop.test.tsx"),
            ("A", "desktop/src/stores/__tests__/theme-store.test.ts"),
        ]
        assert dg.evaluate_rules(changed, [], CHANGELOG_RULE_CONFIG) == []


class TestConfigErrorExitCode:
    """A broken/unparseable config must exit distinctly from a real violation.

    Regression: previously an unparseable config raised an unhandled traceback
    that exited 1 -- identical to a genuine doc-gate violation -- so a typo in
    docs/doc-gate.toml looked just like a missing changelog."""

    def test_unparseable_config_returns_config_error_code(self, tmp_path, capsys):
        bad = tmp_path / "bad.toml"
        bad.write_text('key = "unterminated string\n')
        rc = dg.main(["--config", str(bad), "print-trailer"])
        captured = capsys.readouterr()
        assert rc == dg.EXIT_CONFIG_ERROR
        assert rc != dg.EXIT_VIOLATION
        assert "config error" in captured.err

    def test_missing_config_file_returns_config_error_code(self, tmp_path):
        missing = tmp_path / "does_not_exist.toml"
        rc = dg.main(["--config", str(missing), "print-trailer"])
        assert rc == dg.EXIT_CONFIG_ERROR
        assert rc != dg.EXIT_VIOLATION

    def test_real_violation_returns_violation_not_config_error(self):
        """Exit code 1 (violation) must remain distinct from the config-error
        code."""
        changed = [("A", "tinyagentos/routes/themes.py")]
        failures = dg.evaluate_rules(changed, [], APPS_RULE_CONFIG)
        assert dg._report(failures) == dg.EXIT_VIOLATION

    def test_structurally_invalid_config_returns_config_error_code(self, tmp_path, capsys):
        """Valid TOML of the wrong shape (rules is a string, not a list of
        tables) must be caught as a config error, not crash the rule loop with
        an AttributeError that exits 1."""
        bad = tmp_path / "struct.toml"
        bad.write_text('rules = "not a list"\n[gate]\ntrailer = "X:"\n')
        rc = dg.main(["--config", str(bad), "print-trailer"])
        captured = capsys.readouterr()
        assert rc == dg.EXIT_CONFIG_ERROR
        assert rc != dg.EXIT_VIOLATION
        assert "config error" in captured.err

    def test_non_utf8_config_returns_config_error_code(self, tmp_path, capsys):
        """A config file with invalid UTF-8 bytes raises UnicodeDecodeError
        inside tomllib.load (which decodes before parsing).  That must be
        caught and reported as a config error, not exit 1."""
        bad = tmp_path / "bad_utf8.toml"
        bad.write_bytes(b'trailer = "Docs-Reviewed:"\n\x80\xff\xfe\n')
        rc = dg.main(["--config", str(bad), "print-trailer"])
        captured = capsys.readouterr()
        assert rc == dg.EXIT_CONFIG_ERROR
        assert rc != dg.EXIT_VIOLATION
        assert "config error" in captured.err

    def test_bad_cli_flag_exits_argparse_code(self):
        """A typo'd flag must exit with argparse's own code (2), distinct from
        both the violation code (1) and the config-error code."""
        with pytest.raises(SystemExit) as exc_info:
            dg.main(["diff-gate"])
        assert exc_info.value.code == 2
        assert exc_info.value.code != dg.EXIT_VIOLATION
        assert exc_info.value.code != dg.EXIT_CONFIG_ERROR

    def test_exit_codes_are_mutually_distinguishable(self):
        """The three non-zero outcomes must be mutually distinguishable:
        violation (1), argparse usage error (2), config error (not 2)."""
        assert dg.EXIT_OK == 0
        assert dg.EXIT_VIOLATION == 1
        assert dg.EXIT_CONFIG_ERROR != 1
        assert dg.EXIT_CONFIG_ERROR != 2

