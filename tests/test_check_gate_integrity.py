"""Tests for the gate-integrity guard (scripts/check_gate_integrity.py).

CLASS DEFECT (tsk-o2vhcq, flagged CodeRabbit #2510): every `pull_request`
gate checks out the PR MERGE REF and runs its checker FROM that checkout, so a
PR can edit its own checker (or its own workflow YAML) to always-exit-0 and
green-pass the check that gates it. A lane diff touching a gate script
alongside its nominal change is exactly the shape the gates exist to catch --
and today it would go green.

`check_gate_integrity.py` runs on `pull_request_target` from the BASE ref and
inspects the PR diff via the GitHub API only (no checkout, no execution of PR
code). These tests prove the acceptance criteria:

  RED   -- a PR diff that edits a gate checker to always-exit-0 trips the guard
           (the edit to scripts/check_*.py is itself the signal; because the
           guard runs from base, the tampered checker cannot disable it).
  GREEN -- a PR touching neither .github/workflows/ nor a gate checker passes.

The API layer is mocked at the narrowest scope (check_gate_integrity._api_get)
so the decision logic is exercised end-to-end without network access. Cannot-
see is never mistaken for clean: an API failure yields EXIT_ERROR (fail
closed).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package; make it importable like the other scripts/*.py
# gate tests (see tests/test_check_secret_ignores.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_gate_integrity as cgi  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _files_payload(filenames: list[str]) -> list[dict]:
    """Shape of GET /repos/{o}/{r}/pulls/{n}/files items: {'filename': str}."""
    return [{"filename": f} for f in filenames]


def _pr_payload(label_names: list[str]) -> list[dict]:
    # GET /pulls/{n} is a single object; _api_get wraps it in a list.
    return [{"labels": [{"name": lbl} for lbl in label_names]}]


def _api_get_routing(files: list[str], labels: list[str]):
    """Build a side_effect that routes files vs PR-object requests by URL."""

    def _fake(url: str, token: str | None = None, **_: object) -> list:
        if url.endswith("/files"):
            return _files_payload(files)
        # single-object /pulls/{n} endpoint
        return _pr_payload(labels)

    return _fake


# ---------------------------------------------------------------------------
# is_protected(path)
# ---------------------------------------------------------------------------


class TestIsProtected:
    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/bot-review-gate.yml",
            ".github/workflows/doc-gate.yml",
            ".github/workflows/secret-ignores-gate.yml",
            ".github/workflows/store-wiring-gate.yml",
            ".github/workflows/deleted-symbols-gate.yml",
            ".github/workflows/gate-integrity.yml",
            ".github/scripts/check_all_skip.py",
        ],
    )
    def test_gate_files_are_protected(self, path: str) -> None:
        assert cgi.is_protected(path)

    @pytest.mark.parametrize(
        "path",
        [
            "scripts/check_bot_review.py",
            "scripts/check_deleted_symbols.py",
            "scripts/check_doc_gate.py",
            "scripts/check_secret_ignores.py",
            "scripts/check_store_wiring.py",
            "scripts/check_dependency_audit_ignores.py",
            "scripts/check_manifests.py",
            "scripts/check_schema_migrations.py",
            "scripts/check_retrofit_migrations.py",
            "scripts/check_evil_merge.py",
            "scripts/check_gate_integrity.py",
        ],
    )
    def test_gate_checker_scripts_are_protected(self, path: str) -> None:
        assert cgi.is_protected(path)

    @pytest.mark.parametrize(
        "path",
        [
            "tinyagentos/app.py",
            "tinyagentos/routes/foo.py",
            "README.md",
            "desktop/package.json",
            "data/hub/identity.json",
            "scripts/audit-forks.py",
            "scripts/audit-manifests.py",
            # .github config that is not a workflow or gate script is not blocked
            ".github/dependabot.yml",
            ".github/FUNDING.yml",
            ".coderabbit.yaml",
            "docs/something.md",
            "changelog.d/foo.md",
            # a check_*.py nested in a subdir is NOT matched by the single
            # scripts/check_*.py convention the guard enforces
            "scripts/platform/check_foo.py",
        ],
    )
    def test_non_gate_paths_are_not_protected(self, path: str) -> None:
        assert not cgi.is_protected(path)

    def test_backslash_paths_normalised(self) -> None:
        assert cgi.is_protected(".github\\workflows\\gate.yml")
        assert not cgi.is_protected("tinyagentos\\app.py")


# ---------------------------------------------------------------------------
# classify(files, labels, allow_label) -- the RED / GREEN decision (pure)
# ---------------------------------------------------------------------------


class TestClassify:
    def test_green_when_no_protected_files(self) -> None:
        """GREEN control: a PR touching neither workflows nor gate scripts."""
        files = ["tinyagentos/app.py", "README.md", "desktop/src/foo.ts"]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_OK
        assert "PASS" in result.message

    def test_red_when_gate_script_edited_without_label(self) -> None:
        # RED proof: a lane edits its own checker to always-exit-0. The edit to
        # scripts/check_bot_review.py is itself the signal; the base guard
        # detects it and fails the PR.
        files = [
            "tinyagentos/some_feature.py",
            "scripts/check_bot_review.py",
        ]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED
        assert result.message.startswith("gate-integrity: FAIL")
        # the offending path is named in the message for the audit trail
        assert "scripts/check_bot_review.py" in result.message

    def test_red_when_workflow_edited_without_label(self) -> None:
        files = [".github/workflows/bot-review-gate.yml", "tinyagentos/app.py"]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED
        assert ".github/workflows/bot-review-gate.yml" in result.message

    def test_red_when_dotgithub_scripts_gate_edited(self) -> None:
        files = [".github/scripts/check_all_skip.py"]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED

    def test_allow_label_waives_protected_edit(self) -> None:
        files = ["scripts/check_bot_review.py"]
        result = cgi.classify(
            files, [cgi.DEFAULT_ALLOW_LABEL], cgi.DEFAULT_ALLOW_LABEL
        )
        assert result.exit_code == cgi.EXIT_OK
        assert "waived" in result.message

    def test_wrong_label_does_not_waive(self) -> None:
        files = ["scripts/check_bot_review.py"]
        # a different label name is not the allow label, so still blocked
        result = cgi.classify(files, ["some-other-label"], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED

    def test_multiple_protected_files_all_listed(self) -> None:
        files = [
            ".github/workflows/doc-gate.yml",
            "scripts/check_doc_gate.py",
            "scripts/check_store_wiring.py",
            "tinyagentos/app.py",
        ]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED
        assert "scripts/check_doc_gate.py" in result.message
        assert "scripts/check_store_wiring.py" in result.message
        assert ".github/workflows/doc-gate.yml" in result.message

    def test_duplicates_collapsed_in_message(self) -> None:
        files = ["scripts/check_bot_review.py", "scripts/check_bot_review.py"]
        result = cgi.classify(files, [], cgi.DEFAULT_ALLOW_LABEL)
        assert result.exit_code == cgi.EXIT_BLOCKED
        # one protected file, even though listed twice in the diff
        assert result.message.count("scripts/check_bot_review.py") == 1


# ---------------------------------------------------------------------------
# check_gate_integrity(owner, repo, pr) -- API wiring (mocked at _api_get)
# ---------------------------------------------------------------------------


class TestCheckGateIntegrity:
    def test_red_integration_gate_script_edit_fails(self) -> None:
        # Fixture: a PR diff that edits a gate checker to always-exit-0.
        files = ["scripts/check_bot_review.py", "tinyagentos/x.py"]
        with patch(
            "check_gate_integrity._api_get",
            side_effect=_api_get_routing(files, []),
        ):
            code, message = cgi.check_gate_integrity("jaylfc", "taOS", 42)
        assert code == cgi.EXIT_BLOCKED
        assert "scripts/check_bot_review.py" in message

    def test_green_integration_clean_pr_passes(self) -> None:
        # GREEN control: a PR touching neither workflows nor gate scripts.
        files = ["tinyagentos/app.py", "README.md"]
        with patch(
            "check_gate_integrity._api_get",
            side_effect=_api_get_routing(files, []),
        ):
            code, _ = cgi.check_gate_integrity("jaylfc", "taOS", 42)
        assert code == cgi.EXIT_OK

    def test_green_integration_when_allow_label_present(self) -> None:
        files = ["scripts/check_store_wiring.py"]
        with patch(
            "check_gate_integrity._api_get",
            side_effect=_api_get_routing(files, [cgi.DEFAULT_ALLOW_LABEL]),
        ):
            code, message = cgi.check_gate_integrity("jaylfc", "taOS", 42)
        assert code == cgi.EXIT_OK
        assert "waived" in message

    def test_infra_failure_fails_closed(self) -> None:
        # cannot-see must not read as clean pass: None from _api_get is an
        # infrastructure error -> EXIT_ERROR.
        with patch("check_gate_integrity._api_get", return_value=None):
            code, message = cgi.check_gate_integrity("jaylfc", "taOS", 42)
        assert code == cgi.EXIT_ERROR

    def test_fetches_files_then_labels(self) -> None:
        # The guard must consult BOTH the changed files AND the labels: a PR
        # editing a gate checker with the allow label must still pass.
        files = ["scripts/check_bot_review.py"]
        captured: list[str] = []

        def _spy(url: str, token: str | None = None, **_: object) -> list:
            captured.append(url)
            return _api_get_routing(files, [cgi.DEFAULT_ALLOW_LABEL])(url, token)

        with patch("check_gate_integrity._api_get", side_effect=_spy):
            code, _ = cgi.check_gate_integrity("jaylfc", "taOS", 42)
        assert code == cgi.EXIT_OK
        assert any(u.endswith("/files") for u in captured)
        assert any(u.endswith("/pulls/42") for u in captured)


# ---------------------------------------------------------------------------
# Live regression guards: the committed tree must not outrun the protected set
# ---------------------------------------------------------------------------


class TestCoversRealGates:
    def test_all_gate_checker_scripts_are_protected(self) -> None:
        """Every scripts/check_*.py on disk is a gate checker the guard must
        cover. If a new gate script were added outside the protected set, this
        would fail and force the set to be extended -- so the guard never goes
        silently blind to a gate."""
        scripts_dir = REPO_ROOT / "scripts"
        gate_scripts = sorted(scripts_dir.glob("check_*.py"))
        assert gate_scripts, "expected gate checker scripts under scripts/"
        for path in gate_scripts:
            rel = f"scripts/{path.name}"
            assert cgi.is_protected(rel), f"gate script not protected: {rel}"

    def test_all_workflow_files_are_protected(self) -> None:
        """Every .github/workflows/*.yml on dev is a required-check workflow
        whose edits must be caught by the base-ref guard."""
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        workflows = sorted(workflows_dir.glob("*.yml"))
        assert workflows, "expected workflow files under .github/workflows"
        for path in workflows:
            rel = f".github/workflows/{path.name}"
            assert cgi.is_protected(rel), f"workflow not protected: {rel}"

    def test_gh_scripts_gate_checker_is_protected(self) -> None:
        gh_scripts = REPO_ROOT / ".github" / "scripts"
        if not gh_scripts.is_dir():
            return
        for path in sorted(gh_scripts.glob("**/*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            assert cgi.is_protected(rel), f".github gate script not protected: {rel}"

    def test_real_repo_passes_integrity(self) -> None:
        # The committed tree must be itself green: no gate script should be
        # mid-tamper. The PR files for the real repo's HEAD (none) trivially
        # pass; this guards the classify/is_protected invariants together.
        assert cgi.classify([], [], cgi.DEFAULT_ALLOW_LABEL).exit_code == cgi.EXIT_OK
