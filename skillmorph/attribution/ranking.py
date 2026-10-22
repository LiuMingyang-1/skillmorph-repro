"""Cross-task aggregation and Ochiai suspiciousness scoring (paper §4.2, Eq. 9).

Candidates are actions with failure coverage in at least one task. The score
aggregates N-/N+ across tasks (Eq. 8; first round has no history so adjusted
counts equal raw counts) and applies:

    s(a) = N-(a) / sqrt(F * (N-(a) + N+(a))),   F = sum_t F_{i,t}

Historical weighting (Eq. 5-7) is out of scope for the first loop and is not
implemented.
"""

import math

from .. import config


def _action_text(abstracted_runs: list[dict], action_id: str) -> str:
    for run in abstracted_runs:
        for t in run["transitions"]:
            if t.get("action_id") == action_id:
                return t.get("action_text") or t.get("action", "")
    return ""


def rank(
    coverage_by_task: dict,
    *,
    top_n: int = config.TOP_N_SUSPICIOUS,
    abstracted_runs: list[dict] | None = None,
) -> list[dict]:
    """Rank candidate actions by suspicious score, descending.

    `coverage_by_task` is the output of `coverage()`. `abstracted_runs` is
    optional and only supplies human-readable `action_text` for each action id.

    Returns the top-`top_n` entries as dicts with `action_id`, `action_text`,
    `score`, `n_fail`, `n_succ`, `fail_runs`, `succ_runs`, `tasks` — all
    JSON-serializable, run lists keyed `task_id/run_id` for edit-site lookup.
    """
    f_total = sum(task["f"] for task in coverage_by_task.values())
    if f_total == 0:
        return []

    n_fail: dict[str, int] = {}
    n_succ: dict[str, int] = {}
    fail_runs: dict[str, list[str]] = {}
    succ_runs: dict[str, list[str]] = {}
    tasks_of: dict[str, list[str]] = {}
    for task_id, task in coverage_by_task.items():
        for action_id, a in task["actions"].items():
            n_fail[action_id] = n_fail.get(action_id, 0) + a["n_fail"]
            n_succ[action_id] = n_succ.get(action_id, 0) + a["n_succ"]
            fail_runs.setdefault(action_id, []).extend(a["fail_runs"])
            succ_runs.setdefault(action_id, []).extend(a["succ_runs"])
            if a["n_fail"] > 0 or a["n_succ"] > 0:
                tasks_of.setdefault(action_id, []).append(task_id)

    ranked = []
    for action_id, nf in n_fail.items():
        if nf <= 0:
            continue  # candidate requires failure coverage in some task
        ns = n_succ.get(action_id, 0)
        score = nf / math.sqrt(f_total * (nf + ns))
        ranked.append(
            {
                "action_id": action_id,
                "action_text": (
                    _action_text(abstracted_runs, action_id)
                    if abstracted_runs
                    else ""
                ),
                "score": score,
                "n_fail": nf,
                "n_succ": ns,
                "fail_runs": fail_runs.get(action_id, []),
                "succ_runs": succ_runs.get(action_id, []),
                "tasks": sorted(set(tasks_of.get(action_id, []))),
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["action_id"]))
    return ranked[:top_n]
