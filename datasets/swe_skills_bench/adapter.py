"""SWE-Skills-Bench 的 DatasetAdapter 实现。

复用现有 ``setup.py`` / ``run.py`` / ``evaluate.py`` / ``common.py``
的登记-执行-判分-导出协议：

* ``list_tasks``：manifest 中 ``status == "ready"`` 的任务，可按
  ``cfg["task_families"]`` 过滤；
* ``prepare_run`` → ``setup.py`` 登记语义（task/skills/env 身份冻结
  进 run_dir，构建 setup plan，status=pending）；
* ``execute`` → ``run.py`` 执行 + ``evaluate.py`` 判分，三态
  outcome（success/fail/invalid）；
* ``export_trajectory`` → ``run.py --export-only`` 同一实现
  （``export_formal_trajectory``），严格证据门；数据不足直接抛错；
* ``cleanup`` → ``build_cleanup_plan``（只删本 run 容器，保留产物）。

执行模型不是数据集本体：``agent`` dict 由调用方每次显式给出
（``agent_cmd`` 必填，``agent_config_json`` 可选），与 .env 中
分析/修订模型配置完全无关。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_DATASET_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_DATASET_DIR))

import common  # noqa: E402
import evaluate as evaluate_mod  # noqa: E402
import run as run_mod  # noqa: E402
import setup as setup_mod  # noqa: E402

NAME = "swe_skills_bench"


class SweSkillsBenchAdapter:
    def __init__(self, dataset_dir: Path | None = None):
        self.dataset_dir = Path(dataset_dir or _DATASET_DIR)
        self.manifest = common.load_manifest(
            self.dataset_dir / "manifest.json")

    # ------------------------------------------------------------------
    def list_tasks(self, cfg: dict) -> list[str]:
        tasks = [t["task_id"] for t in self.manifest["tasks"]
                 if common.task_is_runnable(t)]
        families = cfg.get("task_families")
        if families:
            wanted = set(families)
            tasks = [tid for tid in tasks if self._task(tid).get("family")
                     in wanted]
        return tasks

    def _task(self, task_id: str) -> dict:
        return common.get_task(self.manifest, task_id)

    # ------------------------------------------------------------------
    def prepare_run(self, task_id: str, skill_dir: Path,
                    run_dir: Path, cfg: dict) -> None:
        task = self._task(task_id)
        skills_dir = common.check_skills_dir(skill_dir)
        skill_tree_hash = common.tree_sha256(skills_dir)

        env_record = common.base_environment_record(self.manifest)
        env_record.update(cfg.get("environment_overrides") or {})
        errors = common.validate_env_record(env_record)
        if errors:
            raise ValueError("environment overrides: " + "; ".join(errors))
        missing = [k for k in
                   ("docker_image_digest", "docker_image_platform")
                   if not env_record.get(k)]
        if missing:
            raise ValueError(
                f"real execution requires pinned image identity; missing "
                f"{missing} (fill manifest.environment or "
                "dataset.environment_overrides)")
        if not common.task_is_runnable(task):
            raise ValueError(
                f"task {task_id} status={task.get('status')!r} — only "
                "ready tasks may run")

        run_id = uuid.uuid4().hex[:12]
        plan = setup_mod.build_setup_plan(
            self.manifest, task, skills_dir, skill_tree_hash,
            run_dir.name, env_record, run_id)
        config = {
            "dataset": self.manifest["dataset"],
            "task_id": task["task_id"],
            "batch": task["batch"],
            "task_status": task.get("status"),
            "task_file": task["task_file"],
            "test_file": task["test_file"],
            "repo": self.manifest["repo"],
            "environment": env_record,
            "evaluation": self.manifest["evaluation"],
            "skills": {
                "host_dir": str(skills_dir),
                "container_dir": common.CONTAINER_SKILLS_DIR,
                "tree_sha256": skill_tree_hash,
            },
            "run_id": run_id,
            "dry_run": False,
            "setup_plan": plan,
        }
        state = {
            "status": common.STATUS_PENDING,
            "task_id": task["task_id"],
            "run_dir": str(run_dir),
            "setup": None,
            "execution": None,
            "evaluation": None,
        }
        run_dir.mkdir(parents=True, exist_ok=False)
        common.write_json(run_dir / "config.json", config)
        common.write_json(run_dir / "run_state.json", state)

    # ------------------------------------------------------------------
    def execute(self, run_dir: Path, agent: dict) -> dict:
        run_dir = Path(run_dir)
        agent_cmd = agent["agent_cmd"]
        argv = [
            "--task-id", self._run_task(run_dir),
            "--run-dir", str(run_dir),
            "--agent-cmd", agent_cmd,
            "--agent-timeout-sec",
            str(agent.get("agent_timeout_sec", 1800)),
            "--exec-timeout-sec",
            str(agent.get("exec_timeout_sec", 300)),
        ]
        if agent.get("agent_config_json"):
            argv += ["--agent-config-json",
                     str(agent["agent_config_json"])]
        rc = run_mod.main(argv)
        if rc != 0:
            return {"outcome": "invalid",
                    "reason": f"run.py exited {rc}"}

        eval_argv = [
            "--run-dir", str(run_dir),
            "--eval-timeout-sec",
            str(agent.get("eval_timeout_sec", 300)),
            "--exec-timeout-sec",
            str(agent.get("exec_timeout_sec", 300)),
        ]
        rc = evaluate_mod.main(eval_argv)
        eval_rec = {}
        if (run_dir / "evaluation.json").is_file():
            eval_rec = common.read_json(run_dir / "evaluation.json")
        state = common.read_json(run_dir / "run_state.json")
        outcome = eval_rec.get("outcome")
        result = {
            "outcome": outcome,
            "reason": eval_rec.get("outcome_reason"),
            "evaluation": eval_rec or None,
            "evaluate_rc": rc,
            "status": state.get("status"),
        }
        if agent.get("trajectory_container_path") \
                and outcome in ("success", "fail"):
            result["trajectory_log"] = self._fetch_agent_log(run_dir, agent)
        return result

    def _fetch_agent_log(self, run_dir: Path, agent: dict) -> dict:
        """cleanup 前把容器内 agent 日志 ``docker cp`` 到 run_dir。

        ``executor.trajectory_container_path`` 是容器内 agent 写的
        JSONL 路径；每 run 提取到 ``run_dir/agent.jsonl``——原始日志
        随 run 产物保留，``export_trajectory`` 默认也从这里取。容器
        路径在 config.json 显式声明，不读取任何凭据。
        """
        config = common.read_json(run_dir / "config.json")
        container = (config.get("setup_plan") or {}).get("container_name")
        if not container:
            return {"extracted": False,
                    "reason": "no container in setup_plan"}
        container_path = agent["trajectory_container_path"]
        dest = run_dir / "agent.jsonl"
        res = common.Executor(dry_run=False).run(
            ["docker", "cp", f"{container}:{container_path}", str(dest)])
        if not res.ok:
            return {"extracted": False,
                    "reason": (res.error or res.stderr.strip()
                               or f"docker cp exit {res.exit_code}"),
                    "container_path": container_path}
        return {"extracted": True, "path": str(dest),
                "container_path": container_path}

    def _run_task(self, run_dir: Path) -> str:
        config = common.read_json(Path(run_dir) / "config.json")
        return config["task_id"]

    # ------------------------------------------------------------------
    def export_trajectory(self, run_dir: Path, agent: dict) -> dict:
        run_dir = Path(run_dir)
        config = common.read_json(run_dir / "config.json")
        state = common.read_json(run_dir / "run_state.json")
        eval_record = common.read_json(run_dir / "evaluation.json")

        jsonl = agent.get("trajectory_jsonl")
        if jsonl is not None:
            jsonl_path = self._resolve_jsonl_path(run_dir, jsonl)
        else:
            jsonl_path = self._find_jsonl(run_dir, agent)

        res = run_mod.export_formal_trajectory(
            run_dir, config, state, eval_record, jsonl_path,
            self.dataset_dir, self.manifest)
        if not res.get("exported"):
            raise RuntimeError(
                f"formal trajectory export refused: {res.get('reason')}")
        return common.read_json(res["path"])

    def _resolve_jsonl_path(self, run_dir: Path, spec) -> Path:
        """``executor.trajectory_jsonl``：统一路径字符串，或按
        ``run_dir.name``/``task_id`` 键的 dict。"""
        if isinstance(spec, dict):
            task_id = self._run_task(run_dir)
            key = run_dir.name if run_dir.name in spec else task_id
            if key not in spec:
                raise FileNotFoundError(
                    f"trajectory_jsonl has no entry for run "
                    f"{run_dir.name!r} or task {task_id!r}")
            spec = spec[key]
        p = Path(spec)
        if not p.is_file():
            raise FileNotFoundError(f"agent JSONL not found: {p}")
        return p

    def _find_jsonl(self, run_dir: Path, agent: dict) -> Path:
        """从 run 产物里取真实 agent JSONL。

        顺序：``agent['trajectory_jsonl']``（run_dir.name 或 task_id 键
        的 dict 或统一路径）→ run_dir 下 ``agent.jsonl`` /
        ``trajectory.jsonl``。找不到直接抛 FileNotFoundError——
        不编造轨迹。
        """
        for name in ("agent.jsonl", "trajectory.jsonl",
                     "raw_log.jsonl"):
            candidate = run_dir / name
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(
            f"no agent JSONL for {run_dir}: provide "
            "executor.trajectory_jsonl or place agent.jsonl in the run dir "
            "(export only accepts real Claude Code JSONL — drafts and "
            "synthetic logs are refused upstream)")

    # ------------------------------------------------------------------
    def cleanup(self, run_dir: Path, cfg: dict) -> None:
        run_dir = Path(run_dir)
        config = common.read_json(run_dir / "config.json")
        container = (config.get("setup_plan") or {}).get("container_name")
        if not container:
            return  # 没有容器可清（如未来非 docker 后端）
        plan = common.build_cleanup_plan(container)
        executor = common.Executor(dry_run=False)
        for step in plan["steps"]:
            for argv in step["docker_argv"]:
                executor.run(argv)


def get_adapter(cfg: dict | None = None) -> SweSkillsBenchAdapter:
    return SweSkillsBenchAdapter()
