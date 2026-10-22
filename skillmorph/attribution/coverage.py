"""按任务统计各动作在不同运行中的覆盖次数（论文 §4.2，公式 4）。

如果一条运行轨迹中至少出现一次动作 a，则该运行覆盖动作 a。失败运行中出现的
每个动作都计入失败覆盖。成功运行则按动作的每次出现分别判断：被判定为
`introduces_error` 的出现计入失败覆盖，否则计入成功覆盖。每条运行对动作 a 的
每种覆盖计数最多贡献一次，因此同一条成功运行中的同一动作若有不同判断，
N- 和 N+ 都可能增加。

F_{i,t} 统计任务 t 中至少为一个动作提供失败覆盖的运行数：包括所有含动作的失败运行，
以及至少包含一次引入错误动作的成功运行。
"""


def _run_key(run: dict) -> str:
    return f"{run['task_id']}/{run['run_id']}"


def coverage(abstracted_runs: list[dict]) -> dict:
    """计算每个任务中各动作的失败覆盖数和成功覆盖数。

    每条运行都必须包含 `task_id`、`run_id`、`outcome` 和 `transitions`；
    transitions 中须包含 `action_id` 和 `introduces_error`（成功运行必需，
    请先调用 `mark_errors`）。

    返回 `{task_id: {"actions": {action_id: {"n_fail","n_succ",
    "fail_runs","succ_runs"}}, "f": int, "fail_runs": [...]}}`，
    可序列化为 JSON。`fail_runs`/`succ_runs` 中的条目以 `task_id/run_id` 为键。
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
