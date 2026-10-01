"""log_turn_worklog.py - the Stop hook that posts each turn to Tempo (PPA-1757).

Each case drives main() end to end: a Stop payload on stdin, a transcript on
disk, a credentials file in tmp_path, and the HTTP layer replaced by a router
that records every request. No case reaches Tempo or Jira. What the hook
posted is read off the recorder.
"""

import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "log_turn_worklog.py"


def _load():
    spec = importlib.util.spec_from_file_location("log_turn_worklog", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

SESSION = "856c3549-0c10-4463-b59a-c9c27b7d6acc"
TURN_UUID = "54ca0f2d-5eb9-421b-bcb8-b9015e0fc96a"
TAG = f"cc-turn:{SESSION}:{TURN_UUID}"
#: The row PPA-1676 Q4 quoted, trimmed to the fields the hook reads. It ends
#: 2026-09-24T21:42:55.592Z after 485745 ms, so it started 17:34:49 EDT.
TURN = {"type": "system", "subtype": "turn_duration", "durationMs": 485745,
        "timestamp": "2026-09-24T21:42:55.592Z", "uuid": TURN_UUID}


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def turn(**fields):
    return {**TURN, **fields}


class Router:
    """Stands in for http_json and records every request."""

    def __init__(self, *, account=hook.SEAN, existing=(), fail=None, missing=None):
        self.account, self.existing, self.fail = account, list(existing), fail
        self.missing = missing
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if self.fail:
            raise self.fail
        if url.endswith("/myself"):
            return {"accountId": self.account}
        if self.missing and f"/issue/{self.missing}?" in url:
            raise RuntimeError(f"GET {url} -> HTTP 404")
        if "/issue/" in url:
            return {"id": str(45000 + int(re.search(r"-(\d+)\?", url).group(1)))}
        if method == "GET":
            return {"results": [{"description": d} for d in self.existing], "metadata": {}}
        return {}

    @property
    def posts(self):
        return [body for method, _, _, body in self.calls if method == "POST"]


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Drive main(); returns (exit code, router, log lines)."""
    log = tmp_path / "hook.log"
    env = tmp_path / ".env"
    monkeypatch.setattr(hook, "LOG", log)
    monkeypatch.setattr(hook, "CREDENTIALS", env)

    def go(rows, *, router=None, credentials=True, payload=None, transcript=True):
        router = router or Router()
        monkeypatch.setattr(hook, "http_json", router)
        path = tmp_path / "t.jsonl"
        if transcript:
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        if credentials:
            env.write_text("JIRA_EMAIL=s@example.test\nJIRA_API_TOKEN=j\n"
                           "TEMPO_FM_OAUTH_TOKEN='t'\n")
        body = payload if payload is not None else json.dumps(
            {"session_id": SESSION, "transcript_path": str(path)})
        monkeypatch.setattr(sys, "stdin", io.StringIO(body))
        code = hook.main()
        lines = log.read_text().splitlines() if log.exists() else []
        return code, router, lines

    return go


# --- turn parsing -----------------------------------------------------------


def test_the_latest_turn_duration_row_is_the_turn(tmp_path):
    path = tmp_path / "t.jsonl"
    older = turn(uuid="older", durationMs=1000)
    path.write_text("\n".join(json.dumps(r) for r in
                              [prompt("PPA-1"), older, prompt("hi"), TURN]))
    row, keys = hook.latest_turn(path)
    assert row["uuid"] == TURN_UUID and keys == ["PPA-1"]


def test_a_transcript_with_no_turn_duration_row_has_no_turn(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in
                              [prompt("PPA-1"), {"type": "assistant"}]))
    assert hook.latest_turn(path) is None


def test_unparseable_lines_and_non_object_rows_are_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(["not json", "[1]", json.dumps(prompt("PPA-1")),
                               json.dumps(TURN)]))
    assert hook.latest_turn(path)[1] == ["PPA-1"]


def test_a_headless_session_posts_nothing(run):
    code, router, lines = run([prompt("PPA-1757"), {"type": "assistant"}])
    assert (code, router.calls, lines) == (0, [], [])


# --- dispatch keys: the three forms ----------------------------------------


@pytest.mark.parametrize("text, keys", [
    ("PPA-1757", ["PPA-1757"]),
    ("PPA-1757, PPA-1756\n\nrun both", ["PPA-1757", "PPA-1756"]),
    ("Execute PPA-1757.", ["PPA-1757"]),
    ('<pasted_content id="a1">\nPPA-1757, PEECHPMO-12\n</pasted_content>',
     ["PPA-1757", "PEECHPMO-12"]),
    ('<pasted_content id="a1">\n\n  ppa-9 , PPA-9  \n', ["PPA-9"]),
    ("PPA-1289. Fetch the ticket for the spec.", []),
    ("What does PPA-1757 do?", []),
    ("", []),
])
def test_dispatch_keys(text, keys):
    assert hook.dispatch_keys(text) == keys


def test_the_latest_dispatch_holds_until_the_next(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [prompt("PPA-1"), turn(uuid="a"), prompt("a question about PPA-9"),
            turn(uuid="b"), prompt("Execute PPA-2."), TURN]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert hook.latest_turn(path)[1] == ["PPA-2"]
    path.write_text("\n".join(json.dumps(r) for r in rows[:4]))
    assert hook.latest_turn(path)[1] == ["PPA-1"]


def test_tool_results_and_meta_rows_are_not_dispatches(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [prompt("PPA-1"),
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "PPA-7"}]}},
            {"type": "user", "isMeta": True, "message": {"content": "PPA-8"}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "PPA-3"}]}},
            TURN]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert hook.latest_turn(path)[1] == ["PPA-3"]


def test_a_turn_with_no_dispatch_posts_nothing(run):
    code, router, lines = run([prompt("hello"), TURN])
    assert (code, router.calls, lines) == (0, [], [])


# --- the split --------------------------------------------------------------


@pytest.mark.parametrize("total, count, parts", [
    (486, 1, [486]), (10, 3, [4, 3, 3]), (9, 3, [3, 3, 3]), (2, 3, [2, 0, 0])])
def test_split_gives_the_remainder_to_the_first_key(total, count, parts):
    assert hook.split_seconds(total, count) == parts
    assert sum(parts) == total


# --- the post ---------------------------------------------------------------


def test_one_key_posts_one_non_billable_worklog_for_sean(run):
    code, router, lines = run([prompt("PPA-1757"), TURN])
    assert (code, lines) == (0, [])
    assert router.posts == [{
        "issueId": 46757, "authorAccountId": hook.SEAN, "startDate": "2026-09-24",
        "startTime": "17:34:49", "timeSpentSeconds": 486, "billableSeconds": 0,
        "description": TAG}]
    method, url, headers, _ = router.calls[-1]
    assert (method, url) == ("POST", "https://api.tempo.io/4/worklogs")
    assert headers == {"Authorization": "Bearer t"}


def test_the_tag_is_the_description_character_for_character(run):
    _, router, _ = run([prompt("PPA-1757"), TURN])
    assert router.posts[0]["description"] == hook.tag(SESSION, TURN_UUID)
    assert hook.tag("S", "U") == "cc-turn:S:U"


def test_several_keys_split_the_turn_and_sum_to_it(run):
    _, router, _ = run([prompt("PPA-1, PPA-2, PPA-3"), turn(durationMs=10000)])
    assert [(p["issueId"], p["timeSpentSeconds"]) for p in router.posts] == [
        (45001, 4), (45002, 3), (45003, 3)]
    assert {p["description"] for p in router.posts} == {TAG}


def test_a_key_with_no_seconds_left_is_not_posted(run):
    _, router, _ = run([prompt("PPA-1, PPA-2, PPA-3"), turn(durationMs=2000)])
    assert [p["issueId"] for p in router.posts] == [45001]


def test_the_start_date_is_the_start_in_eastern_time(run):
    """Starts 00:00 UTC on the 25th, which is 20:00 EDT on the 24th."""
    _, router, _ = run([prompt("PPA-1"), turn(
        timestamp="2026-09-25T01:00:00.000Z", durationMs=3600000)])
    assert router.posts[0]["startDate"] == "2026-09-24"
    assert router.posts[0]["startTime"] == "20:00:00"


def test_a_turn_already_in_tempo_is_skipped(run):
    router = Router(existing=["unrelated", f"note {TAG}"])
    code, router, lines = run([prompt("PPA-1757"), TURN], router=router)
    assert (code, router.posts, lines) == (0, [], [])


def test_a_different_turns_tag_does_not_skip_this_one(run):
    router = Router(existing=[f"cc-turn:{SESSION}:another-uuid"])
    _, router, _ = run([prompt("PPA-1757"), TURN], router=router)
    assert len(router.posts) == 1


def test_the_existing_tag_lookup_follows_tempo_paging(monkeypatch):
    pages = iter([{"results": [], "metadata": {"next": "https://api.tempo.io/next"}},
                  {"results": [{"description": TAG}], "metadata": {}}])
    seen = []
    monkeypatch.setattr(hook, "http_json",
                        lambda method, url, headers, body=None: seen.append(url) or next(pages))
    assert hook.tag_posted({}, "2026-09-24", TAG) is True
    assert seen[1] == "https://api.tempo.io/next"


def test_anyone_but_sean_posts_nothing_and_logs_nothing(run):
    code, router, lines = run([prompt("PPA-1757"), TURN],
                              router=Router(account="712020:someone-else"))
    assert (code, router.posts, lines) == (0, [], [])
    assert [c[1] for c in router.calls] == ["https://peech-team.atlassian.net/rest/api/3/myself"]


# --- every failure path exits 0 and writes one log line ---------------------


def _one_line(lines, *, turn_name, reason):
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["turn"] == turn_name and reason in record["reason"] and record["at"]


def test_a_missing_transcript_exits_0_with_one_log_line(run):
    code, router, lines = run([], transcript=False)
    assert (code, router.calls) == (0, [])
    _one_line(lines, turn_name=SESSION, reason="FileNotFoundError")


def test_a_missing_credentials_file_exits_0_with_one_log_line(run):
    code, router, lines = run([prompt("PPA-1757"), TURN], credentials=False)
    assert (code, router.calls) == (0, [])
    _one_line(lines, turn_name=TAG, reason="FileNotFoundError")


def test_missing_credentials_in_the_file_exit_0_with_one_log_line(run, tmp_path):
    (tmp_path / ".env").write_text("JIRA_EMAIL=s@example.test\n")
    code, router, lines = run([prompt("PPA-1757"), TURN], credentials=False)
    assert (code, router.calls) == (0, [])
    _one_line(lines, turn_name=TAG, reason="KeyError")


def test_an_http_error_exits_0_with_one_log_line(run):
    router = Router(fail=RuntimeError("POST https://api.tempo.io/4/worklogs -> HTTP 403"))
    code, router, lines = run([prompt("PPA-1757"), TURN], router=router)
    assert (code, router.posts) == (0, [])
    _one_line(lines, turn_name=TAG, reason="HTTP 403")


def test_a_timeout_exits_0_with_one_log_line(run):
    code, _, lines = run([prompt("PPA-1757"), TURN], router=Router(fail=TimeoutError("timed out")))
    assert code == 0
    _one_line(lines, turn_name=TAG, reason="TimeoutError")


def test_a_key_jira_cannot_resolve_posts_nothing_for_the_turn(run):
    code, router, lines = run([prompt("PPA-1, PPA-2"), TURN], router=Router(missing="PPA-2"))
    assert (code, router.posts) == (0, [])
    _one_line(lines, turn_name=TAG, reason="HTTP 404")


@pytest.mark.parametrize("payload", ["", "not json", "{}", '{"session_id": "s"}'])
def test_an_unreadable_hook_input_exits_0_with_one_log_line(run, payload):
    code, router, lines = run([], payload=payload)
    assert (code, router.calls) == (0, [])
    assert len(lines) == 1


def test_a_turn_row_with_no_timestamp_exits_0_with_one_log_line(run):
    bad = {k: v for k, v in TURN.items() if k != "timestamp"}
    code, router, lines = run([prompt("PPA-1757"), bad])
    assert (code, router.posts) == (0, [])
    _one_line(lines, turn_name=TAG, reason="KeyError")


def test_an_unusable_duration_posts_nothing(run):
    for ms in (0, -5, "100", True, None):
        code, router, lines = run([prompt("PPA-1757"), turn(durationMs=ms)])
        assert (code, router.calls, lines) == (0, [], [])


def test_the_deadline_stops_a_request_before_it_is_sent(monkeypatch):
    monkeypatch.setattr(hook, "_started", hook.time.monotonic() - hook.DEADLINE - 1)
    with pytest.raises(TimeoutError):
        hook.http_json("GET", "https://example.test", {})


def test_the_process_exits_0_and_logs_when_nothing_is_set_up(tmp_path):
    """The real interpreter, not main(): HOME holds no credentials file."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in [prompt("PPA-1757"), TURN]))
    done = subprocess.run(
        [sys.executable, str(HOOK)], capture_output=True, text=True, timeout=30,
        input=json.dumps({"session_id": SESSION, "transcript_path": str(transcript)}),
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert (done.returncode, done.stdout) == (0, "")
    lines = (tmp_path / ".claude" / "pt-turn-worklog-hook.log").read_text().splitlines()
    _one_line(lines, turn_name=TAG, reason="FileNotFoundError")


def test_no_code_path_exits_with_code_2():
    """Exit 2 blocks the stop. Nothing in the source may produce it."""
    source = HOOK.read_text()
    assert not re.search(r"exit\s*\(\s*2\b|SystemExit\s*\(\s*2\b|exit\s+2\b|return\s+2\b", source)
    assert "os._exit" not in source
