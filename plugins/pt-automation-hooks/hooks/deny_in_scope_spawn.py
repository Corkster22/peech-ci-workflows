#!/usr/bin/env python3
"""PreToolUse hook (PPA-1566) - refuse a spawned ticket the session should fix.

The ladder for a finding is fix here, halt and ask, note and drop, ticket last
(pt-conduct-gates, Three Outcomes for a Finding). It was prose no mechanism
applied: 30 of the 54 tickets created for this repository in the seven days to
22-SEP-2026 carried the label ``spawned``. A close-out gate cannot fix that -
it reads the session's own prose after the branch has closed - so this fires
on the one observable moment, the ticket-creating tool call, while the branch
is still open.

One mechanical question
-----------------------
Does the ticket about to be created name a file the dispatched ticket already
permits editing? If so, outcome 1 applies and the create is denied with
``permissionDecision: deny``, the reason telling the session to fix it on its
branch. If that file is also named by one of the dispatched ticket's own
Definition of Done conditions, a fix could change what that condition
measures, which is the halt rung: the create is denied too, the reason
telling the session to stop and ask the conductor to rule while the context
is loaded. A deny, not ``continue: false``: only the deny cancels the call
(PPA-1637). The hook answers nothing else and judges no outcome it cannot
decide.

Two more rungs (PPA-1599)
-------------------------
PeechTech-Framework-CommitToDoneAutomation v0-0006, section 'Spawn control:
where halt and ask, and note and drop, fire'. Both run only where the fix-here
question above allowed the create, and neither changes that question.

* Note and drop. A create whose description carries no line beginning
  ``What breaks if not fixed:``, or whose line says nothing breaks, is denied.
  A finding that breaks nothing is dropped with a comment in the code, not
  ticketed. This one denies on an absence, and on purpose: the line is the
  evidence the ladder asks for, so a create without it has not reached rung 4.
* Halt and ask. The second ticket-creating call in one dispatched session
  is denied, naming the first ticket, and the reason tells the session to
  stop and ask the conductor to rule: fold the finding into it, fix it here,
  or open the second. It is a ``permissionDecision: deny``, not
  ``continue: false``: only the deny cancels the call, and ``continue: false``
  alone let PPA-1634 be created on 23-SEP-2026. The count is this hook's own
  ``allowed`` records for the session. The first ticket's key is read from
  Jira, because the create had not happened when its record was written. The
  halt fires once per session: a create after it is the conductor's answer.

Where each input comes from
---------------------------
* The dispatched keys: the dispatch line of the session's latest prompt that
  is a well-formed dispatch, read from the transcript with the dispatch hook's own
  ``dispatched_keys()``, plus the keys that hook cached as settled for this
  session. Both are the conductor's dispatch, never session-authored prose.
* The scope boundary: each dispatched ticket's ``description`` field, read
  live from Jira, and the ``edit:`` lines of its ``pt-files`` block. A ticket
  with no block has no boundary this hook can read.
* The conditions: the ticket's ``customfield_10767``, the Definition of Done.
* The file the new ticket concerns: any editable path named in the create
  payload's ``summary`` or ``description``.

It denies on evidence, never on absence
---------------------------------------
No dispatched key, a create outside PPA, a ticket with no ``pt-files`` block,
a payload naming no editable path: each passes the fix-here question
untouched, and only the note-and-drop rung above reads an absence. So does
every failure - an unreachable Jira, a malformed payload, a missing
credential. A failure is logged and the create is allowed, because a gate
that blocks on its own breakage stops legitimate work to report a bug in the
gate. Every outcome appends one JSON record to ``LOG``.

Who learns of a denial: Claude, through ``permissionDecisionReason``, which
Claude Code returns as the result of the refused tool call. A halt reaches
the operator through the session, which that reason tells to stop and ask.

The tool name
-------------
``mcp__atlassian-rovo__createJiraIssue``, read from the session's own tool
list on 22-SEP-2026. A matcher on a name that does not exist is a gate that
never fires and reports nothing, so the settings matcher and ``TOOL`` below
are the same string and a test holds them together.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Path resolution for the pt-automation-hooks plugin copy (PPA-1586). The
# pt_transition.py it reads credentials through resolves from the
# peech-ci-workflows clone, as in transition_on_prompt.py (PPA-1662). The
# docstring above still describes the peech-pmo-automation layout. PPA-1599
# then extended this copy alone, so it is the one to edit from here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_ci_workflows import CLONE_SCRIPTS  # noqa: E402
from transition_on_prompt import TICKET_PREFIXES  # noqa: E402

TOOL = "mcp__atlassian-rovo__createJiraIssue"
LOG = Path.home() / ".claude" / "pt-spawn-control-hook.log"
DOD_FIELD = "customfield_10767"
JIRA_TIMEOUT = 10

#: The line a create must carry to reach rung 4, and what the line said. Bold
#: and a list marker are allowed ahead of it, since the description is Markdown.
_BREAKS_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?What breaks if not fixed:(?:\*\*)?(.*)$",
    re.M | re.I)
#: A line that answers the question by saying nothing breaks.
_NOTHING_RE = re.compile(r"^\W*(?:nothing|none|n/?a)\b|^\W*$", re.I)

_BLOCK_RE = re.compile(
    r"<!--\s*pt-files:start\s*-->(.*?)<!--\s*pt-files:end\s*-->", re.S)
_EDIT_RE = re.compile(r"^\s*edit:\s*(\S+)", re.M)
#: The transcript records a pasted dispatch inside this wrapper, which puts a
#: tag line ahead of the dispatch line the parser reads first.
_PASTE_TAG_RE = re.compile(r"</?pasted_content[^>]*>")


def log(reason, **fields):
    """Append one JSON record, and never raise."""
    record = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "reason": reason, **fields}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _jira_get(path):
    """One authenticated GET, credentials from pt_transition as the dispatch
    hook takes them, so there is one credential home."""
    sys.path.insert(0, str(CLONE_SCRIPTS))
    from pt_transition import BASE, load_credentials  # noqa: PLC0415

    creds = load_credentials()
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=JIRA_TIMEOUT) as resp:
        return json.loads(resp.read())


def fetch_ticket(key):
    """The two fields the decision reads: the boundary and the conditions."""
    body = _jira_get(f"/issue/{key}?fields=description,{DOD_FIELD}")
    return body.get("fields") or {}


def flatten(node):
    """Every text leaf of an ADF node, joined, or the value itself if it is
    already a string."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        text = node.get("text", "")
        return text + "\n".join(flatten(c) for c in node.get("content", []))
    if isinstance(node, list):
        return "\n".join(flatten(c) for c in node)
    return ""


