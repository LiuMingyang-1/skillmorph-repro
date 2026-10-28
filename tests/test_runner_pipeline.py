"""编排器离线测试：fake 数据集 + fake 方法验证调用顺序/传参/快照/invalid 剔除。

不碰 Docker、不联网、不调真实模型。FakeDataset 是内存实现，按调用记录
顺序供断言；FakeMethod 把一条修订标记写进 output_dir 模拟修订结果。
SkillMorphMethod 的完整链路经 ``with_client``/monkeypatch 注入
pipeline_fixture 的脚本化 fake——全部 LLM 回复预设，产物是
synthetic，不代表真实模型判断。
"""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))  # pipeline_fixture

import runner.pipeline as rp  # noqa: E402
from pipeline_fixture import FakePipelineClient, ABSTRACTIONS_ALL_SUCCESS, \
    RUNS_ALL_SUCCESS  # noqa: E402
from skillmorph.method import SkillMorphMethod  # noqa: E402

PROMPTS = REPO / "experiments/exp_001/prompts"


# ---------------------------------------------------------------------------
# fake DatasetAdapter / Method —— 只实现接口，不模拟 SWE
# ---------------------------------------------------------------------------

class FakeDataset:
    """内存数据集：记录调用序列；execute 按预设表返回 outcome。"""

    def __init__(self, outcomes, traj_doc=None):
        self.calls = []          # [(op, task_id|run_dir, extras)]
        self.outcomes = dict(outcomes)  # run_name -> (outcome, reason)
        self.traj_doc = traj_doc
        self._prepared = {}

    def list_tasks(self, cfg):
        return list(cfg["tasks"])

    def prepare_run(self, task_id, skill_dir, run_dir, cfg):
        self.calls.append(("prepare", task_id, str(skill_dir)))
        run_dir.mkdir(parents=True)
        self._prepared[run_dir.name] = {
            "task_id": task_id, "skill_dir": str(skill_dir)}
        (run_dir / "config.json").write_text(json.dumps(
            {"task_id": task_id, "skill_dir": str(skill_dir)}))
        (run_dir / "run_state.json").write_text(json.dumps(
            {"status": "pending", "task_id": task_id}))

    def execute(self, run_dir, agent):
        run_dir = Path(run_dir)
        task = self._prepared[run_dir.name]["task_id"]
        self.calls.append(("execute", run_dir.name, agent["agent_cmd"]))
        outcome, reason = self.outcomes.get(
            run_dir.name, ("fail", "test_failures"))
        rec = {"outcome": outcome, "reason": reason}
        (run_dir / "evaluation.json").write_text(json.dumps(
            {"task_id": task, "outcome": outcome,
             "outcome_reason": reason}))
        (run_dir / "run_state.json").write_text(json.dumps(
            {"status": "evaluated", "task_id": task}))
        rec["evaluation"] = {"outcome": outcome}
        return rec

    def export_trajectory(self, run_dir, agent):
        run_dir = Path(run_dir)
        self.calls.append(("export", run_dir.name, None))
        outcome, _ = self.outcomes.get(run_dir.name, ("fail", ""))
        if outcome == "invalid" or self.traj_doc is None:
            raise RuntimeError("no valid trajectory available")
        task = self._prepared[run_dir.name]["task_id"]
        return dict(self.traj_doc, task_id=task, run_id=run_dir.name,
                    outcome=outcome)

    def cleanup(self, run_dir, cfg):
        self.calls.append(("cleanup", Path(run_dir).name, None))


class FakeMethod:
    """最小 Method：在 output_dir 写标记文件模拟修订。"""

    def __init__(self):
        self.calls = []

    def revise(self, trajectories, skill_dir, output_dir, cfg):
        self.calls.append((list(trajectories), str(skill_dir),
                           str(output_dir)))
        out = Path(output_dir)
        (out / "skills_after").mkdir(parents=True)
        # 模拟修订后的树：复制输入 + 标记
        shutil.copytree(skill_dir, out / "skills_after",
                        dirs_exist_ok=True)
        (out / "skills_after" / "REVISED.txt").write_text("revised")
        return {"selected": ["act_001"], "rejected": [], "diff": "fake diff",
                "skills_after": str(out / "skills_after")}


