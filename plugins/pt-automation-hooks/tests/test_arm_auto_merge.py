"""arm_auto_merge.py — the SessionEnd auto-merge arming hook (PPA-1407).

The hook is under the plugin's hooks/, not on sys.path, so it is loaded by path —
the same shape as test_transition_on_prompt.py.

No test here reaches GitHub and none reads the real credential file: CREDENTIALS
is repointed at a fixture on every test that touches it, and every ``gh`` call
is captured by a recorder rather than run. The two facts worth protecting are
what the hook refuses to do — fall back to another token, and arm a branch that
is not this session's — and neither is observable from the helpers alone, so
each test drives ``_arm()`` end to end.
"""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "arm_auto_merge.py"


def _load():
    spec = importlib.util.spec_from_file_location("arm_auto_merge", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()


class Recorder:
    """Stands in for ``gh``. Records every argv and env it was handed and
    replays a scripted response per subcommand."""

    def __init__(self, pr_rows="[]", merge_code=0):
        self.calls = []
        self.pr_rows = pr_rows
        self.merge_code = merge_code

    def __call__(self, argv, env=None):
        self.calls.append((argv, env or {}))
        if argv[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(argv, 0, self.pr_rows, "")
        if argv[:3] == ["gh", "pr", "merge"]:
            return subprocess.CompletedProcess(
                argv, self.merge_code, "", "" if not self.merge_code else "refused")
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def gh_argvs(self):
        return [argv for argv, _ in self.calls if argv and argv[0] == "gh"]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A hook wired to a fixture credential file, a fake repo, and a recorder.

    Returns the recorder plus the log path, and yields a ``run(**overrides)``
    that drives ``_arm()`` once.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "JIRA_EMAIL=someone@example.com\n"
        'PEECH_AUTOMATION_TOKEN="ghp_fixture"\n'
    )
    log = tmp_path / "arm.log"

    monkeypatch.setattr(hook, "CREDENTIALS", env_file)
    monkeypatch.setattr(hook, "LOG", log)
    monkeypatch.setattr(hook, "BUDGET", 0)
    monkeypatch.setattr(hook, "INTERVAL", 0)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-survive")

    state = {"branch": "ppa-1407",
             "remote": "https://github.com/Corkster22/peech-pmo-automation.git",
             "reflog": ""}

    def fake_git(root, *args):
        if args[:2] == ("branch", "--show-current"):
            return state["branch"]
        if args[:2] == ("remote", "get-url"):
            return state["remote"]
        if args[:1] == ("reflog",):
            return state["reflog"]
        return ""

    monkeypatch.setattr(hook, "git", fake_git)
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"hook_event_name": "SessionEnd", "reason": "clear"})))

    class Rig:
        def __init__(self):
            self.state = state
            self.log = log
            self.recorder = None

        def run(self, pr_rows="[]", merge_code=0, started_at=None):
            """Drive ``_arm()`` once.

            ``started_at`` stands in for the session's own start time. Left
            None the payload carries no transcript, ``session_start()``
            returns None, and the set collapses to the branch checked out at
            exit — which is what every case written before PPA-1417 assumes
            and why they still hold after the port.
            """
            self.recorder = Recorder(pr_rows, merge_code)
            monkeypatch.setattr(hook, "run", self.recorder)
            if started_at is not None:
                monkeypatch.setattr(hook, "session_start", lambda _p: started_at)
            return hook._arm()

        def records(self):
            return [json.loads(line) for line in
                    log.read_text().splitlines() if line.strip()]

    return Rig()


OPEN_PR = '[{"number": 46, "autoMergeRequest": null}]'
ARMED_PR = '[{"number": 46, "autoMergeRequest": {"enabledAt": "now"}}]'


