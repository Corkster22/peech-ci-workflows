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

    def __init__(self, *, account=hook.SEAN, existing=(), by_issue=None, fail=None,
                 fail_post=None, missing=None):
        """``existing`` descriptions sit on every issue, ``by_issue`` on one."""
        self.account, self.existing, self.fail = account, list(existing), fail
        self.by_issue, self.fail_post, self.missing = by_issue or {}, fail_post, missing
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if self.fail or (self.fail_post and method == "POST"):
            raise self.fail or self.fail_post
        if url.endswith("/myself"):
            return {"accountId": self.account}
        tempo = re.search(r"/worklogs/issue/(\d+)", url)
        if tempo:
            found = self.existing + self.by_issue.get(int(tempo.group(1)), [])
            return {"results": [{"description": d} for d in found], "metadata": {}}
        if self.missing and f"/issue/{self.missing}?" in url:
            raise RuntimeError(f"GET {url} -> HTTP 404")
        if "/issue/" in url:
            return {"id": str(45000 + int(re.search(r"-(\d+)\?", url).group(1)))}
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


def test_every_turn_duration_row_is_a_turn_with_the_keys_in_force(tmp_path):
    path = tmp_path / "t.jsonl"
    older = turn(uuid="older", durationMs=1000)
    path.write_text("\n".join(json.dumps(r) for r in
                              [prompt("PPA-1"), older, prompt("hi"), TURN]))
    assert [(row["uuid"], keys) for row, keys in hook.turns(path)] == [
        ("older", ["PPA-1"]), (TURN_UUID, ["PPA-1"])]


def test_a_transcript_with_no_turn_duration_row_has_no_turn(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in
                              [prompt("PPA-1"), {"type": "assistant"}]))
    assert hook.turns(path) == []


def test_unparseable_lines_and_non_object_rows_are_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(["not json", "[1]", json.dumps(prompt("PPA-1")),
                               json.dumps(TURN)]))
    assert hook.turns(path)[0][1] == ["PPA-1"]


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


# Amendment 1 (01-OCT-2026, corrected 12:54 ET to match PPA-1756's a069ce3e):
# a key line may carry a note after a dash or a colon, and only those. Found
# by the PPA-1756 dry run, session 5f321b58, which opened with
# "PEECHPMO-491 - includes Amendment 1, comment 30603" and lost 1.2 h.


@pytest.mark.parametrize("text, keys", [
    ("PEECHPMO-491 - includes Amendment 1, comment 30603", ["PEECHPMO-491"]),
    ("PPA-1757 - log turns", ["PPA-1757"]),
    ("PPA-1, PPA-2 - both", ["PPA-1", "PPA-2"]),
    ("PPA-1 PPA-2 - both", ["PPA-1", "PPA-2"]),
    ("PPA-1 - see PPA-9", ["PPA-1"]),
    ("Execute PPA-1757 - the amendment", ["PPA-1757"]),
])
def test_a_key_dash_note_line_is_a_dispatch(text, keys):
    assert hook.dispatch_keys(text) == keys


@pytest.mark.parametrize("text, keys", [
    ("PEECHPMO-491: includes Amendment 1, comment 30603", ["PEECHPMO-491"]),
    ("PPA-1757: log turns", ["PPA-1757"]),
    ("PPA-1 : spaced colon", ["PPA-1"]),
    ("PPA-1, PPA-2: both", ["PPA-1", "PPA-2"]),
])
def test_a_key_colon_note_line_is_a_dispatch(text, keys):
    assert hook.dispatch_keys(text) == keys


@pytest.mark.parametrize("text", [
    "PPA-1700 is failing, why?",
    "PPA-1, PPA-2 is failing",
    "PPA-1700 why",
    "PPA-1289. Fetch the ticket for the spec.",
    "Please look at PEECHPMO-491 - it fails",
    "Some prose\nPEECHPMO-491 - note on a later line",
    # A comma is not a note separator (the 12:54 ET correction).
    "PPA-1757, run the fix",
    "PPA-1757, PPA-1756, why is this failing?",
])
def test_a_key_followed_by_a_word_is_not_a_dispatch(text):
    assert hook.dispatch_keys(text) == []


