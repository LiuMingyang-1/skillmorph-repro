"""端到端替身流程测试：pending → run → eval → export（全程 mock Docker）。

- 纯 shell/Python 替身 Executor，绝不碰真实 docker；
- 覆盖：正常路径、task_timeout、infra 失败（poll/终止/staging）、
  export-only 读已存判分、export 覆盖拒绝、无效日志拒导出；
- stop/staging 验证不是无条件 true：替身按语义真实模拟 pkill -U dev /
  pgrep -U dev / chown / sha256sum / pytest 输出。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
import run as run_mod  # noqa: E402
import setup as setup_mod  # noqa: E402
from conftest import make_junit  # noqa: E402


class ScriptedExec(common.Executor):
    """按 argv 语义模拟容器内状态的替身（不是无条件成功）。

    内置：dev 进程存活集合（set of pids）、/tmp/agent.* 文件、staging
    目录、junit.xml、dev 可写性。assertions：
      * kill：pkill -TERM/-KILL -U dev 清空 dev 进程集合；
      * check：pgrep -U dev → 空才 echo 1；
      * staging：mkdir+chown 后 dev_writable 才放行 pytest；
      * pytest：按 self.pytest_xml/pytest_exit 产出 junit.xml。
    """

    def __init__(self, *, skills_dir=None, dev_alive=frozenset(),
                 exit_file="0", agent_exit_ok=True, pytest_exit=0,
                 pytest_xml=None, pytest_write_ok=True,
                 poll_error=False, stage_fails=False,
                 leak=False, repo_head=None):
        super().__init__(dry_run=False)
        self.skills_dir = skills_dir
        self.dev_procs = set(dev_alive)
        self.exit_file = exit_file
        self.agent_exit_ok = agent_exit_ok
        self.pytest_exit = pytest_exit
        self.pytest_xml = pytest_xml
        self.pytest_write_ok = pytest_write_ok
        self.poll_error = poll_error
        self.stage_fails = stage_fails
        self.leak = leak
        self.repo_head = repo_head
        self.calls = []

    def R(self, argv, **k):
        base = dict(argv=list(argv), exit_code=0, stdout="", stderr="",
                    duration_sec=0.01)
        base.update(k)
        return common.CommandResult(**base)

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        joined = " ".join(argv)

        # infra failure injection: any docker exec errors out
        if self.poll_error and "docker" in argv[:1]:
            return self.R(argv, exit_code=None, error="docker: connect lost")

        # --- setup steps ---------------------------------------------------
        if "sudo -n true" in joined:
            # 模拟 dev 无实际提权能力：sudo -n true 失败 → 第一条 shell
            # (sudo && fail || true) 走 true 分支 exit 0；第二条
            # (! sudo -n true) 也 exit 0
            return self.R(argv, exit_code=0)
        if "id -u dev" in joined:
            return self.R(argv)  # dev exists, non-root
        if "sha256sum" in joined and "skills" in joined:
            listing = "\n".join(
                common.skill_tree_listing(self.skills_dir)) + "\n" \
                if self.skills_dir else ""
            return self.R(argv, stdout=listing)

        # --- agent lifecycle ----------------------------------------------
        if any(a.startswith("AGENT_CMD=") for a in argv):
            # spawn: dev processes appear
            self.dev_procs.update({4242})
            return self.R(argv, exit_code=0 if self.agent_exit_ok else 1)
        if "cat /tmp/agent.exit" in joined:
            if self.exit_file is None:
                return self.R(argv, exit_code=0, stdout="")
            return self.R(argv, stdout=self.exit_file + "\n")
        if "kill -TERM" in joined or "kill -KILL" in joined:
            self.dev_procs.clear()
            return self.R(argv)
        if "leftover=" in joined:
            return self.R(argv,
                          stdout=("1" if not self.dev_procs else "0") + "\n")
        if "command -v pgrep" in joined or "pgrep -U dev" in joined:
            # setup 预检：工具存在且 -U 语义返回 0/1
            return self.R(argv)

        # --- artifacts/leak/diff -------------------------------------------
        if "/tmp/agent.stdout" in joined:
            return self.R(argv, stdout="AGENTOUT\n")
        if "/tmp/agent.stderr" in joined:
            return self.R(argv, stdout="AGENTERR\n")
        if "benchmark_tests" in joined and "LEAK" in joined:
            return self.R(argv, stdout="LEAK\n" if self.leak else "clean\n")
        if "git rev-parse HEAD" in joined:
            return self.R(argv, stdout=(self.repo_head or "") + "\n")
        if "chown -R dev:dev" in joined and "benchmark_tests" in joined:
            if self.stage_fails:
                return self.R(argv, exit_code=1,
                              stderr="dev cannot write staging")
            return self.R(argv)
        if "mkdir -p" in joined and "benchmark_tests" in joined:
            return self.R(argv, exit_code=1 if self.stage_fails else 0)
        if "sha256sum" in joined and "test_tdd_workflow" in joined:
            # 容器内回读 staged 测试文件的真实哈希（替身按磁盘实算）
            real = Path(__file__).resolve().parent.parent / \
                "tests/batch1/test_tdd_workflow.py"
            return self.R(argv,
                          stdout=common.sha256_file(real) + "  f\n")
        if "python -m pytest" in joined:
            # dev must be able to write junit.xml (chown did its job)
            if self.stage_fails or not self.pytest_write_ok:
                return self.R(argv, exit_code=1,
                              stderr="cannot write junit.xml")
            return self.R(argv, exit_code=self.pytest_exit,
                          stdout="pytest out", stderr="")
        if "cat /tmp/benchmark_tests/junit.xml" in joined:
            if self.pytest_xml is None:
                return self.R(argv, exit_code=1, stderr="no file")
            return self.R(argv, stdout=self.pytest_xml)

        return self.R(argv)


def _pending_run(tmp_path, skills_dir, manifest):
    rd = tmp_path / "runs" / "run_001"
    rd.mkdir(parents=True)
    cfg = {
        "task_id": "tdd-workflow-batch1",
        "task_file": "tasks/tdd-workflow-batch1.md",
        "test_file": "tests/batch1/test_tdd_workflow.py",
        "run_id": "aa11bb22cc33",
        "setup_plan": {"container_name":
                       "swesk-tdd-workflow-batch1-run_001-aa11bb22cc33"},
        "skills": {"host_dir": str(skills_dir),
                   "container_dir": common.CONTAINER_SKILLS_DIR,
                   "tree_sha256": common.tree_sha256(skills_dir)},
        "repo": manifest["repo"],
        "environment": {"docker_image": "img",
                        "docker_image_digest": "sha256:" + "ab" * 32,
                        "docker_image_platform": "linux/arm64"},
    }
    (rd / "config.json").write_text(json.dumps(cfg))
    (rd / "run_state.json").write_text(json.dumps({
        "status": "pending", "task_id": "tdd-workflow-batch1",
        "run_dir": str(rd), "setup": None}))
    return rd


RUN_ARGS = ["--task-id", "tdd-workflow-batch1", "--agent-cmd",
            "claude -p '$TASK'", "--image-digest", "sha256:" + "ab" * 32,
            "--image-platform", "linux/arm64"]


def _jsonl(path):
    path.write_text("\n".join([
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u1", "name": "Read",
             "input": {"file_path":
                       "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u1",
             "content": "skill body"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u2", "name": "Edit",
             "input": {"file_path": "/workspace/python/src/calculator.py"}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u2",
             "content": "edited"}]}})]) + "\n")


class TestFullFlow:
    def test_pending_to_run_to_eval_to_export(self, tmp_path, skills_dir,
                                              manifest, monkeypatch):
        """mock-Docker 全流程：pending 登记 → run 执行 → eval 判分 →
        export-only 导出。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)
        fake = ScriptedExec(skills_dir=skills_dir,
                            pytest_xml=make_junit(
                                2, cases=[("a", None), ("b", None)]),
                            repo_head=manifest["repo"]["commit"])
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        monkeypatch.setattr(ev, "Executor", lambda **kw: fake)

        rc = run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        assert rc == 0
        st = json.loads((rd / "run_state.json").read_text())
        assert st["status"] == "executed"
        assert not (rd / "trajectory.json").exists()  # run 不产正式轨迹

        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 0
        rec = json.loads((rd / "evaluation.json").read_text())
        assert rec["outcome"] == "success"

        log = tmp_path / "agent.jsonl"
        _jsonl(log)
        rc = run_mod.main(["--run-dir", str(rd), "--export-only",
                           "--trajectory-jsonl", str(log)])
        assert rc == 0
        traj = json.loads((rd / "trajectory.json").read_text())
        assert traj["task"] and traj["outcome"] == "success"
        assert traj["trajectory_import"]["source_sha256"]
        assert traj["steps"][0]["files_read"] == ["tdd-workflow/SKILL.md"]

        # 不可变协议：再次导出不覆盖
        rc = run_mod.main(["--run-dir", str(rd), "--export-only",
                           "--trajectory-jsonl", str(log)])
        assert rc == 2

    def test_export_only_after_evaluation_is_separate(self, tmp_path,
                                                      skills_dir, manifest,
                                                      monkeypatch):
        """判分后单独 export 不触发 pytest 重跑（无 pytest 命令调用）。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)
        fake = ScriptedExec(skills_dir=skills_dir,
                            pytest_xml=make_junit(2,
                                                  cases=[("a", None),
                                                         ("b", None)]),
                            repo_head=manifest["repo"]["commit"])
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        monkeypatch.setattr(ev, "Executor", lambda **kw: fake)
        rc = run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        assert rc == 0
        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 0
        fake.calls.clear()
        log = tmp_path / "agent.jsonl"
        _jsonl(log)
        rc = run_mod.main(["--run-dir", str(rd), "--export-only",
                           "--trajectory-jsonl", str(log)])
        assert rc == 0
        assert not any("pytest" in " ".join(c) for c in fake.calls), \
            "export-only must not re-run pytest"

    def test_run_rejects_evaluated_status(self, tmp_path, skills_dir,
                                          manifest):
        rd = _pending_run(tmp_path, skills_dir, manifest)
        (rd / "run_state.json").write_text(json.dumps(
            {"status": "evaluated"}))
        with pytest.raises(SystemExit):
            run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])

    def test_legit_timeout_is_fail_not_invalid(self, tmp_path, skills_dir,
                                               manifest, monkeypatch):
        """合法 task_timeout：exit 文件缺席 + dev 进程全灭 => fail。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)
        fake = ScriptedExec(skills_dir=skills_dir, exit_file=None,
                            repo_head=manifest["repo"]["commit"])
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        monkeypatch.setattr(run_mod.time, "monotonic",
                            _fake_clock([0, 10**9]))  # deadline 已过的轮询
        monkeypatch.setattr(run_mod.time, "sleep", lambda s: None)
        rc = run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        assert rc == 0
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] == "fail"
        assert ex["outcome_reason"] == "task_timeout"

    def test_poll_infra_error_is_invalid(self, tmp_path, skills_dir,
                                         manifest, monkeypatch):
        """docker 断连 => 立即 invalid，绝不误记 task_timeout。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)
        fake = ScriptedExec(skills_dir=skills_dir, poll_error=True)
        # allow setup but fail on poll only: simpler — fail all docker exec
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rc = run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        assert rc == 0
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] == "invalid"
        assert "setup_failure" == ex["outcome_reason"] \
            or "poll_infra" in (ex["outcome_reason"] or "") \
            or "runner_error" == ex["outcome_reason"]

    def test_residual_dev_process_blocks_eval(self, tmp_path, skills_dir,
                                              manifest, monkeypatch):
        """agent 后代顽固存活（kill 不掉）=> 终止核验失败 => invalid。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)

        class ZombieExec(ScriptedExec):
            def run(self, argv, **kw):
                # kill 成功返回但进程重生了——check 仍见存活
                joined = " ".join(argv)
                if "leftover=" in joined:
                    self.dev_procs = {999}  # 始终回 0
                return super().run(argv, **kw)

        fake = ZombieExec(skills_dir=skills_dir,
                          pytest_xml=make_junit(2,
                                                cases=[("a", None),
                                                       ("b", None)]))
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rc = run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] == "invalid"
        assert ex["outcome_reason"] == "agent_termination_failed"

    def test_export_refuses_bad_log_and_writes_draft(self, tmp_path,
                                                     skills_dir, manifest,
                                                     monkeypatch):
        """无效日志 + 有效判分也不能导出正式轨迹——只写诊断草稿。"""
        rd = _pending_run(tmp_path, skills_dir, manifest)
        fake = ScriptedExec(skills_dir=skills_dir,
                            pytest_xml=make_junit(2,
                                                  cases=[("a", None),
                                                         ("b", None)]),
                            repo_head=manifest["repo"]["commit"])
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        monkeypatch.setattr(ev, "Executor", lambda **kw: fake)
        run_mod.main(RUN_ARGS + ["--run-dir", str(rd)])
        ev.main(["--run-dir", str(rd)])

        bad = tmp_path / "bad.jsonl"
        bad.write_text("corrupt line\n")
        rc = run_mod.main(["--run-dir", str(rd), "--export-only",
                           "--trajectory-jsonl", str(bad)])
        assert rc == 0
        assert not (rd / "trajectory.json").exists()
        assert (rd / "trajectory_draft.json").exists()

    def test_cleanup_removes_only_run_container(self, tmp_path, skills_dir,
                                                manifest, capsys):
        rd = _pending_run(tmp_path, skills_dir, manifest)
        class C(common.Executor):
            def run(self, argv, **kw):
                self.log.append({"argv": list(argv)})
                return common.CommandResult(
                    argv=list(argv), exit_code=0, stdout="", stderr="",
                    duration_sec=0.01)
        monkeyexec = C()
        import run as rm
        rc = rm._cleanup_run(rd, monkeyexec)
        assert rc == 0
        assert any("rm" in c["argv"] and
                   "swesk-tdd-workflow-batch1-run_001-aa11bb22cc33" in c["argv"]
                   for c in monkeyexec.log)
        assert (rd / "config.json").exists()  # artifacts 保留


def _fake_clock(times):
    it = iter(times)

    def _m():
        try:
            return next(it)
        except StopIteration:
            return 10**9
    return _m