class TestItArmsOnlyThisSessionsBranch:
    def test_a_ticket_branch_with_an_open_pull_request_is_armed(self, rig):
        assert rig.run(pr_rows=OPEN_PR) == 0
        assert ["gh", "pr", "merge", "46", "--repo",
                "Corkster22/peech-pmo-automation", "--auto",
                "--squash"] in rig.recorder.gh_argvs
        assert rig.records()[-1]["outcome"] == "armed"

    def test_the_lookup_is_scoped_to_the_branch_and_is_never_a_sweep(self, rig):
        rig.run(pr_rows=OPEN_PR)
        listing = next(a for a in rig.recorder.gh_argvs if a[:3] == ["gh", "pr", "list"])
        assert "--head" in listing and listing[listing.index("--head") + 1] == "ppa-1407"

    @pytest.mark.parametrize("branch", ["main", "", "feature/something"])
    def test_a_branch_that_is_not_a_ticket_branch_arms_nothing(self, rig, branch):
        rig.state["branch"] = branch
        assert rig.run(pr_rows=OPEN_PR) == 0
        assert rig.recorder.gh_argvs == []
        assert rig.records()[-1]["outcome"] == "not-a-ticket-branch"

    def test_an_already_armed_pull_request_is_left_alone(self, rig):
        assert rig.run(pr_rows=ARMED_PR) == 0
        assert not [a for a in rig.recorder.gh_argvs if a[:3] == ["gh", "pr", "merge"]]
        assert rig.records()[-1]["outcome"] == "already-armed"

    def test_no_pull_request_yet_is_reported_and_not_an_error(self, rig):
        assert rig.run(pr_rows="[]") == 0
        assert rig.records()[-1]["outcome"] == "no-pull-request"


class TestTheTokenRuleFromPpa1278:
    def test_gh_runs_under_the_automation_token(self, rig):
        rig.run(pr_rows=OPEN_PR)
        for argv, env in rig.recorder.calls:
            if argv[0] == "gh":
                assert env["GH_TOKEN"] == "ghp_fixture"

    def test_github_token_is_removed_rather_than_left_to_win(self, rig):
        rig.run(pr_rows=OPEN_PR)
        for argv, env in rig.recorder.calls:
            if argv[0] == "gh":
                assert "GITHUB_TOKEN" not in env

    def test_an_absent_token_arms_nothing_and_falls_back_to_nothing(
            self, rig, monkeypatch, tmp_path):
        bare = tmp_path / "bare.env"
        bare.write_text("JIRA_EMAIL=someone@example.com\n")
        monkeypatch.setattr(hook, "CREDENTIALS", bare)
        assert rig.run(pr_rows=OPEN_PR) == 0
        assert rig.recorder.gh_argvs == []
        assert rig.records()[-1]["outcome"] == "no-token"

    def test_a_missing_credential_file_arms_nothing(self, rig, monkeypatch, tmp_path):
        monkeypatch.setattr(hook, "CREDENTIALS", tmp_path / "absent.env")
        assert rig.run(pr_rows=OPEN_PR) == 0
        assert rig.recorder.gh_argvs == []


class TestItArmsAndNeverMerges:
    def test_the_only_merge_call_carries_auto_and_squash(self, rig):
        rig.run(pr_rows=OPEN_PR)
        merges = [a for a in rig.recorder.gh_argvs if a[:3] == ["gh", "pr", "merge"]]
        assert len(merges) == 1
        assert "--auto" in merges[0] and "--squash" in merges[0]

    def test_a_refused_arm_is_logged_and_still_exits_zero(self, rig):
        assert rig.run(pr_rows=OPEN_PR, merge_code=1) == 0
        assert rig.records()[-1]["outcome"] == "arm-failed"