def _write_config(tmp_path, tasks, outcomes=None, *, runs_per_task=1,
                  method=None, skill_name="my-skill"):
    exp_in = tmp_path / "in"
    skill = exp_in / "skills"
    (skill / skill_name).mkdir(parents=True)
    (skill / skill_name / "SKILL.md").write_text("# s\n")
    cfg = {
        "name": "e2e",
        "dataset": {"name": "fake", "tasks": tasks,
                    "runs_per_task": runs_per_task},
        "method": method or {"name": "copy"},
        "skill": {"dir": str(skill)},
        "executor": {"agent_cmd": "fake-actor --do-task"},
        "output": {"dir": str(tmp_path / "out")},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    return cfg_path, skill


def test_orchestration_order_and_reset(tmp_path, monkeypatch):
    """before/prepare→execute→export→cleanup → revise →
    after/prepare→execute→cleanup；输入用 skills_before 快照而非源目录。"""
    ds = FakeDataset(
        outcomes={"run_001": ("fail", "test_failures"),
                  "run_002": ("fail", "test_failures")},
        traj_doc={"task": "t", "steps": []})
    method = FakeMethod()
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: method)

    cfg_path, skill = _write_config(tmp_path, ["tA", "tB"])
    summary = rp.run_experiment(cfg_path)

    ops = [(c[0], c[1]) for c in ds.calls]
    # 每个 task 一轮：prepare→execute→export→cleanup；两轮之后才是
    # revise，再两轮 after
    expected_prefix = [("prepare", "tA"), ("execute", "run_001"),
                       ("export", "run_001"), ("cleanup", "run_001"),
                       ("prepare", "tB"), ("execute", "run_002"),
                       ("export", "run_002"), ("cleanup", "run_002")]
    assert ops[:8] == expected_prefix
    # after 阶段不再有 export，只有 prepare/execute/cleanup
    assert ops[8:] == [("prepare", "tA"), ("execute", "run_001"),
                       ("cleanup", "run_001"),
                       ("prepare", "tB"), ("execute", "run_002"),
                       ("cleanup", "run_002")]

    # 方法收到的轨迹数 = 2，输入 skill_dir 是 skills_before 快照
    assert len(method.calls) == 1
    trajs, in_skill, out_dir = method.calls[0]
    assert len(trajs) == 2 and {t["task_id"] for t in trajs} == {"tA", "tB"}
    assert "skills_before" in in_skill and in_skill != str(skill)

    # 所有 prepare（before+after）都用产物内快照，不读源树
    prepares = [c for c in ds.calls if c[0] == "prepare"]
    assert all("skills_before" in c[2] or "skills_after" in c[2]
               for c in prepares)
    after_prepares = prepares[2:]
    assert all("skills_after" in c[2] for c in after_prepares)

    out = tmp_path / "out" / "e2e"
    assert json.loads((out / "comparison.json").read_text()) == {
        "tA": {"before": ["fail"], "after": ["fail"],
               "before_success": 0, "after_success": 0,
               "before_invalid": 0, "after_invalid": 0},
        "tB": {"before": ["fail"], "after": ["fail"],
               "before_success": 0, "after_success": 0,
               "before_invalid": 0, "after_invalid": 0},
    }
    assert (out / "method" / "skills_after" / "REVISED.txt").is_file()
    assert (out / "skills_before" / "my-skill" / "SKILL.md").is_file()
    assert len(list((out / "trajectories").glob("*.json"))) == 2
    assert summary["trajectories_used"] == 2