def editable_paths(description):
    """The ``edit:`` paths of the ticket's pt-files block, with any trailing
    annotation such as ``(new)`` dropped. Empty when there is no block."""
    block = _BLOCK_RE.search(flatten(description))
    return _EDIT_RE.findall(block.group(1)) if block else []


def _hook_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import transition_on_prompt  # noqa: PLC0415

    return transition_on_prompt


def _user_texts(transcript_path):
    for line in Path(transcript_path).read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "user":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            yield "\n".join(part.get("text", "") for part in content
                            if isinstance(part, dict)
                            and part.get("type") == "text")


def dispatched_keys(payload):
    """The session's dispatched PPA keys, from the conductor's dispatch line
    and the dispatch hook's settled cache. Never from session output."""
    hook = _hook_module()
    keys: list[str] = []
    if payload.get("transcript_path"):
        # PPA-1720: the latest dispatch wins, not the first. A malformed prompt
        # never stopped this loop - it reads as no keys and is skipped - but the
        # first well-formed one did, so a dispatch corrected later in the
        # session was scoped to the set it superseded.
        for text in _user_texts(payload["transcript_path"]):
            found = hook.dispatched_keys(_PASTE_TAG_RE.sub("", text).strip())
            if found:
                keys = [k.upper() for k in found]
    cached = hook.already_settled(hook.cache_path(payload.get("session_id")))
    return sorted(set(keys) | {k.upper() for k in cached})


def decide(tool_input, tickets):
    """The decision alone, from already-fetched tickets.

    Returns None to allow, or the hook output to print. ``tickets`` maps each
    dispatched key to its fields.
    """
    subject = f"{tool_input.get('summary', '')}\n" \
              f"{flatten(tool_input.get('description', ''))}"
    for key, fields in sorted(tickets.items()):
        conditions = flatten(fields.get(DOD_FIELD) or "")
        for path in editable_paths(fields.get("description")):
            if path not in subject:
                continue
            if path in conditions:
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Spawn control (PPA-1566): the ticket being created "
                        f"names {path}, which {key} permits editing and whose "
                        f"Definition of Done names it too. A fix there could "
                        f"change what {key}'s own conditions measure, so this "
                        f"is the halt rung. Do not create the ticket and do "
                        f"not make the fix: stop and ask the conductor to rule "
                        f"- amend the condition, accept the fix, or confirm "
                        f"the deferral - and act on that ruling.")}}
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Spawn control (PPA-1566): {path} is inside {key}'s scope "
                    f"boundary - its pt-files block lists it as edit. That is "
                    f"outcome 1, fix it here: make the fix on this branch in a "
                    f"separate commit whose subject starts 'adjacent:' and "
                    f"carries {key}, with the reproduction before and after. "
                    f"Do not open a ticket for it.")}}
    return None


