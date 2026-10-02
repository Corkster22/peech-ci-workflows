"""PPA-1825 - a PEECHPMO key and a peechpmo-* branch get what PPA gets.

One test per row of PEECHPMO-507 comment 31081, rows 2 to 10. The workflow
rows run the shell step as written, as test_auto_merge_arm.py does, with `gh`
and `pt_transition.py` stubbed. Each fails on main, where the PEECHPMO case
takes the skip a non-ticket branch takes.
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pr_merge_close_out as closeout
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"

GH_STUB = """\
#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["pr", "list"] and "--head" in args:
    pass
elif args[:2] == ["pr", "list"] and "--jq" in args:
    expr = args[args.index("--jq") + 1]
    print(subprocess.run(["jq", "-r", expr], input=os.environ["FAKE_PRS"],
                         text=True, capture_output=True, check=True).stdout,
          end="")
elif args[:1] == ["api"]:
    print("mainsha")
elif args[:2] == ["pr", "view"]:
    print("peechpmo-501" if "headRefName" in " ".join(args) else "CLEAN")
"""


def bin_dir(tmp_path):
    path = tmp_path / "bin"
    path.mkdir()
    (path / "gh").write_text(textwrap.dedent(GH_STUB))
    (path / "gh").chmod(0o755)
    return path


def step(workflow, job, name_starts):
    steps = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]
    return next(s for s in steps if s.get("name", "").startswith(name_starts))


def bash(tmp_path, script, env, cwd=None):
    path = tmp_path / "step.sh"
    path.write_text(script)
    # Actions runs a bash `run:` step as `bash -e -o pipefail {0}`.
    return subprocess.run(["bash", "-e", "-o", "pipefail", str(path)],
                          env={**os.environ, **env}, cwd=cwd or tmp_path,
                          capture_output=True, text=True)


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=repo, check=True, capture_output=True)


def open_step(tmp_path, branch, subject):
    """Run pr-open.yml's open step on `branch`; return (process, repo, creates)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("base")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", "-b", branch)
    (repo / "a.txt").write_text("change")
    git(repo, "commit", "-q", "-am", subject)
    calls = tmp_path / "gh.log"
    done = bash(tmp_path, step("pr-open.yml", "open", "Open the pull")["run"], {
        "PATH": f"{bin_dir(tmp_path)}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "stub", "REPO": "owner/repo", "HEAD_REF": branch,
        "FAKE_GH_LOG": str(calls)}, cwd=repo)
    lines = calls.read_text().splitlines() if calls.exists() else []
    made = [json.loads(line) for line in lines]
    return done, repo, [c for c in made if c[:2] == ["pr", "create"]]


def test_row_2_a_push_to_a_peechpmo_branch_is_a_trigger():
    on = yaml.safe_load((WORKFLOWS / "pr-open.yml").read_text())[True]

    assert on["push"] == {"branches": ["ppa-*", "peechpmo-*"]}


def test_row_3_the_in_progress_hop_takes_a_peechpmo_branch_key(tmp_path):
    home = tmp_path / "home"
    creds = home / "Documents/Claude-Projects/peech-pmo-automation/secrets/.env"
    creds.parent.mkdir(parents=True)
    creds.write_text("JIRA_EMAIL=a@b\n")
    helper = tmp_path / ".peech-ci-workflows/scripts/pt_transition.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("import sys\nprint('ARGS', *sys.argv[1:])\n")

    done = bash(tmp_path, step("pr-open.yml", "open", "Move this")["run"],
                {"HOME": str(home), "HEAD_REF": "peechpmo-501"})

    assert "branch key: PEECHPMO-501" in done.stdout, done.stdout + done.stderr
    assert "ARGS --keys PEECHPMO-501 --to In Progress" in done.stdout


def test_row_4_guard_1_lets_a_peechpmo_branch_through(tmp_path):
    done, _, created = open_step(tmp_path, "peechpmo-501",
                                 "fix: the change (PEECHPMO-501)")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "does not match ppa-*" not in done.stdout
    assert len(created) == 1


