"""单次实验流水线：轨迹 -> 修订后的 Skill。

每次运行独立，不读取之前运行的结果。目录结构位于 ``experiments/<exp>/``：

    data/trajectories.json   原始运行组成的 JSON 列表（见 docs/INTERFACES.md）
    prompts/                 各阶段共用的 prompt 集合
    skills/                  初始 Skill 目录树
    runs/run_001, run_002, ...
        prompts/        本次运行使用的 prompt 集合副本
        skills_before/  输入 Skill 目录树副本
        trajectories/   实际使用的输入轨迹
        analysis/       抽象后的运行、动作映射、覆盖计数和排序
        revision/       编辑位置、提案、评估结果和 diff
        skills_after/   修订后的 Skill 目录树（未应用修订时为原样副本）
        raw/            chat_json 解析失败时保存的原始模型回复

``run_experiment`` 自动选择下一个可用编号 ``runs/run_NNN``；
``mkdir(exist_ok=False)`` 保证拒绝覆盖已存在的运行目录，已有产物完整保留。
所有产物均为普通 JSON 或文本；SDK 重试后仍失败的异常继续向上抛出，流水线不额外重试或回退。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from . import llm
from .abstraction import abstract_run, cluster_actions
from .attribution import coverage, mark_errors, rank
from .revision import evaluate_and_patch, localize, propose

DATA_FILE = "trajectories.json"
RUN_PATTERN = re.compile(r"run_(\d+)$")


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
    path.write_text(text, encoding="utf-8", newline="\n")


def _next_run_number(runs_dir: Path) -> int:
    """返回 runs_dir 下最大的合法 ``run_NNN`` 编号 + 1；没有则为 1。

    忽略空洞编号和非 run_NNN 形式的条目。
    """
    last = 0
    if runs_dir.is_dir():
        for entry in runs_dir.iterdir():
            match = RUN_PATTERN.match(entry.name)
            if entry.is_dir() and match:
                last = max(last, int(match.group(1)))
    return last + 1


def _prepare_run(exp: Path) -> Path:
    """创建 ``runs/run_NNN`` 并保存输入快照；mkdir 保证不覆盖已有目录。"""
    runs_dir = exp / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_dir = runs_dir / f"run_{_next_run_number(runs_dir):03d}"
    run_dir.mkdir(parents=False, exist_ok=False)
    for sub in ("prompts", "skills_before", "trajectories", "analysis",
                "revision", "skills_after", "raw"):
        (run_dir / sub).mkdir()
    shutil.copytree(exp / "prompts", run_dir / "prompts", dirs_exist_ok=True)
    shutil.copytree(
        exp / "skills", run_dir / "skills_before", dirs_exist_ok=True
    )
    return run_dir


def _stage(note: str) -> None:
    """向 stderr 报告阶段进度；stdout 保留给最终摘要 JSON。"""
    print(f"skillmorph: {note}", file=sys.stderr, flush=True)


def _revision(ranked, skill_dir, runs, run_dir, *, prompt_dir, client):
    """对每个可疑动作依次执行 localize -> propose -> evaluate_and_patch。"""
    rev_dir = run_dir / "revision"
    edit_sites, proposals = [], []
    for action in ranked:
        _stage(f"revision: localizing {action['action_id']}")
        site = localize(
            action, skill_dir, runs, client=client, prompt_dir=prompt_dir
        )
        edit_sites.append(site)
        if site["locations"]:
            _stage(f"revision: proposing edits for {action['action_id']}")
            proposal = propose(site, client=client, prompt_dir=prompt_dir)
            # evaluate_and_patch 需要编辑位置中的证据和出现记录；
            # propose() 本身只返回 action_id、edits 和 rationale。
            proposals.append({**proposal, "edit_site": site})
    result = evaluate_and_patch(
        proposals,
        skill_dir,
        client=client,
        prompt_dir=prompt_dir,
        output_dir=run_dir / "skills_after",
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
    """对 ``experiment_dir`` 执行一次完整的独立运行。

    ``client`` 是提供 ``chat.completions.create`` 和 ``embeddings.create``
    接口的 OpenAI 兼容客户端（或 fake）；若为 ``None``，则分别使用
    根目录 .env 配置的聊天和嵌入客户端。返回摘要字典，该摘要也会写入
    ``runs/run_NNN/analysis/summary.json``。
    """
    exp = Path(experiment_dir)
    prompt_dir = exp / "prompts"
    skill_dir = exp / "skills"
    _stage(f"loading trajectories from {exp / 'data' / DATA_FILE}")
    raw_runs = _load_runs(exp / "data")
    if not raw_runs:
        raise ValueError(f"no trajectories found under {exp / 'data'}")

    run_dir = _prepare_run(exp)
    # chat_json 解析失败的原始模型回复随本次运行产物保存在 run_NNN/raw/，
    # 便于定位非法输出；该设置仅对本次运行生效，结束时恢复原值。
    old_raw_dir = llm._raw_dir
    llm.set_raw_dir(run_dir / "raw")
    try:
        for run in raw_runs:
            _write_json(
                run_dir / "trajectories" / f"{run['task_id']}__{run['run_id']}.json",
                run,
            )

        analysis = run_dir / "analysis"
        runs = []
        for i, run in enumerate(raw_runs):
            _stage(f"abstracting run {i + 1}/{len(raw_runs)}: "
                   f"{run['task_id']}/{run['run_id']}")
            runs.append(abstract_run(run, prompt_dir=prompt_dir, client=client))
        _stage(f"clustering {sum(len(r['transitions']) for r in runs)} transitions")
        action_map = cluster_actions(runs, client=client)
        _stage("marking error-introducing actions in successful runs")
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
            ranked, skill_dir, runs, run_dir, prompt_dir=prompt_dir,
            client=client,
        )

        summary = {
            "experiment": exp.name,
            "run": run_dir.name,
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
    finally:
        llm.set_raw_dir(old_raw_dir)
