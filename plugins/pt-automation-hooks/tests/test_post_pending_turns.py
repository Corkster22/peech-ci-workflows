"""post_pending_turns.py - the SessionStart hook that posts earlier sessions' turns
(PPA-1774).

Each case drives main() end to end: a SessionStart payload on stdin, session
transcripts under a fake ~/.claude/projects, a credentials file in tmp_path, and
the HTTP layer replaced by a router that records every request. No case reaches
Tempo, Jira or Slack. The Stop hook is driven through the same module instance,
so the two hooks are compared on the code they actually share.
"""

import importlib.util
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path.insert(0, str(HOOKS))


def _load():
    spec = importlib.util.spec_from_file_location(
        "post_pending_turns", HOOKS / "post_pending_turns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pending = _load()
worklog = pending.worklog

REPOS = ("peech-pmo-automation", "peech-skills", "peech-org-skills", "peech-ci-workflows")
A_UUID = "11111111-aaaa"
B_UUID = "22222222-bbbb"


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def turn(uuid, seconds, end="2026-09-30T14:00:00.000Z"):
    return {"type": "system", "subtype": "turn_duration", "durationMs": seconds * 1000,
            "timestamp": end, "uuid": uuid}


class Router:
    """Stands in for http_json and records every request."""

    def __init__(self, *, existing=(), fail_post=None, slack=None):
        self.existing, self.fail_post, self.slack = list(existing), fail_post, slack
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if "slack.com/api/" in url:
            if isinstance(self.slack, Exception):
                raise self.slack
            return {"ok": True, "user": {"id": "U1"}, "channel": {"id": "D1"}}
        if self.fail_post and method == "POST":
            raise self.fail_post
        if url.endswith("/myself"):
            return {"accountId": worklog.SEAN}
        if "/worklogs/issue/" in url:
            return {"results": [{"description": d} for d in self.existing], "metadata": {}}
        if "/issue/" in url:
            return {"id": str(45000 + int(re.search(r"-(\d+)\?", url).group(1)))}
        return {}

    @property
    def posts(self):
        return [body for method, url, _, body in self.calls
                if method == "POST" and "tempo.io" in url]

    @property
    def messages(self):
        return [body["text"] for _, url, _, body in self.calls
                if url.endswith("/chat.postMessage")]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home: projects dir, credentials, log and alert state in tmp_path."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    projects = tmp_path / ".claude" / "projects"
    projects.mkdir(parents=True)
    env = tmp_path / ".env"
    env.write_text("JIRA_EMAIL=s@example.test\nJIRA_API_TOKEN=j\n"
                   "TEMPO_FM_OAUTH_TOKEN=t\nSLACK_BOT_TOKEN=x\n")
    monkeypatch.setattr(pending, "PROJECTS", projects)
    monkeypatch.setattr(worklog, "CREDENTIALS", env)
    monkeypatch.setattr(worklog, "LOG", tmp_path / "hook.log")
    monkeypatch.setattr(worklog, "ALERTS", tmp_path / "alerts.json")
    return tmp_path


def session(home, session_id, rows, repo="peech-skills"):
    """Write one earlier session under the project directory Claude Code would
    name for ``repo`` ('' for a folder that is not one of the four)."""
    folder = re.sub(r"[^A-Za-z0-9]", "-", str(home / "Documents" / "Claude-Projects" / repo))
    path = home / ".claude" / "projects" / folder / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def start(monkeypatch, router=None, source="startup"):
    router = router or Router()
    monkeypatch.setattr(worklog, "http_json", router)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "new", "source": source, "transcript_path": "/nowhere"})))
    return pending.main(), router


def log_lines(home):
    log = home / "hook.log"
    return log.read_text().splitlines() if log.exists() else []


# --- the sweep ---------------------------------------------------------------


def test_an_earlier_sessions_unposted_final_turn_posts_once_tagged_and_a_second_start_posts_nothing(
        home, monkeypatch):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 1790)])

    code, router = start(monkeypatch)
    assert code == 0
    assert [(p["issueId"], p["timeSpentSeconds"], p["description"]) for p in router.posts] == [
        (46774, 1800, f"cc-turn:old:{A_UUID}")]
    assert router.posts[0]["billableSeconds"] == 0

    code, second = start(monkeypatch, Router(existing=[f"cc-turn:old:{A_UUID}"]))
    assert (code, second.posts) == (0, [])


def test_a_turn_the_stop_hook_already_tagged_is_not_posted_again(home, monkeypatch):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 100), turn(B_UUID, 100)])

    _, router = start(monkeypatch, Router(existing=[f"cc-turn:old:{A_UUID}"]))

    assert [p["description"] for p in router.posts] == [f"cc-turn:old:{B_UUID}"]


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact", "fork"])
def test_every_start_source_sweeps(home, monkeypatch, source):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 100)])
    _, router = start(monkeypatch, source=source)
    assert len(router.posts) == 1


def test_a_session_outside_the_four_repositories_is_not_swept(home, monkeypatch):
    session(home, "elsewhere", [prompt("PPA-1774"), turn(A_UUID, 100)], repo="some-other-repo")
    session(home, "scratch", [prompt("PPA-1774"), turn(B_UUID, 100)],
            repo="peech-skills-scratch")

    code, router = start(monkeypatch)

    assert (code, router.posts, router.messages) == (0, [], [])