def breakage_denial(tool_input):
    """None where the create names what breaks, or the deny to print.

    The first ``What breaks if not fixed:`` line decides. No line, or one that
    says nothing breaks, is a finding for rung 3 - note and drop.
    """
    line = _BREAKS_RE.search(flatten(tool_input.get("description", "")))
    if line and not _NOTHING_RE.search(line.group(1)):
        return None
    said = "carries no line beginning 'What breaks if not fixed:'" if not line \
        else f"says nothing breaks ('{line.group(0).strip()}')"
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Spawn control (PPA-1599): this ticket's description {said}. A "
            f"finding that breaks nothing is not ticketed: drop it with a "
            f"comment in the code where it lives, and name in that comment and "
            f"in the close-out what would break if it is never fixed. If "
            f"something does break, add the line 'What breaks if not fixed: "
            f"<the consequence>' to the description and create it again.")}}


def session_records(session_id):
    """This session's records from ``LOG``, oldest first. Raises where the log
    exists and cannot be read; the caller allows and logs."""
    if not LOG.exists():
        return []
    records = []
    for line in LOG.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("session_id") == session_id:
            records.append(record)
    return records


def created_key(summary, since):
    """The key of the PPA ticket created with this summary on or after the
    day before ``since``, or None. A day's slack, because Jira reads the date
    in the account's timezone and the log writes local time."""
    day = (datetime.fromisoformat(since) - timedelta(days=1)).date().isoformat()
    jql = f'project = PPA AND created >= "{day}" ORDER BY created ASC'
    body = _jira_get(f"/search/jql?jql={urllib.parse.quote(jql)}"
                     f"&fields=summary&maxResults=100")
    for issue in body.get("issues") or []:
        if (issue.get("fields") or {}).get("summary") == summary:
            return issue.get("key")
    return None


def second_create_halt(session_id):
    """None, or the halt for the second create this dispatched session makes.

    Fires once: a create after the halt is the conductor's ruling acted on.
    """
    records = session_records(session_id)
    allowed = [r for r in records if r.get("reason") == "allowed"]
    if not allowed or any(r.get("reason") == "second-create" for r in records):
        return None
    first = allowed[0]
    key = created_key(first.get("summary"), first["at"])
    named = f"{key} ('{first.get('summary')}')" if key else (
        f"the one created as '{first.get('summary')}', whose key Jira did not "
        f"return")
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Spawn control (PPA-1599): this is the second ticket this "
            f"dispatched session is opening. The first was {named}. Do not "
            f"create it yet: stop and ask the conductor to rule on this "
            f"finding - fold this finding into that ticket, fix it here, or "
            f"open the second ticket - and act on that ruling.")}}


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as exc:
        log("unreadable-payload", error=repr(exc))
        return 0
    try:
        if payload.get("tool_name") != TOOL:
            log("other-tool", tool=payload.get("tool_name"))
            return 0
        tool_input = payload.get("tool_input") or {}
        if str(tool_input.get("projectKey", "")).upper() not in TICKET_PREFIXES:
            log("not-ppa", project=tool_input.get("projectKey"))
            return 0
        keys = dispatched_keys(payload)
        if not keys:
            log("no-dispatch")
            return 0
        session = payload.get("session_id")
        tickets = {key: fetch_ticket(key) for key in keys}
        output, reason = decide(tool_input, tickets), None
        if output is None:
            output, reason = breakage_denial(tool_input), "no-breakage"
        if output is None and session:
            output, reason = second_create_halt(session), "second-create"
    except Exception as exc:  # noqa: BLE001 - every failure allows, logged
        log("hook-failed", error=repr(exc))
        return 0
    if output is None:
        log("allowed", keys=keys, summary=tool_input.get("summary"),
            session_id=session)
        return 0
    halt = "halt rung" in output["hookSpecificOutput"]["permissionDecisionReason"]
    log(reason or ("halted" if halt else "denied"),
        keys=keys, summary=tool_input.get("summary"), output=output,
        session_id=session)
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
