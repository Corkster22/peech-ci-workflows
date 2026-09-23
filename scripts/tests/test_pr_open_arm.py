"""PPA-1611 — the push-arm job in the callable pr-open.yml.

The arm is one shell step ported unchanged from peech-skills (PPA-1435), so
these tests run that step as written, as test_auto_merge_arm.py does: the
`run:` block is read out of the workflow and executed by bash, with `gh`
stubbed on PATH and the settle time overridden to zero.
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import yaml

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/pr-open.yml")

PUSHED = "abc1234def5678"

GH_STUB = """\
#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    print(os.environ["FAKE_PRS"])
elif args[:2] == ["pr", "merge"]:
    with open(os.environ["FAKE_MERGE_LOG"], "a") as log:
        log.write(" ".join(args[2:]) + "\\n")
    sys.exit(int(os.environ["FAKE_MERGE_EXIT"]))
else:
    sys.exit("unexpected gh call: " + " ".join(args))
"""


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def pr(*, state="OPEN", oid=PUSHED, draft=False, armed=False):
    return {"number": 7, "state": state, "headRefOid": oid, "isDraft": draft,
            "mergeable": "MERGEABLE",
            "autoMergeRequest": {"mergeMethod": "SQUASH"} if armed else None}


def arm(tmp_path, prs, *, token="stub", merge_exit=0):
    """Run the arm step against `prs`; return the process, summary, merges."""
    step = workflow()["jobs"]["arm"]["steps"][0]
    script = tmp_path / "step.sh"
    script.write_text(step["run"])

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(textwrap.dedent(GH_STUB))
    (bin_dir / "gh").chmod(0o755)

    summary = tmp_path / "summary.md"
    merges = tmp_path / "merged.log"
    env = {**os.environ,
           "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "GH_TOKEN": token, "REPO": "owner/repo", "HEAD_REF": "ppa-1611",
           "PUSHED_SHA": PUSHED, "ARM_SETTLE_MINUTES": "0",
           "GITHUB_STEP_SUMMARY": str(summary),
           "FAKE_PRS": json.dumps(prs), "FAKE_MERGE_EXIT": str(merge_exit),
           "FAKE_MERGE_LOG": str(merges)}

    # Actions runs a bash `run:` step as `bash -e -o pipefail {0}`.
    done = subprocess.run(["bash", "-e", "-o", "pipefail", str(script)],
                          env=env, capture_output=True, text=True)
    return (done, summary.read_text() if summary.exists() else "",
            merges.read_text() if merges.exists() else "")


def test_arms_an_open_unarmed_pull_request(tmp_path):
    done, summary, merges = arm(tmp_path, [pr()])

    assert done.returncode == 0, done.stdout + done.stderr
    assert merges == "7 --repo owner/repo --auto --squash\n"
    assert "arm-attempt outcome=armed branch=ppa-1611" in done.stdout
    assert "| `armed` | `ppa-1611` | `abc1234` |" in summary


def test_records_already_armed(tmp_path):
    done, summary, merges = arm(tmp_path, [pr(armed=True)])

    assert done.returncode == 0, done.stdout + done.stderr
    assert merges == ""
    assert "| `already-armed` |" in summary


def test_records_draft_and_does_not_arm(tmp_path):
    done, summary, merges = arm(tmp_path, [pr(draft=True)])

    assert done.returncode == 0, done.stdout + done.stderr
    assert merges == ""
    assert "| `draft` |" in summary


def test_does_not_arm_when_the_head_moved_during_the_settle(tmp_path):
    done, summary, merges = arm(tmp_path, [pr(oid="fff9999")])

    assert done.returncode == 0, done.stdout + done.stderr
    assert merges == ""
    assert "| `head-moved` |" in summary
    assert "branch head is now fff9999" in summary


def test_records_already_merged(tmp_path):
    done, summary, merges = arm(tmp_path, [pr(state="MERGED")])

    assert done.returncode == 1, done.stdout + done.stderr
    assert merges == ""
    assert "| `already-merged` |" in summary
    assert "::error::pull request #7 for 'ppa-1611' has already merged." in (
        done.stdout)


def test_records_arm_failed_as_a_warning(tmp_path):
    done, summary, merges = arm(tmp_path, [pr()], merge_exit=1)

    assert done.returncode == 0, done.stdout + done.stderr
    assert merges != "", "the arm was attempted"
    assert "| `arm-failed` |" in summary
    assert "::warning::could not arm pull request #7" in done.stdout


def test_fails_loudly_on_a_missing_token(tmp_path):
    done, summary, merges = arm(tmp_path, [pr()], token="")

    assert done.returncode == 1, done.stdout + done.stderr
    assert merges == ""
    assert "| `no-token` |" in summary
    assert "::error::PEECH_AUTOMATION_TOKEN is empty or absent" in done.stdout


def test_arm_job_needs_open_and_cancels_on_the_next_push():
    job = workflow()["jobs"]["arm"]

    assert job["needs"] == "open"
    assert job["concurrency"] == {"group": "pr-arm-${{ github.ref }}",
                                  "cancel-in-progress": True}


def test_arm_job_permissions_fit_the_caller_grant():
    """A called workflow cannot hold more than its caller grants, and the
    callers grant contents: read and pull-requests: write."""
    flow = workflow()
    grant = {"contents": "read", "pull-requests": "write"}

    assert flow["jobs"]["arm"]["permissions"] == grant
    assert flow["permissions"] == grant
