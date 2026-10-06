"""delete_merged_branches.py - the SessionStart hook that deletes merged branches
(PPA-1872).

Each case runs main() against a real temporary git repository standing in for one
of the four Peech repositories. Only ``gh`` is stubbed: a script on PATH that
answers each branch from a table, so no case reaches GitHub.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path.insert(0, str(HOOKS))
import delete_merged_branches as hook  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "Claude-Projects"
    repo = root / "peech-skills"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    stub = tmp_path / "bin"
    stub.mkdir()
    answers = tmp_path / "answers.json"
    answers.write_text("{}")
    gh = stub / "gh"
    gh.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv
answers = json.load(open({str(answers)!r}))
branch = a[a.index("--head") + 1]
if answers.get("__fail__"):
    sys.exit(1)
print(json.dumps([{{"state": s}} for s in answers.get(branch, [])]))
""")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(hook, "ROOT", root)
    monkeypatch.setattr(hook, "LOG", tmp_path / "logs" / "cleanup.log")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo)})))

    class Env:
        pass
    e = Env()
    e.repo, e.root, e.answers, e.log = repo, root, answers, tmp_path / "logs" / "cleanup.log"
    e.branch = lambda name: git(repo, "branch", name)
    e.say = lambda table: answers.write_text(json.dumps(table))
    e.names = lambda: set(git(repo, "branch", "--format=%(refname:short)").split())
    return e


def test_a_branch_whose_pull_requests_all_merged_is_deleted(env):
    env.branch("done")
    env.branch("twice")
    env.say({"done": ["MERGED"], "twice": ["MERGED", "MERGED"]})
    assert hook.main() == 0
    assert env.names() == {"main"}


def test_a_branch_with_an_open_pull_request_is_kept(env):
    env.branch("open")
    env.say({"open": ["OPEN"]})
    hook.main()
    assert "open" in env.names()


def test_a_branch_with_a_closed_unmerged_pull_request_is_kept(env):
    env.branch("closed")
    env.say({"closed": ["CLOSED"]})
    hook.main()
    assert "closed" in env.names()


def test_a_branch_with_one_merged_and_one_open_pull_request_is_kept(env):
    env.branch("mixed")
    env.say({"mixed": ["MERGED", "OPEN"]})
    hook.main()
    assert "mixed" in env.names()


def test_a_branch_with_no_pull_request_is_kept_on_an_empty_gh_result(env):
    """An empty `gh pr list` is no evidence of a merge, so the branch stays."""
    env.branch("never-pushed")
    env.say({})
    hook.main()
    assert "never-pushed" in env.names()


def test_main_and_the_checked_out_branch_are_kept_even_when_merged(env):
    git(env.repo, "checkout", "-q", "-b", "current")
    env.say({"main": ["MERGED"], "current": ["MERGED"]})
    hook.main()
    assert env.names() == {"main", "current"}


def test_a_branch_held_by_another_worktree_is_kept(env, tmp_path):
    env.branch("held")
    git(env.repo, "worktree", "add", "-q", str(tmp_path / "wt"), "held")
    env.say({"held": ["MERGED"]})
    hook.main()
    assert "held" in env.names()


def test_a_github_failure_keeps_every_branch_and_exits_zero(env):
    env.branch("a")
    env.say({"__fail__": True})
    assert hook.main() == 0
    assert "a" in env.names()


def test_a_folder_outside_the_four_repositories_is_left_alone(env, tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    git(other, "commit", "-q", "--allow-empty", "-m", "base")
    git(other, "branch", "done")
    env.say({"done": ["MERGED"]})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(other)})))
    assert hook.main() == 0
    assert "done" in set(git(other, "branch", "--format=%(refname:short)").split())


def test_a_subfolder_of_a_peech_repository_still_acts(env, monkeypatch):
    env.branch("done")
    sub = env.repo / "scripts"
    sub.mkdir()
    env.say({"done": ["MERGED"]})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(sub)})))
    hook.main()
    assert "done" not in env.names()


def test_nothing_is_written_to_standard_output(env, capsys):
    env.branch("done")
    env.say({"done": ["MERGED"]})
    hook.main()
    assert capsys.readouterr().out == ""


def test_each_deletion_logs_one_line_naming_the_branch_and_its_last_commit(env):
    env.branch("done")
    sha = git(env.repo, "rev-parse", "done")
    env.say({"done": ["MERGED"]})
    hook.main()
    lines = env.log.read_text().splitlines()
    assert len(lines) == 1
    assert "deleted done " + sha in lines[0]
    assert not str(env.log).startswith(str(env.repo))


def test_the_deadline_stops_the_github_calls_and_still_exits_zero(env, monkeypatch):
    env.branch("done")
    env.say({"done": ["MERGED"]})
    monkeypatch.setattr(hook, "DEADLINE", 0)
    assert hook.main() == 0
    assert "done" in env.names()


def test_the_deadline_sits_inside_the_hooks_json_timeout():
    config = json.loads((HOOKS / "hooks.json").read_text())
    timeouts = [h["timeout"] for b in config["hooks"]["SessionStart"] for h in b["hooks"]
                if "delete_merged_branches.py" in h["command"]]
    assert timeouts and hook.DEADLINE < timeouts[0]