@pytest.mark.parametrize("repo", REPOS)
def test_each_of_the_four_repositories_is_swept(home, monkeypatch, repo):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 100)], repo=repo)
    _, router = start(monkeypatch)
    assert len(router.posts) == 1


def test_a_turn_before_the_cutoff_is_not_posted(home, monkeypatch):
    session(home, "old", [prompt("PPA-1774"),
                          turn(A_UUID, 100, end="2026-09-23T23:00:00.000Z")])
    _, router = start(monkeypatch)
    assert router.posts == []


def test_every_earlier_session_is_swept_oldest_first(home, monkeypatch):
    first = session(home, "one", [prompt("PPA-1"), turn(A_UUID, 100)])
    second = session(home, "two", [prompt("PPA-2"), turn(B_UUID, 100)])
    now = time.time()
    os.utime(first, (now - 200, now - 200))
    os.utime(second, (now - 100, now - 100))

    _, router = start(monkeypatch)

    assert [p["issueId"] for p in router.posts] == [45001, 45002]
    assert len([c for c in router.calls if c[1].endswith("/myself")]) == 1


def test_the_project_directory_is_named_as_claude_code_names_it(home):
    assert pending.project_dirs() == {
        re.sub(r"[^A-Za-z0-9]", "-", str(home / "Documents" / "Claude-Projects" / name))
        for name in REPOS}
    assert "-peech-ci-workflows" in "".join(pending.project_dirs())


# --- alerts, through the same code ------------------------------------------


def test_a_failed_tempo_post_sends_one_direct_message_and_exits_0(home, monkeypatch):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 100), turn(B_UUID, 100)])

    code, router = start(monkeypatch, Router(fail_post=RuntimeError("POST -> HTTP 403")))

    assert code == 0
    assert len(router.messages) == 1
    for part in ("a Tempo post failed", "Session old", "2026-09-30 10:00 ET",
                 "length 1m 40s", "HTTP 403"):
        assert part in router.messages[0]


def test_a_ticketless_turn_sends_one_direct_message_and_posts_nothing(home, monkeypatch):
    session(home, "old", [prompt("hello"), turn(A_UUID, 100), turn(B_UUID, 100)])

    code, router = start(monkeypatch)

    assert (code, router.posts) == (0, [])
    assert len(router.messages) == 1
    assert "no dispatch key" in router.messages[0] and "Session old" in router.messages[0]

    _, again = start(monkeypatch)
    assert again.messages == [], "one message per session per reason"


def test_a_slack_failure_is_logged_and_the_hook_exits_0(home, monkeypatch):
    session(home, "old", [prompt("hello"), turn(A_UUID, 100)])

    code, router = start(monkeypatch, Router(slack=OSError("down")))

    assert code == 0
    assert any("alert not sent: OSError: down" in line for line in log_lines(home))


# --- fail open ---------------------------------------------------------------


def test_a_missing_credentials_file_exits_0_and_logs(home, monkeypatch):
    (home / ".env").unlink()
    code, router = start(monkeypatch)
    assert (code, router.calls) == (0, [])
    assert "FileNotFoundError" in log_lines(home)[0]


def test_a_network_failure_ends_the_run_with_exit_0(home, monkeypatch):
    session(home, "old", [prompt("PPA-1"), turn(A_UUID, 100), turn(B_UUID, 100)])
    code, router = start(monkeypatch, Router(fail_post=TimeoutError("timed out")))
    assert code == 0 and len(router.posts) == 1
    assert "TimeoutError" in log_lines(home)[0]


def test_an_unreadable_payload_still_sweeps_and_exits_0(home, monkeypatch):
    session(home, "old", [prompt("PPA-1774"), turn(A_UUID, 100)])
    router = Router()
    monkeypatch.setattr(worklog, "http_json", router)
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert pending.main() == 0
    assert len(router.posts) == 1


def test_the_hook_prints_nothing(home, monkeypatch, capsys):
    """SessionStart stdout is injected into the model's context."""
    session(home, "old", [prompt("hello"), turn(A_UUID, 100)])
    start(monkeypatch)
    assert capsys.readouterr().out == ""


def test_no_code_path_exits_with_code_2():
    source = (HOOKS / "post_pending_turns.py").read_text()
    assert not re.search(r"exit\s*\(\s*2\b|SystemExit\s*\(\s*2\b|return\s+2\b", source)


# --- one rounding rule, both hooks -------------------------------------------


def test_the_same_turn_posted_through_each_hook_posts_the_same_seconds(home, monkeypatch):
    rows = [prompt("PPA-1, PPA-2, PPA-3"), turn(A_UUID, 100), turn(B_UUID, 485)]
    path = session(home, "old", rows)

    _, from_start = start(monkeypatch)

    stop = Router()
    monkeypatch.setattr(worklog, "http_json", stop)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "old", "transcript_path": str(path)})))
    assert worklog.main() == 0

    seconds = lambda router: [(p["issueId"], p["description"], p["timeSpentSeconds"])
                              for p in router.posts]
    assert seconds(from_start) == seconds(stop) != []
    assert all(s % 360 == 0 for _, _, s in seconds(stop))


def test_both_hooks_round_through_the_one_function(monkeypatch, home):
    """Replace the shared function and both hooks follow it."""
    session(home, "old", [prompt("PPA-1"), turn(A_UUID, 100)])
    monkeypatch.setattr(worklog, "round_up", lambda seconds: 7777)

    _, router = start(monkeypatch)

    assert [p["timeSpentSeconds"] for p in router.posts] == [7777]
    assert pending.worklog is worklog