def test_row_5_the_title_and_body_read_a_peechpmo_key(tmp_path):
    done, repo, created = open_step(tmp_path, "peechpmo-501",
                                    "fix: the change (PEECHPMO-501)")

    title = created[0][created[0].index("--title") + 1]
    assert title == "fix: the change (PEECHPMO-501)", done.stdout
    assert "PEECHPMO-501" in (repo / "pr-body.txt").read_text()


def test_row_4_a_branch_matching_neither_prefix_still_skips(tmp_path):
    done, _, created = open_step(tmp_path, "feature/x", "fix: a change")

    assert done.returncode == 0
    assert "SKIP: branch 'feature/x' does not match ppa-*." in done.stdout
    assert created == []


def sweep_with(tmp_path, head):
    from .test_auto_merge_arm import pr, sweep
    return sweep(tmp_path, [pr(61, head, armed=False, mergeable="MERGEABLE")])


def test_row_6_the_sweep_arms_a_peechpmo_branch(tmp_path):
    done, _ = sweep_with(tmp_path, "peechpmo-501")

    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "merged.log").read_text() == "61\n"


def test_row_6_a_branch_matching_neither_prefix_still_skips(tmp_path):
    done, _ = sweep_with(tmp_path, "feature/x")

    assert "SKIP: 'feature/x' does not match ppa-*." in done.stdout
    assert not (tmp_path / "merged.log").exists()


def behind(tmp_path, head):
    prs = [{"number": 61, "headRefName": head, "isDraft": False,
            "createdAt": "2026-10-02T10:00:00Z",
            "autoMergeRequest": {"mergeMethod": "SQUASH"}}]
    return bash(tmp_path, step("behind-branch-update.yml", "update",
                               "Update one")["run"], {
        "PATH": f"{bin_dir(tmp_path)}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "stub", "REPO": "owner/repo", "FAKE_PRS": json.dumps(prs),
        "FAKE_GH_LOG": str(tmp_path / "gh.log")})


def test_row_7_a_peechpmo_head_is_a_candidate_for_the_update(tmp_path):
    done = behind(tmp_path, "peechpmo-501")

    assert "SKIP: no open pull request is armed" not in done.stdout, done.stdout


def test_row_7_a_head_matching_neither_prefix_still_skips(tmp_path):
    done = behind(tmp_path, "feature/x")

    assert "SKIP: no open pull request is armed, on a ppa-* head" in done.stdout


def test_row_8_the_subject_key_reads_a_peechpmo_key():
    assert closeout.keys_from_subject(
        "fix: a change (PEECHPMO-501, PPA-9) (#159)") == ["PEECHPMO-501", "PPA-9"]
    assert closeout.keys_in("see docs/PEECHPMO-501-notes.md") == []


def test_row_9_the_branch_key_reads_a_peechpmo_branch():
    assert closeout.keys_from_branch("peechpmo-501") == ["PEECHPMO-501"]
    assert closeout.keys_from_branch("peechpmo-501-502-slug-9") == [
        "PEECHPMO-501", "PEECHPMO-502"]
    assert closeout.key_from_branch("PeechPMO-7-x") == "PEECHPMO-7"


def test_row_10_the_own_key_reads_a_peechpmo_commit_subject():
    assert closeout.own_keys_in(
        "fix: a change citing PPA-5 (PEECHPMO-501)") == ["PEECHPMO-501"]
    assert closeout.keys_from_commit_subjects(
        "fix: x (#1)\n\n* fix: first (PEECHPMO-501)\n* docs: second (PPA-3)\n"
    ) == ["PEECHPMO-501", "PPA-3"]


def test_row_10_a_peechpmo_heading_opens_a_section():
    lines = ["## PEECHPMO-501", "1. The first - MET", "## PPA-9",
             "1. The second - NOT MET"]

    assert [r.verdict for r in closeout.section_rows(lines, "PEECHPMO-501")] == ["MET"]
    assert [r.verdict for r in closeout.section_rows(lines, "PPA-9")] == ["NOT MET"]


def test_a_branch_and_message_matching_neither_prefix_close_out_nothing(capsys):
    code = closeout.main(["--message", "chore: tidy (#4)", "--sha", "abc",
                          "--head-ref", "feature/x"])

    assert code == closeout.OK
    assert ("no PPA key in branch 'feature/x', the merge commit subject or its "
            "commit subjects; nothing to close out") in capsys.readouterr().out
