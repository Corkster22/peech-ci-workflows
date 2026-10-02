"""label_spawned_ticket.py - the PostToolUse spawned-label hook (PPA-1597).

Each case drives main() end to end: a PostToolUse payload on stdin, a
transcript on disk carrying the dispatch line, and the Jira write replaced by
a recorder, so no case reaches Jira. What was written is read off the recorder.
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "label_spawned_ticket.py"


def _load():
    spec = importlib.util.spec_from_file_location("label_spawned_ticket", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

#: The MCP tool's response shape: the created issue as JSON text in a content
#: block. The key sits beside a self link and the issue id.
RESPONSE = [{"type": "text", "text": json.dumps({
    "id": "45400", "key": "PPA-1700",
    "self": "https://api.atlassian.com/ex/jira/x/rest/api/3/issue/45400"})}]


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Drive main() and return (writes, stdout payload, log records)."""
    log = tmp_path / "hook.log"
    monkeypatch.setattr(hook, "LOG", log)
    transcript = tmp_path / "t.jsonl"
    writes = []

    def go(*, dispatch="PPA-1597, PPA-1599", project="PPA", summary="A finding",
           description="", response=RESPONSE, tool=hook.TOOL, write=None):
        prompts = [dispatch] if isinstance(dispatch, str) else dispatch
        transcript.write_text("\n".join(json.dumps({"type": "user", "message": {
            "role": "user",
            "content": f'<pasted_content id="x">\n{text}\n</pasted_content>'}})
            for text in prompts))
        monkeypatch.setattr(hook, "jira_write", write or (
            lambda method, path, body: writes.append((method, path, body))))
        payload = {"session_id": "test-no-cache", "transcript_path": str(transcript),
                   "hook_event_name": "PostToolUse", "tool_name": tool,
                   "tool_input": {"projectKey": project, "summary": summary,
                                  "description": description},
                   "tool_response": response}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        assert hook.main() == 0
        printed = json.loads(out.getvalue()) if out.getvalue() else None
        records = [json.loads(line) for line in log.read_text().splitlines()]
        return writes, printed, records

    return go


def test_a_dispatched_create_is_labelled_and_linked(run):
    writes, printed, records = run()

    assert writes[0] == ("PUT", "/issue/PPA-1700",
                         {"update": {"labels": [{"add": "spawned"}]}})
    assert writes[1:] == [
        ("POST", "/issueLink", {"type": {"name": "Relates"},
                                "inwardIssue": {"key": key},
                                "outwardIssue": {"key": "PPA-1700"}})
        for key in ("PPA-1597", "PPA-1599")]
    assert printed is None
    assert records[-1]["reason"] == "labelled"


def test_the_link_goes_to_the_dispatched_key_the_payload_names(run):
    writes, _, _ = run(description="Surfaced while building PPA-1599's halt.")

    assert [w[2]["inwardIssue"]["key"] for w in writes[1:]] == ["PPA-1599"]


def test_the_link_goes_to_the_latest_dispatch_not_the_first(run):
    """PPA-1720. This hook takes its keys from deny_in_scope_spawn's finder, so
    the two agree on the session's dispatch - and both follow the latest."""
    writes, _, _ = run(dispatch=["PPA-1597", "Run batch 02 \u2014 set: PPA-1598",
                                 "PPA-1599"])

    assert [w[2]["inwardIssue"]["key"] for w in writes[1:]] == ["PPA-1599"]


def test_a_create_with_no_dispatch_writes_nothing(run):
    writes, printed, records = run(dispatch="just a question, no key")

    assert writes == []
    assert printed is None
    assert records[-1]["reason"] == "no-dispatch"


def test_a_create_outside_ppa_writes_nothing(run):
    writes, _, records = run(project="AISD2026")

    assert writes == []
    assert records[-1]["reason"] == "not-ppa"


def test_a_response_naming_no_key_writes_nothing(run):
    writes, _, records = run(response=[{"type": "text", "text": "error: denied"}])

    assert writes == []
    assert records[-1]["reason"] == "no-key"


def test_a_jira_failure_does_not_fail_the_tool_call(run):
    def unreachable(method, path, body):
        raise OSError("Jira unreachable")

    writes, printed, records = run(write=unreachable)

    assert writes == []
    assert "PPA-1700 was created" in printed["systemMessage"]
    assert "Apply them by hand" in printed["systemMessage"]
    assert records[-1]["reason"] == "hook-failed"
    assert "Jira unreachable" in records[-1]["error"]


def test_a_malformed_payload_exits_zero_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "LOG", tmp_path / "hook.log")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

    assert hook.main() == 0
    assert json.loads((tmp_path / "hook.log").read_text())["reason"] == \
        "unreadable-payload"


@pytest.mark.parametrize("response", [
    RESPONSE,
    {"key": "PPA-1700", "fields": {"summary": "x"}},
    "Created https://peech-team.atlassian.net/browse/PPA-1700",
])
def test_the_key_is_read_from_each_response_shape(response):
    assert hook.created_key(response) == "PPA-1700"


def test_the_hooks_json_matcher_is_the_tool_the_hook_checks():
    config = json.loads((HOOK.parent / "hooks.json").read_text())
    matchers = [block["matcher"] for block in config["hooks"]["PostToolUse"]
                if any(HOOK.name in h["command"] for h in block["hooks"])]
    assert matchers == [hook.TOOL]


def test_a_dispatched_peechpmo_create_is_labelled_and_linked(run):
    """PPA-1825. No label or link was written for a PEECHPMO spawn."""
    response = [{"type": "text", "text": json.dumps({
        "id": "45401", "key": "PEECHPMO-700",
        "self": "https://api.atlassian.com/ex/jira/x/rest/api/3/issue/45401"})}]

    writes, _, records = run(dispatch="PEECHPMO-507", project="PEECHPMO",
                             response=response)

    assert writes == [
        ("PUT", "/issue/PEECHPMO-700",
         {"update": {"labels": [{"add": "spawned"}]}}),
        ("POST", "/issueLink", {"type": {"name": "Relates"},
                                "inwardIssue": {"key": "PEECHPMO-507"},
                                "outwardIssue": {"key": "PEECHPMO-700"}})]
    assert records[-1]["reason"] == "labelled"
