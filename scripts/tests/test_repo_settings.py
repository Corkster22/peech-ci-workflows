"""repo_settings.py - the six tests named in PPA-1632.

Every gh call goes to FakeGitHub, which answers reads from a scripted state,
applies writes to that state so a re-read sees them, and records each call so
a test can assert exactly what would have been sent.
"""

import copy
import json

import repo_settings
from repo_settings import GhError, apply, check, main

REPO = "Org/live"
BLOCKED = "Org/blocked"


def entry(**overrides):
    """One repo-settings.json entry, with protection values overridable."""
    protection = {
        "pull_request_required": True,
        "required_approving_review_count": 0,
        "required_status_checks": ["pytest", "lint"],
        "strict": False,
        "enforce_admins": True,
    }
    protection.update(overrides)
    return {
        "branch": "main",
        "protection": protection,
        "merge": {"allow_auto_merge": True, "allow_squash_merge": True,
                  "delete_branch_on_merge": True},
    }


def live_protection(strict=False):
    """A live protection read, shaped like GitHub's response."""
    return {
        "required_status_checks": {"strict": strict,
                                   "contexts": ["lint", "pytest"]},
        "required_pull_request_reviews": {
            "required_approving_review_count": 0},
        "enforce_admins": {"enabled": True},
    }


class FakeGitHub:
    def __init__(self, repos, protections):
        self.repos = copy.deepcopy(repos)
        self.protections = copy.deepcopy(protections)
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        repo = "/".join(path.split("/")[1:3])
        if path.endswith("/protection"):
            if method == "GET":
                if repo not in self.protections:
                    raise GhError(f"gh api -X GET {path}: "
                                  "gh: Branch not protected (HTTP 404)")
                return self.protections[repo]
            assert method == "PUT", method
            self.protections[repo] = {
                "required_status_checks": {
                    "strict": body["required_status_checks"]["strict"],
                    "contexts": [c["context"] for c in
                                 body["required_status_checks"]["checks"]]},
                "required_pull_request_reviews":
                    body["required_pull_request_reviews"],
                "enforce_admins": {"enabled": body["enforce_admins"]},
            }
            return self.protections[repo]
        if method == "GET":
            return self.repos[repo]
        assert method == "PATCH", method
        self.repos[repo].update(body)
        return self.repos[repo]

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


MERGE_LIVE = {"allow_auto_merge": True, "allow_squash_merge": True,
              "delete_branch_on_merge": True}


def test_check_reports_match_when_live_equals_file():
    gh = FakeGitHub({REPO: MERGE_LIVE}, {REPO: live_protection()})

    lines, drifted = check(gh, {REPO: entry()})

    assert not drifted
    assert len(lines) == 8
    assert all(" MATCH " in line for line in lines), lines
    assert f'{REPO} required_status_checks MATCH ["lint", "pytest"]' in lines
    assert gh.writes() == []


def test_check_reports_drift_and_exits_nonzero(tmp_path, capsys):
    gh = FakeGitHub({REPO: MERGE_LIVE}, {REPO: live_protection(strict=True)})
    path = tmp_path / "repo-settings.json"
    path.write_text(json.dumps({REPO: entry()}))

    code = main(["--check"], gh=gh, settings_path=path)

    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert f"{REPO} strict DRIFT live=true file=false" in out
    assert [line for line in out if " DRIFT " in line] == [
        f"{REPO} strict DRIFT live=true file=false"]
    assert gh.writes() == []


def test_check_reports_blocked_repo_without_reading_protection():
    gh = FakeGitHub({REPO: MERGE_LIVE}, {REPO: live_protection()})
    blocked = {**entry(), "blocked_by": "PPA-1071"}

    lines, drifted = check(gh, {BLOCKED: blocked, REPO: entry()})

    assert not drifted
    assert [line for line in lines if line.startswith(BLOCKED)] == [
        f"{BLOCKED} {name} BLOCKED PPA-1071"
        for name in repo_settings.PROTECTION + repo_settings.MERGE]
    assert not any(BLOCKED in path for _, path, _ in gh.calls), gh.calls


def test_apply_writes_file_values_then_rereads(tmp_path, capsys):
    gh = FakeGitHub(
        {REPO: {"allow_auto_merge": False, "allow_squash_merge": True,
                "delete_branch_on_merge": False}},
        {REPO: live_protection(strict=True)})
    path = tmp_path / "repo-settings.json"
    path.write_text(json.dumps({REPO: entry()}))

    code = main(["--apply"], gh=gh, settings_path=path)

    assert gh.writes() == [
        ("PUT", f"repos/{REPO}/branches/main/protection", {
            "required_status_checks": {
                "strict": False,
                "checks": [{"context": "pytest"}, {"context": "lint"}]},
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "required_approving_review_count": 0},
            "restrictions": None,
        }),
        ("PATCH", f"repos/{REPO}", {"allow_auto_merge": True,
                                    "allow_squash_merge": True,
                                    "delete_branch_on_merge": True}),
    ]
    last_write = max(i for i, c in enumerate(gh.calls) if c[0] != "GET")
    assert ("GET", f"repos/{REPO}/branches/main/protection", None) in \
        gh.calls[last_write + 1:], "apply must re-read after writing"
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert len(out) == 8 and all(" MATCH " in line for line in out), out


def test_apply_skips_blocked_repo():
    gh = FakeGitHub({REPO: MERGE_LIVE}, {})
    blocked = {**entry(), "blocked_by": "PPA-1071"}

    apply(gh, {BLOCKED: blocked, REPO: entry(pull_request_required=False,
                                             required_approving_review_count=None)})

    assert [(m, p) for m, p, _ in gh.calls] == [
        ("PUT", f"repos/{REPO}/branches/main/protection"),
        ("PATCH", f"repos/{REPO}"),
    ]
    assert gh.calls[0][2]["required_pull_request_reviews"] is None


def test_no_flag_writes_nothing(tmp_path, capsys):
    gh = FakeGitHub({REPO: {"allow_auto_merge": False,
                            "allow_squash_merge": False,
                            "delete_branch_on_merge": False}}, {})
    path = tmp_path / "repo-settings.json"
    path.write_text(json.dumps({REPO: entry()}))

    code = main([], gh=gh, settings_path=path)

    assert code == 1
    assert gh.writes() == []
    assert {m for m, _, _ in gh.calls} == {"GET"}
    out = capsys.readouterr().out
    assert f"{REPO} pull_request_required DRIFT live=false file=true" in out