def test_invalid_run_not_fed_to_method(tmp_path, monkeypatch):
    """数据集明确报告 outcome=invalid 的 run 不进入方法输入，计入 summary。"""
    ds = FakeDataset(
        outcomes={"run_001": ("fail", "test_failures"),
                  "run_002": ("invalid", "docker_disconnect")},
        traj_doc={"task": "t", "steps": []})
    method = FakeMethod()
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: method)

    cfg_path, _ = _write_config(tmp_path, ["tA", "tB"])
    summary = rp.run_experiment(cfg_path)

    trajs = method.calls[0][0]
    assert len(trajs) == 1 and trajs[0]["task_id"] == "tA"
    assert summary["invalid_runs"] == [
        {"task_id": "tB", "run": "run_002", "outcome": "invalid",
         "reason": "docker_disconnect"}]
    assert summary["trajectories_used"] == 1


def test_export_error_raises_after_cleanup(tmp_path, monkeypatch):
    """export_trajectory 抛错（缺真实日志/证据门拒绝）不降级为 invalid：
    cleanup 照常执行，然后原样抛出中断实验。"""
    ds = FakeDataset(
        outcomes={"run_001": ("fail", "test_failures")},
        traj_doc={"task": "t", "steps": []})

    def refused_export(run_dir, agent):
        raise RuntimeError("no agent JSONL — export refused")

    ds.export_trajectory = refused_export
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: FakeMethod())

    cfg_path, _ = _write_config(tmp_path, ["tA"])
    with pytest.raises(RuntimeError, match="export refused"):
        rp.run_experiment(cfg_path)
    # cleanup 仍对本 run 调用（容器不泄漏）；方法从未被调用
    assert ("cleanup", "run_001", None) in ds.calls


def test_execute_bug_raises_after_cleanup(tmp_path, monkeypatch):
    """execute 的未知异常不降级为 invalid：cleanup 照常执行，然后原样抛出。"""
    ds = FakeDataset(outcomes={}, traj_doc={"task": "t", "steps": []})

    def buggy_execute(run_dir, agent):
        raise KeyError("dataset bug: missing evaluation key")

    ds.execute = buggy_execute
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: FakeMethod())

    cfg_path, _ = _write_config(tmp_path, ["tA"])
    with pytest.raises(KeyError, match="dataset bug"):
        rp.run_experiment(cfg_path)
    # cleanup 仍对本 run 调用（容器不泄漏）
    assert ("cleanup", "run_001", None) in ds.calls


def test_cleanup_error_propagates(tmp_path, monkeypatch):
    """cleanup 抛错不吞：明确暴露（资源泄漏不可静默）。"""
    ds = FakeDataset(outcomes={"run_001": ("fail", "test_failures")},
                     traj_doc={"task": "t", "steps": []})

    def bad_cleanup(run_dir, cfg):
        raise RuntimeError("docker rm failed")

    ds.cleanup = bad_cleanup
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: FakeMethod())

    cfg_path, _ = _write_config(tmp_path, ["tA"])
    with pytest.raises(RuntimeError, match="docker rm failed"):
        rp.run_experiment(cfg_path)


def test_skills_before_snapshot_immutable(tmp_path, monkeypatch):
    """before/方法/after 都不依赖源 skill 目录：实验开始后修改源树无影响。"""
    ds = FakeDataset(outcomes={"run_001": ("success", "all_passed")},
                     traj_doc={"task": "t", "steps": []})
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: FakeMethod())

    cfg_path, skill = _write_config(tmp_path, ["tA"])
    original = (skill / "my-skill" / "SKILL.md").read_text()
    rp.run_experiment(cfg_path)
    # 实验结束后改源树——产物内快照不受影响
    (skill / "my-skill" / "SKILL.md").write_text("# mutated\n")
    out = tmp_path / "out" / "e2e"
    assert (out / "skills_before" / "my-skill" / "SKILL.md") \
        .read_text() == original