def test_a_key_dash_note_dispatch_posts_on_its_key(run):
    """End to end: the session-5f321b58 opening line now maps its turn."""
    _, router, _ = run([prompt("PEECHPMO-491 - includes Amendment 1, comment 30603"), TURN])
    assert [p["issueId"] for p in router.posts] == [45491]


def test_a_prose_line_naming_a_key_posts_nothing(run):
    code, router, lines = run([prompt("PPA-1700 is failing, why?"), TURN])
    assert (code, router.calls, lines) == (0, [], [])


def test_the_latest_dispatch_holds_until_the_next(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [prompt("PPA-1"), turn(uuid="a"), prompt("a question about PPA-9"),
            turn(uuid="b"), prompt("Execute PPA-2."), TURN]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert [keys for _, keys in hook.turns(path)] == [["PPA-1"], ["PPA-1"], ["PPA-2"]]


def test_tool_results_and_meta_rows_are_not_dispatches(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [prompt("PPA-1"),
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "PPA-7"}]}},
            {"type": "user", "isMeta": True, "message": {"content": "PPA-8"}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "PPA-3"}]}},
            TURN]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert hook.turns(path)[0][1] == ["PPA-3"]


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
    _, router, _ = run([prompt("PPA-1, PPA-2, PPA-3"), turn(durationMs=310000)])
    assert [(p["issueId"], p["timeSpentSeconds"]) for p in router.posts] == [
        (45001, 104), (45002, 103), (45003, 103)]
    assert {p["description"] for p in router.posts} == {TAG}


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
    poster = hook.Poster({"JIRA_EMAIL": "e", "JIRA_API_TOKEN": "j", "TEMPO_FM_OAUTH_TOKEN": "t"})
    assert poster.posted(45001, TAG) is True
    assert seen[1] == "https://api.tempo.io/next"


def test_anyone_but_sean_posts_nothing_and_logs_nothing(run):
    code, router, lines = run([prompt("PPA-1757"), TURN],
                              router=Router(account="712020:someone-else"))
    assert (code, router.posts, lines) == (0, [], [])
    assert [c[1] for c in router.calls] == ["https://peech-team.atlassian.net/rest/api/3/myself"]


# --- rows that land after Stop (PPA-1757 finding 1) -------------------------
#
# Read off real transcripts on 01-OCT-2026: the turn_duration row is written
# about 3 ms after the turn's last stop_hook_summary, so the ending turn's row
# is never there when its own Stop hook runs. The hook posts every row it finds.


def _rows(uuid, end, ms=60000):
    return turn(uuid=uuid, timestamp=end, durationMs=ms)


A = _rows("a", "2026-09-30T14:00:00.000Z")
B = _rows("b", "2026-09-30T15:00:00.000Z")


def test_a_lagging_row_is_posted_at_the_next_stop(run):
    """Stop for turn C: C's row is not written yet, A's and B's are."""
    _, router, _ = run([prompt("PPA-1"), A, prompt("go"), B, prompt("again")])
    assert [p["description"] for p in router.posts] == [
        f"cc-turn:{SESSION}:a", f"cc-turn:{SESSION}:b"]


def test_only_rows_not_yet_in_tempo_are_posted(run):
    router = Router(existing=[f"cc-turn:{SESSION}:a"])
    _, router, _ = run([prompt("PPA-1"), A, B], router=router)
    assert [p["description"] for p in router.posts] == [f"cc-turn:{SESSION}:b"]


def test_a_run_with_everything_posted_makes_no_post(run):
    router = Router(existing=[f"cc-turn:{SESSION}:a", f"cc-turn:{SESSION}:b"])
    code, router, lines = run([prompt("PPA-1"), A, B], router=router)
    assert (code, router.posts, lines) == (0, [], [])


def test_tempo_is_read_once_per_issue_not_per_user_or_date(run):
    _, router, _ = run([prompt("PPA-1"), A, B])
    reads = [c[1] for c in router.calls if c[0] == "GET" and "tempo.io" in c[1]]
    assert reads == ["https://api.tempo.io/4/worklogs/issue/45001?limit=1000"]


