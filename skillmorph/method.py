"""SkillMorph 修订方法的 Method 接口适配。

把现有 ``skillmorph`` 的 abstraction/attribution/revision 阶段包成
``runner.interfaces.Method``：轨迹 + 原始 Skill → 分析 → 修订后的
Skill 树写入 ``output_dir``。不重写算法——内部复用
``skillmorph.pipeline._revision`` 与各阶段函数；分析/修订模型经
``client``（OpenAI 兼容或 fake）注入，与执行模型完全分开。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .abstraction import abstract_run, cluster_actions
from .attribution import coverage, mark_errors, rank
from .pipeline import _revision, _write_json


class SkillMorphMethod:
    """``Method.revise`` 实现：轨迹 → 修订后 Skill 树。

    ``client_name`` 选择分析/修订模型客户端；当前只支持
    ``None``/``"env"``（.env 中 LLM_* 配置）。离线编排验证用
    ``SkillMorphMethod.with_client(<scripted client>)`` 注入 fake——
    产出是 synthetic，不代表真实模型判断。
    """

    def __init__(self, client_name: str | None = None):
        if client_name in (None, "env"):
            self._client = None  # 惰性走 llm.get_client()（.env 配置）
        else:
            raise ValueError(
                f"unknown analysis client {client_name!r}; supported: "
                "'env' (default, .env LLM_*) or an injected client object")

    @classmethod
    def with_client(cls, client) -> "SkillMorphMethod":
        """测试/离线编排注入脚本化客户端；不读 .env、不联网。"""
        obj = cls.__new__(cls)
        obj._client = client
        return obj

    def revise(self, trajectories: list[dict], skill_dir: Path,
               output_dir: Path, cfg: dict) -> dict:
        """单轮修订：``output_dir`` 是干净的输出根。

        布局：``output_dir/skills_after`` = 修订后的 Skill 树；
        ``output_dir/analysis`` = abstracted_runs/action_map/coverage/
        ranking；``output_dir/revision`` = edit_sites/proposals/
        evaluation/skills.diff。输入 ``skill_dir`` 永不修改。
        """
        prompt_dir = Path(cfg["prompt_dir"])
        skill_dir = Path(skill_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=False)
        analysis_dir = output_dir / "analysis"
        analysis_dir.mkdir()
        (output_dir / "revision").mkdir()

        for i, run in enumerate(trajectories):
            for key in ("task_id", "run_id", "outcome", "steps"):
                if key not in run:
                    raise ValueError(
                        f"trajectory #{i} missing required key {key!r}")
            if run["outcome"] not in ("success", "fail"):
                raise ValueError(
                    f"trajectory #{i} has outcome {run['outcome']!r} — "
                    "only success/fail runs reach the method; invalid "
                    "must be excluded by the orchestrator")

        # --- abstraction ---------------------------------------------------
        runs = []
        for i, run in enumerate(trajectories):
            _stage(f"abstract {i + 1}/{len(trajectories)} "
                   f"{run['task_id']}/{run['run_id']}")
            runs.append(abstract_run(
                run, prompt_dir=prompt_dir, client=self._client))
        _stage("clustering actions")
        action_map = cluster_actions(runs, client=self._client)
        runs = [
            mark_errors(run, prompt_dir=prompt_dir, client=self._client)
            if run["outcome"] == "success" else run
            for run in runs
        ]
        cov = coverage(runs)
        ranked = rank(cov, abstracted_runs=runs)

        _write_json(analysis_dir / "abstracted_runs.json", runs)
        _write_json(analysis_dir / "action_map.json", action_map)
        _write_json(analysis_dir / "coverage.json", cov)
        _write_json(analysis_dir / "ranking.json", ranked)

        # --- revision -------------------------------------------------------
        # _revision 把 localize/propose/evaluate 产物写进 run_dir/revision
        # 并把修订后树写进 run_dir/skills_after；这里 run_dir=output_dir。
        rev = _revision(ranked, skill_dir, runs, output_dir,
                        prompt_dir=prompt_dir, client=self._client)

        return {
            "trajectories": len(trajectories),
            "actions_clustered": len(action_map),
            "suspicious_actions": [a["action_id"] for a in ranked],
            "selected": rev["selected"],
            "rejected": rev["rejected"],
            "diff": rev["diff"],
            "skills_after": rev["skills_after"],
        }


def get_method(cfg: dict | None = None) -> "SkillMorphMethod":
    """runner 工厂入口：``method.client``（默认 .env）之外的配置字段
    目前不消费。"""
    return SkillMorphMethod(client_name=(cfg or {}).get("client"))


def _stage(note: str) -> None:
    print(f"skillmorph-method: {note}", file=sys.stderr, flush=True)
