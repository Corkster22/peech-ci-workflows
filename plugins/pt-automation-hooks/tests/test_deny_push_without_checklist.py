"""deny_push_without_checklist.py - the ticket-branch push guard (PPA-1626).

Each test drives ``decide()`` against a real git repository in tmp_path and a
transcript on disk, with Jira stubbed: the branch name and the head commit are
read from git as a session's push would read them, and no test reaches Jira.
"""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
HOOK = PLUGIN / "hooks" / "deny_push_without_checklist.py"


def _load():
    spec = importlib.util.spec_from_file_location("deny_push_without_checklist", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()


def comment(text):
    """One Jira comment as the v3 API returns it, its body in ADF."""
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}}


CHECKLIST = comment("1. The hook denies a push with no checklist - MET")
PROSE = comment("Pushed the branch; every condition is met.")


def jira(comments_by_key):
    calls = []

    def get(path, timeout):
        calls.append((path, timeout))
        key = re.match(r"/issue/([A-Z]+-\d+)/comment", path).group(1)
        return {"comments": comments_by_key.get(key, [])}

    get.calls = calls
    return get


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: the work (PPA-1)")
    git(tmp_path, "checkout", "-q", "-b", "ppa-1-guard")
    return tmp_path


def payload(repo, command="git push -u origin HEAD", dispatch="PPA-1, PPA-2"):
    transcript = repo / "transcript.jsonl"
    transcript.write_text(json.dumps(
        {"type": "user", "message": {"content": dispatch}}) + "\n")
    return {"tool_name": "Bash", "cwd": str(repo),
            "transcript_path": str(transcript),
            "tool_input": {"command": command}}


def denial(output):
    """The PreToolUse decision, or {} - so a missing deny fails an assertion
    on its value rather than raising on None."""
    return (output or {}).get("hookSpecificOutput") or {}


def test_denies_a_ppa_push_with_no_checklist(repo):
    get = jira({"PPA-1": [CHECKLIST], "PPA-2": [PROSE]})
    decision = denial(hook.decide(payload(repo), get))
    assert decision.get("permissionDecision") == "deny"
    reason = decision["permissionDecisionReason"]
    assert "PPA-2 carries no close-out checklist" in reason
    assert "PPA-1," not in reason
    assert "| 1 | <the condition text, quoted> | MET |" in reason
    assert "1. <the condition text, quoted> - MET" in reason


def test_allows_a_ppa_push_once_every_key_has_a_checklist(repo):
    get = jira({"PPA-1": [PROSE, CHECKLIST], "PPA-2": [CHECKLIST]})
    assert hook.decide(payload(repo), get) is None
    assert len(get.calls) == 2


def test_a_malformed_first_prompt_is_checked_against_the_later_dispatch(repo):
    """PPA-1720. session_keys stopped at a malformed first prompt, so this
    guard saw no keys and let the push through unchecked."""
    call = payload(repo)
    Path(call["transcript_path"]).write_text("\n".join(json.dumps(
        {"type": "user", "message": {"content": text}})
        for text in ("Run batch 01 \u2014 set: PPA-1", "PPA-2")) + "\n")
    get = jira({"PPA-1": [CHECKLIST], "PPA-2": [PROSE]})

    decision = denial(hook.decide(call, get))

    assert decision.get("permissionDecision") == "deny"
    assert "PPA-2 carries no close-out checklist" in decision[
        "permissionDecisionReason"]
    assert [path.split("/")[2] for path, _ in get.calls] == ["PPA-2"]


def test_a_superseded_dispatch_is_not_the_set_checked(repo):
    call = payload(repo)
    Path(call["transcript_path"]).write_text("\n".join(json.dumps(
        {"type": "user", "message": {"content": text}})
        for text in ("PPA-1", "PPA-2")) + "\n")
    get = jira({"PPA-1": [PROSE], "PPA-2": [CHECKLIST]})

    assert hook.decide(call, get) is None
    assert [path.split("/")[2] for path, _ in get.calls] == ["PPA-2"]


def test_allows_a_non_ppa_branch_without_reading_jira(repo):
    git(repo, "checkout", "-q", "main")
    get = jira({})
    assert hook.decide(payload(repo, "git push origin main"), get) is None
    assert get.calls == []


def test_allows_a_work_in_progress_push_without_reading_jira(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "wip: halfway - pausing session")
    get = jira({})
    assert hook.decide(payload(repo), get) is None
    assert get.calls == []


def test_allows_and_warns_when_jira_fails(repo):
    def get(path, timeout):
        raise TimeoutError("timed out")

    output = hook.decide(payload(repo), get)
    assert "hookSpecificOutput" not in output
    assert "reading Jira comments failed" in output["systemMessage"]
    assert "TimeoutError" in output["systemMessage"]


def test_an_explicit_ppa_refspec_is_checked_from_another_branch(repo):
    git(repo, "checkout", "-q", "main")
    output = hook.decide(payload(repo, "git push origin main:ppa-1-guard"), jira({}))
    assert denial(output).get("permissionDecision") == "deny"


@pytest.mark.parametrize("command", [
    "git status", "git commit -m 'push the fix'", "echo git push"])
def test_a_command_running_no_push_is_not_checked(repo, command):
    get = jira({})
    assert hook.decide(payload(repo, command), get) is None
    assert get.calls == []


def test_the_jira_reads_stop_inside_the_hook_timeout():
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    timeout = next(h["timeout"] for block in config["hooks"]["PreToolUse"]
                   for h in block["hooks"] if HOOK.name in h["command"])
    assert hook.JIRA_TIMEOUT <= hook.BUDGET < timeout
