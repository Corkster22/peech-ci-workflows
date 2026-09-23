"""Shared pytest fixtures/setup for scripts/tests.

PPA-1021 created this suite. `scripts/` had no test harness before it; the
package shape here (tests/ carrying __init__.py and conftest.py, run from the
directory that owns it) mirrors libs/shared/tests and pipelines/*/tests.

Two things worth knowing before adding to this suite:

* PPA-1101 wired `scripts/` into .github/workflows/test-suites.yml, so CI does
  run this suite — on a change under `scripts/` or `.claude/hooks/`. It is
  still NOT in the PPA-919 Stop hook (.claude/hooks/run_touched_tests.py maps
  only pipelines/<name>/ and libs/shared/, and passes silently on anything
  else), so nothing runs these tests at the end of a session — run them
  yourself before you push.
* The sys.path insert below puts scripts/ on the path, so the suite runs both
  from scripts/ (`python -m pytest tests/ -v`) and from the repo root
  (`python -m pytest scripts/tests/ -v`). Without it only the former works,
  and only by pytest's rootdir inference.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class StubJira:
    """A fake Jira that answers status and transition reads from a scripted
    map, and records every write.

    `plan` maps a status name to the transition list offered from it. Firing a
    transition moves the stub to that transition's `to` status, unless `stuck`
    names a status the stub refuses to leave — that models the real
    no-status-change case (a workflow condition silently rejecting the move,
    which returns success and changes nothing).
    """

    def __init__(self, status, plan, stuck=(), missing=()):
        self.status = status
        self.plan = plan
        self.stuck = set(stuck)
        self.missing = set(missing)
        self.posts = []
        self.status_reads = 0
        self.transition_reads = 0

    # -- the two callables the script consumes -------------------------------

    def get(self, path):
        if path.endswith("/transitions"):
            self.transition_reads += 1
            return {"transitions": self.plan.get(self.status, [])}
        self.status_reads += 1
        return {"fields": {"status": {"name": self.status}}}

    def post(self, path, payload):
        self.posts.append((path, payload))
        fired = payload["transition"]["id"]
        for candidate in self.plan.get(self.status, []):
            if candidate["id"] == fired:
                if self.status not in self.stuck:
                    self.status = candidate["to"]["name"]
                return None
        raise AssertionError(
            f"fired transition id {fired!r} is not offered from "
            f"{self.status!r}; the script invented an ID")


def transition(id_, name, to):
    """One entry in a stubbed transition set, shaped like the live payload."""
    return {"id": id_, "name": name, "to": {"name": to}}


@pytest.fixture()
def ppa_plan():
    """The live PPA Story workflow, as read on 13-AUG-2026.

    From To Do, five transitions are offered and only one of them is on the
    lifecycle ladder — that is the case the script has to get right, and the
    reason "fire the single available transition" is not a usable rule.

    The reject loop was added under PPA-1025 from the live sets read
    26-AUG-2026 off PPA-1188 and PPA-1126 — id 17 out of Client Validation and
    id 10 out of Reopened, which is the same transition To Do offers. There is
    no Reopened -> Client Validation shortcut in the live workflow and none is
    stubbed here: rework passes back through In Progress.
    """
    return {
        "To Do": [
            transition("4", "Info Returned - Resume Workflow", "Info Provided"),
            transition("5", "Request Info - Clarify with Client",
                       "Need More Info - Client"),
            transition("13", "Blocked - Escalate Issue", "BLOCKED"),
            transition("27", "Exit - Close as Not Needed",
                       "Closed - Not Needed"),
            transition("10", "Start - Move to In Progress", "In Progress"),
        ],
        "In Progress": [
            transition("13", "Blocked - Escalate Issue", "BLOCKED"),
            transition("21", "Ready - Move to Client Validation",
                       "Client Validation"),
            transition("3", "Closed - No client approval required", "Done"),
        ],
        "Client Validation": [
            transition("17", "Client Rejected - Restart Work", "Reopened"),
            transition("31", "Approved - Close", "Done"),
        ],
        "Reopened": [
            transition("10", "Start - Move to In Progress", "In Progress"),
        ],
    }
