"""Per-task coverage counts of actions across runs (paper §4.2, Eq. 4).

A run covers action a if its trajectory contains at least one occurrence of a.
Failed runs give failure coverage to every occurring action. Successful runs
split per occurrence: an occurrence judged `introduces_error` gives failure
coverage, otherwise success coverage. Each run contributes at most once to
*each* coverage count of a, so one successful run may contribute both N- and
N+ for the same action when its occurrences split.

F_{i,t} counts the runs of task t providing failure coverage of at least one
action: all failed runs (that have actions) plus successful runs containing at
least one error-introducing occurrence.
"""


def _run_key(run: dict) -> str:
    return f"{run['task_id']}/{run['run_id']}"


def coverage(abstracted_runs: list[dict]) -> dict:
    """Compute per-task, per-action failure/success coverage counts.

    Each run must have `task_id`, `run_id`, `outcome` and `transitions`;
    transitions carry `action_id` plus `introduces_error` (required on
    successful runs — call `mark_errors` first).

    Returns `{task_id: {"actions": {action_id: {"n_fail","n_succ",
    "fail_runs","succ_runs"}}, "f": int, "fail_runs": [...]}}`,
    JSON-serializable. `fail_runs`/`succ_runs` hold `task_id/run_id` keys.
    """
    tasks: dict[str, dict] = {}
    for run in abstracted_runs:
        task_id = run["task_id"]
        outcome = run["outcome"]
        if outcome not in ("success", "fail"):
            raise ValueError(f"unknown outcome {outcome!r} in {_run_key(run)}")
        task = tasks.setdefault(task_id, {"actions": {}, "f": 0, "fail_runs": []})
        run_id = _run_key(run)

        covers_fail: set[str] = set()
        covers_succ: set[str] = set()
        for t in run["transitions"]:
            action_id = t["action_id"]
            if outcome == "fail":
                covers_fail.add(action_id)
            else:
                if "introduces_error" not in t:
                    raise ValueError(
                        f"successful run {_run_key(run)} has an unjudged "
                        "transition; call mark_errors first"
                    )
                if t["introduces_error"]:
                    covers_fail.add(action_id)
                else:
                    covers_succ.add(action_id)

        for action_id in covers_fail:
            a = task["actions"].setdefault(
                action_id,
                {"n_fail": 0, "n_succ": 0, "fail_runs": [], "succ_runs": []},
            )
            a["n_fail"] += 1
            a["fail_runs"].append(run_id)
        for action_id in covers_succ:
            a = task["actions"].setdefault(
                action_id,
                {"n_fail": 0, "n_succ": 0, "fail_runs": [], "succ_runs": []},
            )
            a["n_succ"] += 1
            a["succ_runs"].append(run_id)

        if covers_fail:
            task["f"] += 1
            task["fail_runs"].append(run_id)
    return tasks
