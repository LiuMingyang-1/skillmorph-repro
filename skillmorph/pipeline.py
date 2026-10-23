"""首轮实验流水线：轨迹 -> 修订后的 Skill。

单轮运行，不使用历史数据。目录结构位于 ``experiments/<exp>/``：

    data/trajectories.json   原始运行组成的 JSON 列表（见 docs/INTERFACES.md）
    prompts/                 各阶段共用的 prompt 集合
    skills/                  初始 Skill 目录树
    rounds/round_001/
        prompts/        本轮使用的 prompt 集合副本
        skills_before/  输入 Skill 目录树副本
        trajectories/   实际使用的输入轨迹
        analysis/       抽象后的运行、动作映射、覆盖计数和排序
        revision/       编辑位置、提案、评估结果和 diff
        skills_after/   修订后的 Skill 目录树（未应用修订时为原样副本）

``run_experiment`` 会拒绝覆盖已存在的轮次目录。所有产物均为普通 JSON 或文本；
异常会继续向上抛出（不重试、不回退）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .abstraction import abstract_run, cluster_actions
from .attribution import coverage, mark_errors, rank
from .revision import evaluate_and_patch, localize, propose

DATA_FILE = "trajectories.json"
ROUND = "round_001"


def _load_runs(data_dir: Path) -> list[dict]:
    """读取 ``data/trajectories.json``：其中是原始运行组成的 JSON 列表。

    每条运行都需要 task_id/run_id/outcome/steps（见 docs/INTERFACES.md）。
    文件或字段缺失时会直接抛出异常。
    """
    runs = json.loads((data_dir / DATA_FILE).read_text(encoding="utf-8"))
    for i, run in enumerate(runs):
        for key in ("task_id", "run_id", "outcome", "steps"):
            if key not in run:
                raise ValueError(f"run #{i} in {data_dir} is missing {key!r}")
    return runs


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _prepare_round(exp: Path) -> Path:
    """创建 round_001 并保存输入快照；若目录已存在则报错。"""
    round_dir = exp / "rounds" / ROUND
    round_dir.mkdir(parents=True, exist_ok=False)
    for sub in ("prompts", "skills_before", "trajectories", "analysis",
                "revision", "skills_after"):
        (round_dir / sub).mkdir()
    shutil.copytree(exp / "prompts", round_dir / "prompts", dirs_exist_ok=True)
    shutil.copytree(
        exp / "skills", round_dir / "skills_before", dirs_exist_ok=True
    )
    return round_dir


def _revision(ranked, skill_dir, runs, round_dir, *, prompt_dir, client):
    """对每个可疑动作依次执行 localize -> propose -> evaluate_and_patch。"""
    rev_dir = round_dir / "revision"
    edit_sites, proposals = [], []
    for action in ranked:
        site = localize(
            action, skill_dir, runs, client=client, prompt_dir=prompt_dir
        )
        edit_sites.append(site)
        if site["locations"]:
            proposal = propose(site, client=client, prompt_dir=prompt_dir)
            # evaluate_and_patch 需要编辑位置中的证据和出现记录；
            # propose() 本身只返回 action_id、edits 和 rationale。
            proposals.append({**proposal, "edit_site": site})
    result = evaluate_and_patch(
        proposals,
        skill_dir,
        client=client,
        prompt_dir=prompt_dir,
        output_dir=round_dir / "skills_after",
    )
    _write_json(rev_dir / "edit_sites.json", edit_sites)
    _write_json(rev_dir / "proposals.json", proposals)
    _write_json(rev_dir / "evaluation.json", {
        "selected": result["selected"],
        "rejected": result["rejected"],
        "skills_after": result["skills_after"],
    })
    _write_text(rev_dir / "skills.diff", result["diff"])
    return result


def run_experiment(experiment_dir, *, client=None) -> dict:
    """对 ``experiment_dir`` 执行一轮完整的流水线。

    ``client`` 是提供 ``chat.completions.create`` 和 ``embeddings.create``
    接口的 OpenAI 兼容客户端（或 fake）；若为 ``None``，则分别使用
    根目录 .env 配置的聊天和嵌入客户端。返回摘要字典，该摘要也会写入
    ``rounds/round_001/analysis/summary.json``。
    """
    exp = Path(experiment_dir)
    prompt_dir = exp / "prompts"
    skill_dir = exp / "skills"
    raw_runs = _load_runs(exp / "data")
    if not raw_runs:
        raise ValueError(f"no trajectories found under {exp / 'data'}")

    round_dir = _prepare_round(exp)
    for run in raw_runs:
        _write_json(
            round_dir / "trajectories" / f"{run['task_id']}__{run['run_id']}.json",
            run,
        )

    analysis = round_dir / "analysis"
    runs = [
        abstract_run(run, prompt_dir=prompt_dir, client=client)
        for run in raw_runs
    ]
    action_map = cluster_actions(runs, client=client)
    runs = [
        mark_errors(run, prompt_dir=prompt_dir, client=client)
        if run["outcome"] == "success" else run
        for run in runs
    ]
    cov = coverage(runs)
    ranked = rank(cov, abstracted_runs=runs)

    _write_json(analysis / "abstracted_runs.json", runs)
    _write_json(analysis / "action_map.json", action_map)
    _write_json(analysis / "coverage.json", cov)
    _write_json(analysis / "ranking.json", ranked)

    result = _revision(
        ranked, skill_dir, runs, round_dir, prompt_dir=prompt_dir,
        client=client,
    )

    summary = {
        "experiment": exp.name,
        "round": ROUND,
        "runs": len(raw_runs),
        "actions_clustered": len(action_map),
        "suspicious_actions": [a["action_id"] for a in ranked],
        "selected": result["selected"],
        "rejected": result["rejected"],
        "diff_empty": not result["diff"],
        "skills_after": result["skills_after"],
    }
    _write_json(analysis / "summary.json", summary)
    return summary
