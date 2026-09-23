"""PPA-1616 — merge-close-out.yml closes out this repository's own merges.

The workflow runs on push to main beside workflow_call. On a push the `inputs`
context is empty, so each job's `if` evaluates against a null `regrade`. These
tests read the workflow and assert that routing.
"""

from pathlib import Path

import yaml

import pt_transition

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/merge-close-out.yml")


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def runs(condition, inputs):
    """Evaluate a job's `if` the way GitHub does for the two shapes this file
    uses: `inputs.<name>` and `!inputs.<name>`, where a missing input is null
    and null is falsy. Any other shape is refused, so a rewritten condition
    fails here rather than being read wrongly."""
    expr = condition.removeprefix("${{").removesuffix("}}").strip()
    negate = expr.startswith("!")
    name = expr.removeprefix("!").removeprefix("inputs.")
    assert name.isidentifier() and expr.lstrip("!").startswith("inputs."), (
        f"unsupported condition {condition!r}")
    return bool(inputs.get(name)) != negate


def test_push_to_main_is_a_trigger_beside_workflow_call():
    # PyYAML reads the bare key `on` as the boolean True.
    on = workflow()[True]

    assert on.get("push") == {"branches": ["main"]}
    assert "workflow_call" in on


def test_close_out_job_runs_on_a_push_with_no_regrade_input():
    assert runs(workflow()["jobs"]["close-out"]["if"], inputs={}) is True


def test_regrade_job_is_skipped_on_a_push():
    assert runs(workflow()["jobs"]["regrade-held"]["if"], inputs={}) is False


def test_file_name_is_merge_close_out_yml():
    # merge_close_out_run() refuses the Done hop to any other workflow path.
    assert str(WORKFLOW).endswith("/" + pt_transition.MERGE_CLOSE_OUT_WORKFLOW)