def test_a_row_ending_before_the_cutoff_never_posts(run):
    """The untagged 23-SEP backfill covers everything before 24-SEP 00:00 ET."""
    before = _rows("before", "2026-09-24T03:59:59.000Z")
    at = _rows("at", "2026-09-24T04:00:00.000Z")
    _, router, _ = run([prompt("PPA-1"), before, at])
    assert [p["description"] for p in router.posts] == [f"cc-turn:{SESSION}:at"]


def test_a_lone_row_before_the_cutoff_posts_nothing(run):
    code, router, lines = run([prompt("PPA-1"), _rows("old", "2026-09-23T23:00:00.000Z")])
    assert (code, router.posts, lines) == (0, [], [])


def test_the_cutoff_is_midnight_eastern_on_24_sep():
    assert hook.CUTOFF.isoformat() == "2026-09-24T00:00:00-04:00"


def test_one_turn_that_cannot_post_does_not_block_the_rows_after_it(run):
    rows = [prompt("PPA-2"), A, prompt("PPA-3"), B]
    code, router, lines = run(rows, router=Router(missing="PPA-2"))
    assert code == 0
    assert [(p["issueId"], p["description"]) for p in router.posts] == [
        (45003, f"cc-turn:{SESSION}:b")]
    _one_line(lines, turn_name=f"cc-turn:{SESSION}:a", reason="HTTP 404")


def test_a_network_failure_stops_the_run_with_one_log_line(run):
    router = Router(fail_post=TimeoutError("timed out"))
    code, router, lines = run([prompt("PPA-1"), A, B], router=router)
    assert code == 0 and len(router.posts) == 1
    _one_line(lines, turn_name=f"cc-turn:{SESSION}:a", reason="TimeoutError")


# --- Amendments 2 and 3: Tempo's one-minute floor ---------------------------
#
# Found live by PPA-1756 on 01-OCT-2026: Tempo rejects any worklog under 60 s
# with HTTP 400 "Duration must be at least one minute". Amendment 3 (Decision
# 1B) rounds a part under a minute up to exactly 60 s, posts a longer part at
# its real length, and holds and bundles nothing. The per-tag, per-issue posted
# check of Amendment 2 stays.


def secs(uuid, seconds, end="2026-09-30T14:00:00.000Z"):
    return turn(uuid=uuid, durationMs=seconds * 1000, timestamp=end)


@pytest.mark.parametrize("real, posted", [
    (1, 60), (30, 60), (59, 60), (60, 60), (61, 61), (120, 120), (485, 485)])
def test_a_part_under_a_minute_posts_sixty_seconds_and_a_longer_one_its_real_length(
        run, real, posted):
    code, router, lines = run([prompt("PPA-1"), secs("a", real)])
    assert (code, lines) == (0, [])
    assert [p["timeSpentSeconds"] for p in router.posts] == [posted]


def test_a_multi_key_turn_with_parts_under_a_minute_posts_sixty_seconds_per_key(run):
    """100 s over three keys is 34, 33 and 33."""
    _, router, _ = run([prompt("PPA-1, PPA-2, PPA-3"), secs("a", 100)])
    assert [(p["issueId"], p["timeSpentSeconds"]) for p in router.posts] == [
        (45001, 60), (45002, 60), (45003, 60)]


def test_a_multi_key_turn_with_parts_over_a_minute_posts_their_real_lengths(run):
    """150 s over two keys is 75 and 75."""
    _, router, _ = run([prompt("PPA-1, PPA-2"), secs("a", 150)])
    assert [p["timeSpentSeconds"] for p in router.posts] == [75, 75]


def test_a_zero_second_part_posts_nothing(run):
    """2 s over three keys is 2, 0 and 0. A zero part would overstate by 60 s,
    past the 59 s Decision 1B allows, so only the first key posts."""
    _, router, _ = run([prompt("PPA-1, PPA-2, PPA-3"), secs("a", 2)])
    assert [(p["issueId"], p["timeSpentSeconds"]) for p in router.posts] == [(45001, 60)]


