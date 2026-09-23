"""PPA-1607 — the conflicting-base alarm in the callable auto-merge-arm.yml.

The sweep is one shell step, so these tests run that step as written: the
`run:` block is read out of the workflow and executed by bash, with `gh` and
`date` replaced by stubs on PATH. The rule stays in YAML because the ticket
names the workflow as the only file that changes, and running the step itself
is what lets the rule be tested there.
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import yaml

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/auto-merge-arm.yml")

#: 12:00Z on 23-SEP-2026, the sweep's clock.
NOW = 1790164800

GH_STUB = """\
#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    print(os.environ["FAKE_PRS"])
elif args[:2] == ["pr", "merge"]:
    with open(os.environ["FAKE_MERGE_LOG"], "a") as log:
        log.write(args[2] + "\\n")
elif args[:1] == ["api"]:
    print("2026-09-23T10:00:00Z")
elif args[:2] == ["run", "list"]:
    print("")
else:
    sys.exit("unexpected gh call: " + " ".join(args))
"""

# GNU date's two forms the step uses, so the test runs on macOS as well.
DATE_STUB = """\
#!/usr/bin/env python3
import os, sys
from datetime import datetime, timezone
args = [a for a in sys.argv[1:] if a != "-u"]
fmt = next(a for a in args if a.startswith("+"))[1:]
if "-d" in args:
    value = args[args.index("-d") + 1]
    if value.startswith("@"):
        moment = datetime.fromtimestamp(int(value[1:]), timezone.utc)
    else:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
else:
    moment = datetime.fromtimestamp(int(os.environ["FAKE_NOW"]), timezone.utc)
print(int(moment.timestamp()) if fmt == "%s" else moment.strftime(fmt))
"""


def pr(number, head, *, armed, mergeable):
    return {"number": number, "headRefName": head, "headRefOid": f"oid{number}",
            "isDraft": False, "mergeable": mergeable,
            "autoMergeRequest": {"mergeMethod": "SQUASH"} if armed else None}


def sweep(tmp_path, prs):
    """Run the sweep step against `prs`; return the process and its summary."""
    step = yaml.safe_load(WORKFLOW.read_text())["jobs"]["arm"]["steps"][0]
    script = tmp_path / "step.sh"
    script.write_text(step["run"])

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("date", DATE_STUB)):
        (bin_dir / name).write_text(textwrap.dedent(body))
        (bin_dir / name).chmod(0o755)

    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    summary = tmp_path / "summary.md"
    env = {**os.environ,
           "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "GH_TOKEN": "stub", "REPO": "owner/repo", "QUIET_MINUTES": "20",
           "GITHUB_STEP_SUMMARY": str(summary),
           "RUNNER_TEMP": str(runner_temp),
           "FAKE_PRS": json.dumps(prs), "FAKE_NOW": str(NOW),
           "FAKE_MERGE_LOG": str(tmp_path / "merged.log")}

    # Actions runs a bash `run:` step as `bash -e -o pipefail {0}`.
    done = subprocess.run(["bash", "-e", "-o", "pipefail", str(script)],
                          env=env, capture_output=True, text=True)
    return done, summary.read_text() if summary.exists() else ""


def test_a_conflicting_armed_pull_request_fails_the_sweep_naming_it(tmp_path):
    done, summary = sweep(tmp_path, [
        pr(41, "ppa-1600", armed=True, mergeable="CONFLICTING")])

    assert done.returncode == 1, done.stdout + done.stderr
    assert ("::error::pull request #41 (ppa-1600) is armed but cannot merge"
            in done.stdout)
    assert "| #41 | `ppa-1600` | armed, base CONFLICTING" in summary


def test_an_armed_pull_request_that_is_not_conflicting_does_not(tmp_path):
    done, summary = sweep(tmp_path, [
        pr(42, "ppa-1601", armed=True, mergeable="MERGEABLE")])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "::error::" not in done.stdout
    assert "SKIP: already armed (mergeable=MERGEABLE)." in done.stdout
    assert "#42" not in summary


def test_a_blocked_pull_request_does_not_stop_the_sweep_arming_the_rest(tmp_path):
    """The exit reports the blockage after the loop; it undoes no arming."""
    done, _ = sweep(tmp_path, [
        pr(43, "ppa-1602", armed=True, mergeable="CONFLICTING"),
        pr(44, "ppa-1603", armed=False, mergeable="MERGEABLE")])

    assert done.returncode == 1, done.stdout + done.stderr
    assert (tmp_path / "merged.log").read_text() == "44\n"
