"""使用 LLM 将一条原始轨迹抽象为状态转移序列。

提示词要求模型将原始步骤合并为有意义的操作，并输出
(state_before, action, state_after) 三元组，同时注明每个转移对应的原始步骤索引。
每个 LLM 输出项保留为一条状态转移，并附上其覆盖步骤中的 skills_used / files_read 并集，
以便后续阶段将证据追溯到 Skill 来源。
"""

from __future__ import annotations

from pathlib import Path

from .. import llm


def _load_prompt(prompt_dir: Path | str) -> str:
    return (Path(prompt_dir) / "abstract.txt").read_text(encoding="utf-8")


def _format_steps(steps: list[dict]) -> str:
    lines = []
    for i, step in enumerate(steps):
        parts = [f"step {i}: action={step['action']}"]
        if step.get("observation"):
            parts.append(f"observation={step['observation']}")
        if step.get("skills_used"):
            parts.append(f"skills_used={step['skills_used']}")
        if step.get("files_read"):
            parts.append(f"files_read={step['files_read']}")
        lines.append("\n  ".join(parts))
    return "\n".join(lines)


def abstract_run(raw: dict, *, prompt_dir, client=None) -> dict:
    """将一条原始运行抽象为状态转移序列。

    `raw` 遵循 docs/INTERFACES.md 中阶段 0 的结构。返回字典，保留
    task_id / run_id / outcome / task，并包含 `transitions` 列表；每项含有
    {k, state_before, action, state_after, skills_used, files_read,
    source_steps}。k 从 1 开始，为返回的状态转移编号；论文中的
    (mu_{k-1}, a_k, mu_k) 对应 transitions[k-1]。
    source_steps 是模型报告的、每条状态转移所覆盖的原始步骤索引（从 0 开始）。
    """
    prompt = _load_prompt(prompt_dir)
    user = (
        f"Task: {raw['task']}\n\n"
        f"Trajectory steps:\n{_format_steps(raw['steps'])}\n\n"
        "Return the JSON object described in the system prompt."
    )
    result = llm.chat_json(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ],
        client=client,
    )

    steps = raw["steps"]
    transitions = []
    for k, tr in enumerate(result["transitions"], start=1):
        covered = tr["source_steps"]
        for idx in covered:
            if idx < 0 or idx >= len(steps):
                raise ValueError(
                    f"transition {k} references out-of-range source step {idx}"
                )
        skills_used = sorted({s for i in covered for s in steps[i].get("skills_used", [])})
        files_read = sorted({f for i in covered for f in steps[i].get("files_read", [])})
        transitions.append(
            {
                "k": k,
                "state_before": tr["state_before"],
                "action": tr["action"],
                "state_after": tr["state_after"],
                "skills_used": skills_used,
                "files_read": files_read,
                "source_steps": covered,
            }
        )

    return {
        "task_id": raw["task_id"],
        "run_id": raw["run_id"],
        "outcome": raw["outcome"],
        "task": raw["task"],
        "transitions": transitions,
    }
