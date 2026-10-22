"""跨任务汇总并使用 Ochiai 可疑度公式评分（论文 §4.2，公式 9）。

候选项是在至少一个任务中具有失败覆盖的动作。评分先汇总各任务的 N-/N+
（公式 8；首轮没有历史数据，因此调整后计数等于原始计数），再应用：

    s(a) = N-(a) / sqrt(F * (N-(a) + N+(a))),   F = sum_t F_{i,t}

首轮不涉及历史加权（公式 5–7），因此尚未实现。
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
    """按可疑度从高到低排列候选动作。

    `coverage_by_task` 是 `coverage()` 的输出。`abstracted_runs` 为可选参数，
    仅用于为每个动作 ID 提供便于阅读的 `action_text`。

    返回前 `top_n` 项，每项为包含 `action_id`、`action_text`、`score`、
    `n_fail`、`n_succ`、`fail_runs`、`succ_runs`、`tasks` 的字典，均可
    序列化为 JSON。运行列表使用 `task_id/run_id` 键，以便查找编辑位置。
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
            continue  # 候选动作必须至少在一个任务中具有失败覆盖。
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
