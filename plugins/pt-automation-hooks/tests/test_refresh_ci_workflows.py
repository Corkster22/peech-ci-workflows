"""refresh_ci_workflows.py - the SessionStart clone freshness step (PPA-1662).

Every case builds a real origin and a real clone under tmp_path, so what is
asserted is what git does rather than what a stub says it would. No case
touches the operator's own peech-ci-workflows clone.
"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "refresh_ci_workflows.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_ci_workflows", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

#: git identity and config isolated from the operator's own.
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd, name, text):
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)


def advance_origin(origin, tmp_path, text="v2"):
    """Land a commit on origin/main from a second working copy."""
    work = tmp_path / "work"
    if not work.exists():
        git(tmp_path, "clone", "-q", str(origin), str(work))
    commit(work, "pt_transition.py", text)
    git(work, "push", "-q", "origin", "main")


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    """An origin with one commit on main, and a clone of it the hook reads."""
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    commit(seed, "pt_transition.py", "v1")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    target = tmp_path / "peech-ci-workflows"
    git(tmp_path, "clone", "-q", str(origin), str(target))
    monkeypatch.setattr(hook, "CLONE", target)
    return target


def run(capsys):
    code = hook.main()
    out = capsys.readouterr().out
    return code, (json.loads(out)["systemMessage"] if out else None)


def test_an_absent_clone_warns_naming_the_path_and_returns_zero(
        tmp_path, monkeypatch, capsys):
    missing = tmp_path / "peech-ci-workflows"
    monkeypatch.setattr(hook, "CLONE", missing)

    code, message = run(capsys)

    assert code == 0
    assert f"Clone peech-ci-workflows to {missing}" in message


def test_a_current_clone_says_nothing(clone, capsys):
    assert run(capsys) == (0, None)


def test_a_clean_main_behind_origin_is_fast_forwarded(clone, tmp_path, capsys):
    advance_origin(tmp_path / "origin.git", tmp_path)

    assert run(capsys) == (0, None)
    assert (clone / "pt_transition.py").read_text() == "v2"
    assert git(clone, "rev-parse", "HEAD") == git(clone, "rev-parse", "origin/main")


def test_a_merged_branch_carrying_origin_main_content_says_nothing(
        clone, tmp_path, capsys):
    """A squash merge leaves the clone on a branch that is not an ancestor of
    origin/main but carries its tree. That is current, not lagging."""
    git(clone, "checkout", "-q", "-b", "ppa-1")
    commit(clone, "pt_transition.py", "v2")
    advance_origin(tmp_path / "origin.git", tmp_path, text="v2")

    assert run(capsys) == (0, None)
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "ppa-1"


def test_another_branch_that_lags_warns_and_is_left_alone(clone, tmp_path, capsys):
    git(clone, "checkout", "-q", "-b", "ppa-2")
    before = git(clone, "rev-parse", "HEAD")
    advance_origin(tmp_path / "origin.git", tmp_path)

    code, message = run(capsys)

    assert code == 0
    assert "differs from origin/main" in message
    assert "'ppa-2', not main" in message
    assert git(clone, "rev-parse", "HEAD") == before


def test_a_dirty_main_that_lags_warns_and_is_left_alone(clone, tmp_path, capsys):
    (clone / "pt_transition.py").write_text("local edit")
    advance_origin(tmp_path / "origin.git", tmp_path)

    code, message = run(capsys)

    assert code == 0
    assert "uncommitted changes" in message
    assert (clone / "pt_transition.py").read_text() == "local edit"


def test_a_failed_fetch_warns_and_returns_zero(clone, capsys):
    git(clone, "remote", "set-url", "origin", str(clone.parent / "nowhere.git"))

    code, message = run(capsys)

    assert code == 0
    assert "git fetch failed" in message


def test_a_raising_check_still_returns_zero(monkeypatch, capsys):
    def boom():
        raise OSError("git not found")

    monkeypatch.setattr(hook, "freshness", boom)

    code, message = run(capsys)

    assert code == 0
    assert "freshness was not checked" in message


def test_the_hooks_json_command_runs_it_with_home_moved(tmp_path):
    """The declared SessionStart command, run by a shell. HOME moves, so no
    clone exists there and the step warns and exits 0."""
    (command,) = [h["command"]
                  for block in json.loads((HOOK.parent / "hooks.json").read_text())
                  ["hooks"]["SessionStart"] for h in block["hooks"]
                  if "refresh_ci_workflows.py" in h["command"]]
    env = {**os.environ, "HOME": str(tmp_path),
           "CLAUDE_PLUGIN_ROOT": str(HOOK.parents[1])}
    proc = subprocess.run(["sh", "-c", command], capture_output=True, text=True,
                          env=env, timeout=60)

    assert proc.returncode == 0, proc.stderr
    assert "Clone peech-ci-workflows to" in json.loads(proc.stdout)["systemMessage"]