def test_a_turn_that_rounds_to_zero_seconds_posts_nothing(run):
    code, router, lines = run([prompt("PPA-1"), turn(durationMs=400)])
    assert (code, router.posts, lines) == (0, [], [])


def test_every_slice_posts_on_its_own_and_nothing_is_held_or_bundled(run):
    """Four short turns on one key: four worklogs of 60 s, one tag each, so no
    slice waits for a later Stop and no worklog carries several turns."""
    rows = [prompt("PPA-1")] + [secs(u, 20) for u in "abcd"]
    _, router, _ = run(rows)
    assert [(p["timeSpentSeconds"], p["description"]) for p in router.posts] == [
        (60, f"cc-turn:{SESSION}:{u}") for u in "abcd"]


def test_a_later_stop_posts_only_the_slices_not_yet_in_tempo(run):
    router = Router(existing=[f"cc-turn:{SESSION}:a"])
    _, router, _ = run([prompt("PPA-1"), secs("a", 20), secs("b", 20)], router=router)
    assert [p["description"] for p in router.posts] == [f"cc-turn:{SESSION}:b"]


def test_no_post_is_under_a_minute_or_overstates_a_part_by_more_than_59_seconds(run):
    """Two keys over mixed turns: each post is max(part, 60), its tag is on
    the issue once, and it overstates its part by at most 59 seconds."""
    durations = [95, 10, 61, 7, 200, 3, 59, 1, 121]
    rows = [prompt("PPA-1, PPA-2")] + [secs(f"u{i}", d) for i, d in enumerate(durations)]
    _, router, _ = run(rows)
    for index, issue in enumerate((45001, 45002)):
        parts = [x for x in (hook.split_seconds(d, 2)[index] for d in durations) if x > 0]
        mine = [p for p in router.posts if p["issueId"] == issue]
        assert len(mine) == len(parts)
        for post, part in zip(mine, parts):
            assert post["timeSpentSeconds"] == max(part, 60)
            assert post["timeSpentSeconds"] - part <= 59
        tags = [p["description"] for p in mine]
        assert len(tags) == len(set(tags)) and all(" " not in t for t in tags)


def test_a_posted_check_is_per_tag_and_per_issue(run):
    """A two-key turn posted for PPA-1 only is finished for PPA-2."""
    router = Router(by_issue={45001: [TAG]})
    _, router, _ = run([prompt("PPA-1, PPA-2"), TURN], router=router)
    assert [(p["issueId"], p["timeSpentSeconds"], p["description"])
            for p in router.posts] == [(45002, 243, TAG)]


def test_a_tag_on_another_issue_does_not_count_as_posted(run):
    router = Router(by_issue={45002: [TAG]})
    _, router, _ = run([prompt("PPA-1, PPA-2"), TURN], router=router)
    assert [p["issueId"] for p in router.posts] == [45001]


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


def test_a_key_jira_cannot_resolve_does_not_stop_the_other_keys(run):
    code, router, lines = run([prompt("PPA-1, PPA-2"), TURN], router=Router(missing="PPA-2"))
    assert code == 0
    assert [(p["issueId"], p["timeSpentSeconds"]) for p in router.posts] == [(45001, 243)]
    _one_line(lines, turn_name=TAG, reason="HTTP 404")


@pytest.mark.parametrize("payload", ["", "not json", "{}", '{"session_id": "s"}'])
def test_an_unreadable_hook_input_exits_0_with_one_log_line(run, payload):
    code, router, lines = run([], payload=payload)
    assert (code, router.calls) == (0, [])
    assert len(lines) == 1


@pytest.mark.parametrize("drop", ["timestamp", "uuid"])
def test_a_row_it_cannot_time_or_tag_is_skipped_not_a_failure(run, drop):
    """A row that stays malformed would log at every Stop and block the rows
    after it, so it is skipped."""
    bad = {k: v for k, v in TURN.items() if k != drop}
    code, router, lines = run([prompt("PPA-1757"), bad])
    assert (code, router.calls, lines) == (0, [], [])


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