def test_after_uses_revised_skill_tree(tmp_path, monkeypatch):
    """方法不改树时 after 仍用 skills_after（干净副本），不是原树。"""
    ds = FakeDataset(outcomes={"run_001": ("success", "all_passed"),
                               "run_002": ("success", "all_passed")},
                     traj_doc={"task": "t", "steps": []})

    class NoopMethod:
        def revise(self, trajectories, skill_dir, output_dir, cfg):
            out = Path(output_dir) / "skills_after"
            shutil.copytree(skill_dir, out)
            return {"selected": [], "rejected": [], "diff": "",
                    "skills_after": str(out)}

    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method",
                        lambda cfg, *a, **kw: NoopMethod())
    cfg_path, skill = _write_config(tmp_path, ["tA"])
    rp.run_experiment(cfg_path)

    after_prepares = [c for c in ds.calls if c[0] == "prepare"][1:]
    assert len(after_prepares) == 1
    # 用的是 method/skills_after（distinct dir），内容与原树一致
    used = Path(after_prepares[0][2])
    assert used.name == "skills_after" and "method" in str(used)
    assert (used / "my-skill" / "SKILL.md").read_text() == \
        (skill / "my-skill" / "SKILL.md").read_text()


def test_custom_dataset_module_path(tmp_path):
    """第二个数据集只给 .py 路径：dataset.module 不需要改编排器。"""
    mod = tmp_path / "my_dataset.py"
    mod.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "class A:\n"
        "    def list_tasks(self, cfg):\n"
        "        return cfg.get('tasks') or ['x1']\n"
        "    def prepare_run(self, task_id, skill_dir, run_dir, cfg):\n"
        "        run_dir.mkdir(parents=True)\n"
        "        (run_dir / 'config.json').write_text(\n"
        "            json.dumps({'task_id': task_id}))\n"
        "    def execute(self, run_dir, agent):\n"
        "        return {'outcome': 'fail', 'reason': 'boom'}\n"
        "    def export_trajectory(self, run_dir, agent):\n"
        "        return {'task_id': 'x1', 'run_id': Path(run_dir).name,\n"
        "                'task': 't', 'outcome': 'fail', 'steps': []}\n"
        "    def cleanup(self, run_dir, cfg):\n"
        "        pass\n"
        "def get_adapter(cfg):\n"
        "    return A()\n")
    cfg = {
        "name": "e2e",
        "dataset": {"module": "my_dataset.py", "tasks": ["x1"]},
        "method": {"name": "copy"},
        "skill": {"dir": "skills"},
        "executor": {"agent_cmd": "x"},
        "output": {"dir": "out"},
    }
    (tmp_path / "skills" / "s").mkdir(parents=True)
    (tmp_path / "skills" / "s" / "SKILL.md").write_text("# s\n")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    summary = rp.run_experiment(cfg_path)
    assert summary["dataset"] == "my_dataset.py"
    assert summary["trajectories_used"] == 1
    assert summary["comparison"]["x1"]["after"] == ["fail"]


def test_custom_method_module_path(tmp_path, monkeypatch):
    """第二个方法只给 .py 路径：method.module 不需要改编排器。"""
    mod = tmp_path / "my_method.py"
    mod.write_text(
        "import shutil\n"
        "from pathlib import Path\n"
        "class M:\n"
        "    def revise(self, trajectories, skill_dir, output_dir, cfg):\n"
        "        out = Path(output_dir) / 'skills_after'\n"
        "        shutil.copytree(skill_dir, out)\n"
        "        (out / 'TAG').write_text('custom')\n"
        "        return {'selected': [], 'rejected': [], 'diff': '',\n"
        "                'skills_after': str(out)}\n"
        "def get_method(cfg):\n"
        "    return M()\n")
    ds = FakeDataset(outcomes={"run_001": ("fail", "t"),
                               "run_002": ("fail", "t")},
                     traj_doc={"task": "t", "steps": []})
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)

    cfg_path, _ = _write_config(
        tmp_path, ["tA"], method={"module": "my_method.py"})
    summary = rp.run_experiment(cfg_path)
    out = tmp_path / "out" / "e2e"
    assert (out / "method" / "skills_after" / "TAG").read_text() == "custom"
    assert summary["comparison"]["tA"]["after"] == ["fail"]


