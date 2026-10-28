"""单轮编排器：原 Skill 执行 → 方法修订 → 新 Skill 重置执行 → 对比。

输入是一份实验配置（JSON；``python -m runner <config>``）。配置显式
指定数据集、方法、任务、Skill、执行与修订参数和输出目录；编排器只
依赖 ``runner.interfaces`` 的 DatasetAdapter/Method 契约，不含任何
数据集或方法专属分支。

产物目录 ``<output>/<experiment_name>/`` 下：

    config.json          本次配置原样拷贝
    prompts/             配置的 prompt_dir 快照（随产物保存）
    skills_before/       原始 Skill 的**输入快照**——before 阶段执行与
                         method.revise 都以此为唯一输入（源目录变更不影响
                         已开始的实验）
    method/skills_after/ 方法修订后的 Skill 树
    method/analysis/     abstracted_runs/action_map/coverage/ranking
    method/revision/     edit_sites/proposals/evaluation/skills.diff
    runs_before/run_NNN/ 数据集为每个 task×repetition 登记的 run 目录
                         （内含执行/判分/轨迹产物与原始 agent 日志）
    runs_after/run_NNN/  修订后 Skill 重跑的 run 目录
    trajectories/        供方法消费的原始 Skill 轨迹 JSON（success/fail）
    analysis/method_result.json  方法返回的摘要
    comparison.json      每个 task 修订前后判分对照
    summary.json         汇总 + invalid run 清单（invalid 不喂方法）

单轮设计：原始 run 与修订后 run 不共用 run_dir——``runs_before`` 与
``runs_after`` 分开登记，数据集对每个 run_dir 做完整环境准备，新
Skill 在重置的干净环境执行。无多轮历史、无断点续跑、无效果统计。

错误语义：数据集以 ``outcome="invalid"`` 明确报告的失败（setup/
runner/evaluator/缺轨迹证据）记入 ``summary.json:invalid_runs`` 并
跳过；代码缺陷与非预期异常不经翻译——当前 run 先 cleanup，然后原样
抛出中断实验。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_PATTERN = "run_{:03d}"

DATASET_MODULES = {
    "swe_skills_bench": REPO_ROOT / "datasets/swe_skills_bench/adapter.py",
}

METHOD_MODULES = {
    "skillmorph": REPO_ROOT / "skillmorph/method.py",
    "copy": REPO_ROOT / "runner/methods.py",
}


def _stage(note: str) -> None:
    """向 stderr 报告阶段进度；stdout 保留给最终摘要 JSON。"""
    print(f"runner: {note}", file=sys.stderr, flush=True)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _copytree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=False)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _load_module(path: Path, mod_name: str):
    if not path.is_file():
        raise ValueError(f"module not found: {path}")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_entry(entry: str, builtin: dict, kind: str,
                factory: str, base: Path, cfg: dict):
    """把 ``name`` / ``path.py`` 解析成含 ``factory()`` 的模块并调用。

    内置名字查 ``builtin`` 映射；否则按文件路径（相对配置文件目录
    解析）加载。新数据集/新方法只需给出一个含工厂函数的 .py——
    不需要改编排器。
    """
    if entry in builtin:
        path = builtin[entry]
    else:
        candidate = Path(entry)
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.is_file():
            path = candidate.resolve()
        else:
            raise ValueError(
                f"unknown {kind} {entry!r}; known: {sorted(builtin)} "
                f"or pass a .py path exposing {factory}()")
    return getattr(_load_module(path, f"{kind}_{path.stem}"),
                   factory)(cfg)


def load_dataset_adapter(name: str, base: Path = REPO_ROOT,
                         cfg: dict | None = None):
    """按 ``dataset.name``/``dataset.module`` 解析适配模块 →
    ``get_adapter(cfg)`` 实例。"""
    return _load_entry(name, DATASET_MODULES, "dataset", "get_adapter",
                       base, cfg or {})


def build_method(method_cfg: dict, base: Path = REPO_ROOT):
    """按 ``method.name``/``method.module`` 构造 Method →
    ``get_method()`` 实例。

    内置：``"skillmorph"``（``method.client`` 选分析/修订模型客户端；
    当前支持 ``"env"``/缺省走 .env LLM_*——测试用 fake 客户端经
    ``SkillMorphMethod.with_client`` 或 monkeypatch 本工厂注入，
    不经 config）、``"copy"``/``"noop"``（原样拷贝，不做修订）。
    自定义方法给一个含 ``get_method(cfg)`` 的 .py 路径即可。
    """
    entry = method_cfg.get("module") or method_cfg.get("name")
    if not entry:
        raise ValueError("config.method requires 'name' or 'module'")
    name = method_cfg.get("name")
    if name == "noop":
        entry = "copy"
    if entry == "skillmorph":
        # 内置包内模块（相对 import）走普通 import 而非按路径加载
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        import skillmorph.method
        return skillmorph.method.get_method(method_cfg)
    return _load_entry(entry, METHOD_MODULES, "method", "get_method",
                       base, method_cfg)


def _resolve_agent(agent_cfg: dict, base: Path) -> dict:
    """执行模型配置：dict 至少含 ``agent_cmd``；``agent_config_json`` /
    ``trajectory_jsonl`` 路径按配置文件所在目录解析；
    ``trajectory_container_path``（容器内 agent 日志路径）原样传给
    数据集——execute 后用 docker cp 提取到 run_dir/agent.jsonl。"""
    agent = dict(agent_cfg or {})
    cfg_file = agent.pop("agent_config_json", None)
    if cfg_file is not None:
        agent["agent_config_json"] = str(
            (base / cfg_file).resolve()
            if not Path(cfg_file).is_absolute() else Path(cfg_file))
    traj = agent.get("trajectory_jsonl")
    if isinstance(traj, str) and not Path(traj).is_absolute():
        agent["trajectory_jsonl"] = str((base / traj).resolve())
    elif isinstance(traj, dict):
        agent["trajectory_jsonl"] = {
            k: (str((base / v).resolve())
                if not Path(v).is_absolute() else v)
            for k, v in traj.items()}
    if not agent.get("agent_cmd"):
        raise ValueError(
            "config requires executor.agent_cmd — the execution model is an "
            "explicit per-run parameter, not dataset state")
    return agent


def _next_run_name(runs_root: Path) -> str:
    n = 1
    if runs_root.is_dir():
        n = 1 + max(
            (int(p.name.rsplit("_", 1)[1]) for p in runs_root.iterdir()
             if p.is_dir() and p.name.startswith("run_")
             and p.name.rsplit("_", 1)[1].isdigit()),
            default=0,
        )
    return RUN_PATTERN.format(n)


def _phase_runs(dataset, tasks: list[str], skill_dir: Path,
                runs_root: Path, dataset_cfg: dict, agent: dict,
                traj_out_dir: Path | None) -> dict:
    """对一批 (task, run) 执行 prepare→execute→[export]→cleanup。

    ``traj_out_dir`` 非空时导出正式轨迹（before 阶段），否则只判分
    （after 阶段）。返回 ``{task_id: {"runs": [run_record...]}}``；
    每个 run_record 带 run_dir、outcome、reason、可选 trajectory 路径。

    错误语义：数据集以 ``outcome="invalid"`` 明确报告的失败记 invalid
    继续；``export_trajectory`` 抛错（缺真实日志/证据门拒绝）与其它
    未捕获异常一样，当前 run 在 finally 中 cleanup 后原样上抛——
    证据不足是数据/通道缺陷，不当普通任务失败降级喂方法。
    """
    runs_root.mkdir(parents=True, exist_ok=True)
    per_task: dict[str, dict] = {}
    for task_id in tasks:
        per_task[task_id] = {"runs": []}
        # 数据集决定每 task 的 run 数（当前由 config.runs_per_task 控制，
        # 数据集侧不重复实现）。
        n_runs = int(dataset_cfg.get("runs_per_task", 1))
        for i in range(1, n_runs + 1):
            run_name = _next_run_name(runs_root)
            run_dir = runs_root / run_name
            record = {"task_id": task_id, "run": run_name,
                      "run_dir": str(run_dir)}
            _stage(f"{runs_root.name}/{run_name}: prepare {task_id} "
                   f"(repetition {i}/{n_runs})")
            dataset.prepare_run(task_id, Path(skill_dir), run_dir,
                                dataset_cfg)
            try:
                result = dataset.execute(run_dir, agent)
                record["outcome"] = result.get("outcome")
                record["reason"] = result.get("reason")
                if result.get("evaluation") is not None:
                    record["evaluation"] = result["evaluation"]

                if traj_out_dir is not None and record["outcome"] in (
                        "success", "fail"):
                    traj = dataset.export_trajectory(run_dir, agent)
                    traj_name = f"{task_id}__{run_name}.json"
                    _write_json(traj_out_dir / traj_name, traj)
                    record["trajectory"] = str(
                        traj_out_dir / traj_name)
                elif traj_out_dir is not None:
                    record["trajectory"] = None
            finally:
                # 环境资源（容器）必清；清理失败原样上抛——资源泄漏不
                # 可静默吞掉。
                dataset.cleanup(run_dir, dataset_cfg)
            _write_json(run_dir / "runner_record.json", record)
            per_task[task_id]["runs"].append(record)
            _stage(f"{run_name}: outcome={record['outcome']} "
                   f"reason={record['reason']}")
    return per_task


def run_experiment(config_path) -> dict:
    """按配置文件执行一轮 before→revise→after 对比，返回 summary dict。

    配置文件是 JSON：
      dataset:   {"name"/"module", "tasks"/"task_families",
                  "runs_per_task", ...数据集自有字段}
      method:    {"name"/"module", "prompt_dir", "client", ...方法字段}
                 "skillmorph"=SkillMorph 修订；"copy"/"noop"=原样拷贝
                 （采集/通道验证用，不声称修订）；其它给含
                 get_method(cfg) 的 .py 路径
      skip_after:  true 时只跑 before+export，不做 revise/rerun
      skill:     {"dir": <path>}  —— 原始 Skill 树根（含 <skill>/ 子目录）
      executor:  {"agent_cmd", "agent_timeout_sec", "agent_config_json",
                  "trajectory_jsonl", "trajectory_container_path"}
      output:    {"dir": <path>}  —— 实验输出根（不存在则创建，存在即拒）

    所有路径字段允许相对路径（相对配置文件所在目录解析）。返回的
    summary 同时写入 ``<output>/<name>/summary.json``。
    """
    config_path = Path(config_path).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    def _resolve(p):
        p = Path(p)
        return p if p.is_absolute() else (base / p).resolve()

    dataset_cfg = dict(cfg.get("dataset") or {})
    method_cfg = dict(cfg.get("method") or {})
    skill_cfg = dict(cfg.get("skill") or {})
    executor_cfg = _resolve_agent(dict(cfg.get("executor") or {}), base)
    out_root = _resolve(cfg["output"]["dir"])
    exp_name = cfg.get("name") or out_root.name
    out_dir = out_root / exp_name
    if out_dir.exists():
        raise FileExistsError(
            f"output experiment dir already exists: {out_dir}")

    for key in ("prompt_dir",):
        if key in method_cfg and method_cfg[key] is not None:
            method_cfg[key] = str(_resolve(method_cfg[key]))
    skill_dir = _resolve(skill_cfg["dir"])
    if not skill_dir.is_dir():
        raise ValueError(f"skill.dir does not exist: {skill_dir}")

    dataset_name = dataset_cfg.get("name") or dataset_cfg.get("module")
    if not dataset_name:
        raise ValueError("config.dataset requires 'name' or 'module'")
    dataset = load_dataset_adapter(
        dataset_cfg.pop("module", None) or dataset_name, base)
    method = build_method(method_cfg, base)

    # 任务列表：显式 tasks 优先；否则数据集按 cfg（如 task_families）解析
    tasks = dataset_cfg.get("tasks")
    if not tasks:
        tasks = dataset.list_tasks(dataset_cfg)
    if not tasks:
        raise ValueError("no tasks selected by config")
    dataset_cfg["tasks"] = list(tasks)

    # --- 输出骨架 -----------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=False)
    _write_json(out_dir / "config.json", cfg)
    if method_cfg.get("prompt_dir"):
        _copytree(Path(method_cfg["prompt_dir"]), out_dir / "prompts")
    # 输入 Skill 的不可变快照：before 执行与 method.revise 都用这一份，
    # 与源目录的后续变更解耦。
    skills_before = out_dir / "skills_before"
    _copytree(skill_dir, skills_before)

    summary = {"experiment": exp_name, "dataset": dataset_name,
               "tasks": tasks, "config": str(config_path)}

    # --- before：原始 Skill 快照执行 + 判分 + 轨迹 --------------------------
    traj_dir = out_dir / "trajectories"
    traj_dir.mkdir()
    before = _phase_runs(dataset, tasks, skills_before,
                         out_dir / "runs_before", dataset_cfg,
                         executor_cfg, traj_dir)
    trajectories = []
    invalid_runs = []
    for task_id, blk in before.items():
        for rec in blk["runs"]:
            if rec["outcome"] in ("success", "fail") \
                    and rec.get("trajectory"):
                trajectories.append(rec["trajectory"])
            else:
                invalid_runs.append(
                    {k: rec[k] for k in
                     ("task_id", "run", "outcome", "reason")})

    # --- 方法修订 -----------------------------------------------------------
    if cfg.get("skip_after"):
        summary.update({
            "output_dir": str(out_dir),
            "runs_before": {t: [r["run"] for r in before[t]["runs"]]
                            for t in before},
            "trajectories_used": len(trajectories),
            "invalid_runs": invalid_runs,
            "skipped_after": True,
        })
        _write_json(out_dir / "summary.json", summary)
        return summary

    _stage(f"method.revise over {len(trajectories)} trajectories "
           f"({len(invalid_runs)} invalid excluded)")
    traj_docs = [json.loads(Path(p).read_text(encoding="utf-8"))
                 for p in trajectories]
    result = method.revise(traj_docs, skills_before,
                           out_dir / "method", method_cfg)
    _write_json(out_dir / "analysis" / "method_result.json", result)
    skills_after_dir = Path(result["skills_after"])

    # --- after：修订后 Skill 在重置环境执行 + 判分 --------------------------
    after = _phase_runs(dataset, tasks, skills_after_dir,
                        out_dir / "runs_after", dataset_cfg,
                        executor_cfg, None)

    # --- 对比 ---------------------------------------------------------------
    comparison = {}
    for task_id in tasks:
        b = [r["outcome"] for r in before[task_id]["runs"]]
        a = [r["outcome"] for r in after[task_id]["runs"]]
        comparison[task_id] = {
            "before": b, "after": a,
            "before_success": b.count("success"),
            "after_success": a.count("success"),
            "before_invalid": b.count("invalid"),
            "after_invalid": a.count("invalid"),
        }
    _write_json(out_dir / "comparison.json", comparison)

    summary.update({
        "output_dir": str(out_dir),
        "runs_before": {t: [r["run"] for r in before[t]["runs"]]
                        for t in before},
        "runs_after": {t: [r["run"] for r in after[t]["runs"]]
                       for t in after},
        "trajectories_used": len(trajectories),
        "invalid_runs": invalid_runs,
        "comparison": comparison,
        "method_summary": {k: v for k, v in result.items()
                           if isinstance(v, (str, int, bool, list))},
    })
    _write_json(out_dir / "summary.json", summary)
    return summary