class TestItNeverBlocksTheSessionEnding:
    def test_an_unreadable_payload_does_not_raise(self, rig, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert rig.run(pr_rows=OPEN_PR) == 0

    def test_an_unset_project_dir_exits_zero(self, rig, monkeypatch):
        monkeypatch.delenv("CLAUDE_PROJECT_DIR")
        assert rig.run() == 0
        assert rig.records()[-1]["outcome"] == "no-project-dir"

    def test_main_swallows_an_exception_and_logs_it(self, rig, monkeypatch):
        monkeypatch.setattr(hook, "_arm", lambda: 1 / 0)
        assert hook.main() == 0
        assert rig.records()[-1]["outcome"] == "hook-raised"

    def test_a_subprocess_that_cannot_start_is_a_failure_not_a_raise(self):
        proc = hook.run(["definitely-not-a-real-binary-ppa1407"])
        assert proc.returncode == 1


class TestItIsWired:
    """A hook file nobody registered is a file that never runs. This is the
    failure PPA-1407 hit for real: the arming call was written, tested and
    committed while .claude/settings.json still had no SessionEnd block.

    PPA-1586. The plugin registers it in hooks/hooks.json."""

    SETTINGS = HOOK.parent / "hooks.json"

    def _entry(self):
        blocks = json.loads(self.SETTINGS.read_text())["hooks"]["SessionEnd"]
        return [h for b in blocks for h in b["hooks"] if HOOK.name in h["command"]]

    def test_hooks_json_wires_this_hook_on_session_end(self):
        assert self._entry(), (
            f"{self.SETTINGS} has no SessionEnd hook naming {HOOK.name}. "
            "The file exists but nothing runs it.")

    def test_the_timeout_buys_the_poll_budget(self):
        """SessionEnd hooks share a 1.5-second budget unless a per-hook
        timeout raises it, so a timeout under BUDGET truncates the wait for
        pr-open.yml silently."""
        assert all(h.get("timeout", 0) >= hook.BUDGET for h in self._entry())


def reflog(*entries):
    """A reflog as ``--date=unix --format=%gd|%gs`` renders it, newest first."""
    return "\n".join(
        f"HEAD@{{{at}}}|checkout: moving from {frm} to {to}"
        for at, frm, to in entries)


@pytest.fixture
def branches(monkeypatch):
    """``session_branches()`` driven against a reflog fixture.

    The hook reads the reflog through its own ``git()``, so the fake goes
    there rather than into a second entry point written for the test.
    """
    def call(log, started_at, current):
        monkeypatch.setattr(hook, "git", lambda root, *args: log)
        return hook.session_branches("/repo", started_at, current)
    return call


class TestTheBranchSetComesFromTheReflog:
    """PPA-1417. The old hook read one branch — the checkout's own at exit —
    so a dispatch carrying four tickets armed the last pull request and left
    three to the half-hourly cron. The set is now every ppa-* branch the
    session's HEAD visited, bounded below by the session's own start."""

    def test_every_branch_the_session_touched_is_in_the_set(self, branches):
        log = reflog((1300, "ppa-1416", "ppa-1407"),
                     (1200, "ppa-1418", "ppa-1416"),
                     (1100, "main", "ppa-1418"))
        assert branches(log, 1000, "ppa-1407") == [
            "ppa-1407", "ppa-1416", "ppa-1418"]

    def test_the_current_branch_leads_because_it_carries_the_last_push(
            self, branches):
        log = reflog((1300, "ppa-1416", "ppa-1407"))
        assert branches(log, 1000, "ppa-1407")[0] == "ppa-1407"

    def test_a_checkout_older_than_the_session_is_not_in_the_set(self, branches):
        """The bound is what keeps this from becoming a sweep of the clone's
        whole history."""
        log = reflog((1300, "ppa-1416", "ppa-1407"),
                     (900, "ppa-0001", "ppa-1416"))
        assert branches(log, 1000, "ppa-1407") == ["ppa-1407", "ppa-1416"]

    def test_a_branch_that_is_not_ticket_shaped_is_never_in_the_set(
            self, branches):
        log = reflog((1300, "main", "ppa-1407"),
                     (1200, "feature/spike", "main"))
        assert branches(log, 1000, "ppa-1407") == ["ppa-1407"]

    def test_no_session_start_falls_back_to_the_branch_checked_out_at_exit(
            self, branches):
        """Narrower than intended, never wider — the pre-PPA-1417 behaviour."""
        log = reflog((1300, "ppa-1416", "ppa-1407"))
        assert branches(log, None, "ppa-1407") == ["ppa-1407"]

    def test_an_inherited_branch_is_reached_by_the_from_half_of_a_checkout(
            self, branches):
        """A session opening on a ticket branch left over from the last one
        checked it out before the window, so the move off it is the only
        entry inside the window that names it at all."""
        log = reflog((1300, "ppa-1414", "ppa-1407"))
        assert branches(log, 1000, "ppa-1407") == ["ppa-1407", "ppa-1414"]

    def test_a_branch_visited_twice_appears_once(self, branches):
        log = reflog((1300, "ppa-1416", "ppa-1407"),
                     (1200, "ppa-1407", "ppa-1416"))
        assert branches(log, 1000, "ppa-1407") == ["ppa-1407", "ppa-1416"]

    def test_a_non_ticket_branch_at_exit_does_not_lead_the_set(self, branches):
        log = reflog((1300, "ppa-1407", "main"))
        assert branches(log, 1000, "main") == ["ppa-1407"]


class TestTheSessionStartBound:
    """``st_birthtime`` is not portable. macOS on APFS records it; Linux does
    not, and ``os.stat_result`` there has no such attribute at all. The hook
    reads it through ``getattr(..., None)`` for that reason, so the bound is
    simply absent on a platform that does not keep one and the branch set
    falls back to the checkout's own — narrower than intended, never wider.

    Both halves are asserted, each where it is real, rather than pinning the
    macOS answer and failing the Linux runner on a difference the hook is
    already written to absorb.
    """

    HAS_BIRTHTIME = hasattr(Path(__file__).stat(), "st_birthtime")

    @pytest.mark.skipif(not HAS_BIRTHTIME,
                        reason="this filesystem records no birth time")
    def test_the_transcripts_birth_time_is_the_sessions_start(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}\n")
        born = transcript.stat().st_birthtime
        assert hook.session_start({"transcript_path": str(transcript)}) == born

    @pytest.mark.skipif(HAS_BIRTHTIME,
                        reason="this filesystem records a birth time")
    def test_no_birth_time_on_this_platform_is_none_not_a_raise(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}\n")
        assert hook.session_start({"transcript_path": str(transcript)}) is None

    def test_an_absent_birth_time_is_none_whatever_the_platform(
            self, tmp_path, monkeypatch):
        """The same path, forced, so the contract is pinned on both runners
        rather than only on whichever one happens to lack the attribute."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}\n")

        class NoBirthTime:
            pass

        monkeypatch.setattr(hook.Path, "stat", lambda self, **kw: NoBirthTime())
        assert hook.session_start({"transcript_path": str(transcript)}) is None

    def test_no_transcript_in_the_payload_is_none(self):
        assert hook.session_start({}) is None

    def test_a_transcript_that_is_gone_is_none_rather_than_a_raise(self, tmp_path):
        assert hook.session_start(
            {"transcript_path": str(tmp_path / "never-written.jsonl")}) is None

    def test_without_a_bound_the_set_is_the_checkout_s_own_branch_only(
            self, branches):
        """What a no-birth-time platform actually gets: the pre-PPA-1417
        behaviour, not a crash and not a sweep."""
        log = reflog((1300, "ppa-1416", "ppa-1407"))
        assert branches(log, None, "ppa-1407") == ["ppa-1407"]


class TestEveryBranchIsArmedNotOnlyTheLast:
    """The founding case, from PPA-1407's rejection: one /exit armed PR #52
    and left #48 through #51 to the cron."""

    THREE = reflog((1300, "ppa-1416", "ppa-1407"),
                   (1200, "ppa-1418", "ppa-1416"))

    def test_one_arm_call_is_made_for_each_branch_the_session_touched(self, rig):
        rig.state["reflog"] = self.THREE
        rig.run(pr_rows=OPEN_PR, started_at=1000)
        heads = [a[a.index("--head") + 1] for a in rig.recorder.gh_argvs
                 if a[:3] == ["gh", "pr", "list"]]
        assert heads == ["ppa-1407", "ppa-1416", "ppa-1418"]
        assert len([a for a in rig.recorder.gh_argvs
                    if a[:3] == ["gh", "pr", "merge"]]) == 3

    def test_a_branch_that_cannot_be_armed_does_not_stop_the_next(self, rig):
        rig.state["reflog"] = self.THREE
        assert rig.run(pr_rows=OPEN_PR, merge_code=1, started_at=1000) == 0
        outcomes = [r["outcome"] for r in rig.records()]
        assert outcomes == ["arm-failed"] * 3

    def test_an_absent_token_is_logged_once_per_branch(self, rig, monkeypatch):
        """So the log says how many pull requests a missing token cost."""
        monkeypatch.setattr(hook, "CREDENTIALS", rig.log.parent / "absent.env")
        rig.state["reflog"] = self.THREE
        rig.run(pr_rows=OPEN_PR, started_at=1000)
        assert [r["branch"] for r in rig.records()] == [
            "ppa-1407", "ppa-1416", "ppa-1418"]
        assert {r["outcome"] for r in rig.records()} == {"no-token"}

    def test_only_the_branch_checked_out_at_exit_spends_the_poll_budget(
            self, rig, monkeypatch, capsys):
        """BUDGET is the whole run's. Only the branch checked out at exit can
        still be racing pr-open.yml, because it carries the session's last
        push; every earlier branch was pushed minutes ago and one lookup
        settles it.

        The two paths are told apart by what they report, not by how long
        they took. A shared deadline has already expired by the time branch
        two is reached, so both spend roughly no time — but a branch handed
        no deadline reports a pull request that was never opened, and a
        branch handed an expired one reports a race it lost. Asserting on the
        elapsed time would hold under either.
        """
        monkeypatch.setattr(hook, "BUDGET", 0.03)
        monkeypatch.setattr(hook, "INTERVAL", 0.01)
        rig.state["reflog"] = self.THREE
        rig.run(pr_rows="[]", started_at=1000)

        heads = [a[a.index("--head") + 1] for a in rig.recorder.gh_argvs
                 if a[:3] == ["gh", "pr", "list"]]
        assert heads.count("ppa-1407") > 1, "the current branch never polled"

        said = capsys.readouterr().err
        assert "ppa-1407 not armed — no open pull request after" in said
        for branch in ("ppa-1416", "ppa-1418"):
            assert f"{branch} not armed — it has no open pull request." in said, (
                f"{branch} was given the poll budget; only the branch checked "
                "out at exit may wait for pr-open.yml")

    def test_a_branch_with_no_pull_request_is_reported_and_costs_one_lookup(
            self, rig):
        rig.state["reflog"] = reflog((1300, "ppa-1416", "ppa-1407"))
        rig.run(pr_rows="[]", started_at=1000)
        later = [r for r in rig.records() if r["branch"] == "ppa-1416"]
        assert [r["outcome"] for r in later] == ["no-pull-request"]
        assert later[0]["waited_seconds"] == 0


class TestTheSlugParse:
    @pytest.mark.parametrize("url", [
        "https://github.com/Corkster22/peech-skills.git",
        "https://github.com/Corkster22/peech-skills",
        "git@github.com:Corkster22/peech-skills.git",
        "ssh://git@github.com/Corkster22/peech-skills.git",
    ])
    def test_every_remote_spelling_resolves_to_owner_and_name(self, url):
        assert hook._SLUG_RE.search(url).group(1) == "Corkster22/peech-skills"


class TestAPeechpmoBranchIsATicketBranch:
    """PPA-1825. The SessionEnd arm took only ppa-* branches."""

    def test_a_peechpmo_branch_with_an_open_pull_request_is_armed(self, rig):
        rig.state["branch"] = "peechpmo-501"
        assert rig.run(pr_rows=OPEN_PR) == 0
        assert ["gh", "pr", "merge", "46", "--repo",
                "Corkster22/peech-pmo-automation", "--auto",
                "--squash"] in rig.recorder.gh_argvs
        assert rig.records()[-1]["outcome"] == "armed"

    def test_the_reflog_set_carries_both_prefixes(self, monkeypatch):
        log = reflog((1300, "peechpmo-501", "ppa-1407"),
                     (1200, "feature/x", "peechpmo-501"))
        monkeypatch.setattr(hook, "git", lambda root, *args: log)
        assert hook.session_branches("/repo", 1000, "ppa-1407") == [
            "ppa-1407", "peechpmo-501"]