def test_swe_adapter_loads_and_lists_tasks(monkeypatch):
    """真实 SWE adapter 的 list_tasks：family 过滤 + ready 白名单。"""
    adapter = rp.load_dataset_adapter("swe_skills_bench")
    tasks = adapter.list_tasks({})
    assert "tdd-workflow-batch1" in tasks
    # 非 ready 任务（batch9 unsuitable / batch10 pending）不出现
    assert "tdd-workflow-batch9" not in tasks
    assert "tdd-workflow-batch10" not in tasks
    filtered = adapter.list_tasks({"task_families": ["coupon_calculator"]})
    assert filtered == ["tdd-workflow-batch1"]


def test_skillmorph_method_end_to_end_offline(tmp_path):
    """SkillMorphMethod.revise：全成功轨迹 → 无可疑动作 → 干净复制。"""
    method = SkillMorphMethod.with_client(
        FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))
    skill_dir = tmp_path / "skills"
    (skill_dir / "sqlite-memory" / "reference").mkdir(parents=True)
    (skill_dir / "sqlite-memory" / "SKILL.md").write_text("# m\n")
    (skill_dir / "sqlite-memory" / "reference" / "db.md").write_text("x\n")
    out = tmp_path / "out"
    result = method.revise(RUNS_ALL_SUCCESS, skill_dir, out,
                           {"prompt_dir": PROMPTS})

    assert result["selected"] == [] and result["diff"] == ""
    after = Path(result["skills_after"])
    assert (after / "sqlite-memory" / "SKILL.md").read_text() == "# m\n"
    assert (out / "analysis" / "ranking.json").is_file()
    assert (out / "revision" / "proposals.json").is_file()


def test_skillmorph_method_revision_applied_offline(tmp_path):
    """SkillMorphMethod 完整链路：fixture client → 选提案 → 改文件 →
    skills_after 含新内容（输入树不变）。"""
    import pipeline_fixture as fx
    method = SkillMorphMethod.with_client(
        FakePipelineClient(fx.ABSTRACTIONS))
    skill_dir = tmp_path / "skills"
    ref = skill_dir / "sqlite-memory" / "reference"
    ref.mkdir(parents=True)
    (skill_dir / "sqlite-memory" / "SKILL.md").write_text(fx.SKILL_MD)
    (ref / "connections.md").write_text(fx.DB_MD)
    before_snapshot = fx.tree_snapshot(skill_dir)

    out = tmp_path / "out"
    result = method.revise(fx.RUNS, skill_dir, out,
                           {"prompt_dir": PROMPTS})

    assert result["selected"], "expected a selected proposal"
    assert result["diff"], "expected a non-empty diff"
    after = Path(result["skills_after"])
    assert (after / "sqlite-memory" / "reference" / "connections.md") \
        .read_text() == fx.NEW_DB_MD
    # 输入树不被修改
    assert fx.tree_snapshot(skill_dir) == before_snapshot


def test_runner_skillmorph_fixture_end_to_end(tmp_path, monkeypatch):
    """Runner + SkillMorphMethod（with_client 注入脚本化 fake）完整
    编排：轨迹→修订→after 用 skills_after。"""
    import pipeline_fixture as fx
    ds = FakeDataset(outcomes={"run_001": ("fail", "t"),
                               "run_002": ("fail", "t"),
                               "run_003": ("fail", "t"),
                               "run_004": ("fail", "t")},
                     traj_doc=None)
    # 每条轨迹用 fixture RUNS 的一条（含 steps/outcome/task_id）
    runs = list(fx.RUNS)
    seq = iter(runs)

    def export(run_dir, agent):
        run = next(seq)
        return dict(run, run_id=Path(run_dir).name)

    ds.export_trajectory = export
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    # fake 分析/修订客户端经方法工厂注入（生产路径是 "env"）
    method = SkillMorphMethod.with_client(
        FakePipelineClient(fx.ABSTRACTIONS))
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: method)

    cfg_path, _ = _write_config(
        tmp_path, ["t1", "t2"], runs_per_task=2,
        method={"name": "skillmorph", "prompt_dir": str(PROMPTS)},
        skill_name="sqlite-memory")
    # fixture 期望 skill 树是 sqlite-memory + reference/connections.md
    skill = tmp_path / "in" / "skills" / "sqlite-memory"
    (skill / "reference").mkdir(parents=True)
    (skill / "SKILL.md").write_text(fx.SKILL_MD)
    (skill / "reference" / "connections.md").write_text(fx.DB_MD)

    summary = rp.run_experiment(cfg_path)

    out = tmp_path / "out" / "e2e"
    after_skill = out / "method" / "skills_after" / "sqlite-memory"
    assert (after_skill / "reference" / "connections.md").read_text() \
        == fx.NEW_DB_MD
    # after 的 prepare 用的是修订后的树（4 个 before run 之后）
    after_prepares = [c for c in ds.calls if c[0] == "prepare"][4:]
    assert all("skills_after" in c[2] for c in after_prepares)
    # 原始快照未被方法修改
    assert (out / "skills_before" / "sqlite-memory" / "reference"
            / "connections.md").read_text() == fx.DB_MD
    assert summary["trajectories_used"] == 4
    assert summary["method_summary"]["selected"]


def test_output_dir_collision_refused(tmp_path, monkeypatch):
    """已存在的实验输出目录直接拒绝，不覆盖已有产物。"""
    ds = FakeDataset(outcomes={"run_001": ("fail", "t"),
                               "run_002": ("fail", "t")},
                     traj_doc={"task": "t", "steps": []})
    monkeypatch.setattr(rp, "load_dataset_adapter", lambda name, base=None: ds)
    monkeypatch.setattr(rp, "build_method", lambda cfg, *a, **kw: FakeMethod())
    cfg_path, _ = _write_config(tmp_path, ["tA"])
    rp.run_experiment(cfg_path)
    with pytest.raises(FileExistsError):
        rp.run_experiment(cfg_path)


def test_existing_skillmorph_cli_compatible(tmp_path):
    """原 CLI 入口不变：experiment_dir + data/trajectories.json 仍可用。"""
    import shutil as sh
    from pipeline_fixture import make_experiment
    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    summary = __import__("skillmorph.pipeline", fromlist=["x"]) \
        .run_experiment(exp, client=FakePipelineClient(
            ABSTRACTIONS_ALL_SUCCESS))
    assert summary["run"] == "run_001"
    assert summary["diff_empty"] is True


def test_run_experiment_explicit_trajectories(tmp_path):
    """小重构入口：显式 trajectories 不再要求 data/ 文件。"""
    from skillmorph.pipeline import run_experiment
    from pipeline_fixture import make_experiment
    exp = tmp_path / "exp"
    (exp / "skills" / "sqlite-memory" / "reference").mkdir(parents=True)
    (exp / "skills" / "sqlite-memory" / "SKILL.md").write_text("# m\n")
    (exp / "skills" / "sqlite-memory" / "reference" / "db.md").write_text("x\n")
    sh = __import__("shutil")
    sh.copytree(PROMPTS, exp / "prompts")
    summary = run_experiment(
        exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS),
        trajectories=RUNS_ALL_SUCCESS)
    assert summary["runs"] == 2
    assert (exp / "runs" / "run_001" / "analysis" /
            "summary.json").is_file()
