"""setup.py/run.py 测试：登记、计划、dry-run 无副作用、命令结构、轨迹导入。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
import run as run_mod  # noqa: E402
import setup as setup_mod  # noqa: E402
from common import CONTAINER_TEST_STAGING  # noqa: E402


def _flat_docker_commands(plan):
    """计划里所有将以 argv 形式执行的 docker 命令（host 侧 + exec 包装）。"""
    cmds = []
    for step in plan["steps"]:
        for argv in step.get("docker_argv", []):
            cmds.append(argv)
        for shell in step.get("container_shell", []):
            cmds.append(common.docker_exec_argv(plan["container_name"], shell))
    return cmds


class TestSetup:
    def test_dry_run_creates_nothing(self, tmp_path, skills_dir, capsys):
        out_root = tmp_path / "runs"
        rc = setup_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(out_root),
            "--dry-run",
        ])
        assert rc == 0
        assert not out_root.exists()
        plan = json.loads(capsys.readouterr().out)
        assert "config" in plan and "setup_plan" in plan["config"]

    def test_dry_run_marks_unrunnable_but_allowed(self, tmp_path, skills_dir,
                                                  capsys):
        rc = setup_mod.main([
            "--task-id", "tdd-workflow-batch9",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
            "--dry-run",
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["config"]["task_runnable"] is False

    def test_real_run_refuses_unrunnable_task(self, tmp_path, skills_dir):
        rc = setup_mod.main([
            "--task-id", "tdd-workflow-batch9",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
        ])
        assert rc == 2
        assert not (tmp_path / "runs").exists()

    def test_real_registers_run_dir(self, tmp_path, skills_dir):
        out_root = tmp_path / "runs"
        rc = setup_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(out_root),
        ])
        assert rc == 0
        run_dir = out_root / "run_001"
        cfg = json.loads((run_dir / "config.json").read_text())
        assert cfg["task_id"] == "tdd-workflow-batch1"
        state = json.loads((run_dir / "run_state.json").read_text())
        assert state["status"] == "pending"
        assert cfg["environment"]["docker_image_digest"] is None

    def test_empty_skills_dir_rejected(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        rc = setup_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(empty),
            "--output-dir", str(tmp_path / "runs"),
        ])
        assert rc == 2

    def test_plan_commands_are_argv_lists_not_chars(self, manifest, skills_dir):
        """计划里的每条命令必须是 argv list，不得是字符串。"""
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "deadbeef", "run_001")
        for cmd in _flat_docker_commands(plan):
            assert isinstance(cmd, list), f"command is not argv list: {cmd!r}"
            assert all(isinstance(a, str) for a in cmd)
            assert cmd[0] == "docker", f"argv does not start with docker: {cmd}"
            assert len(cmd[1]) > 1, f"argv[1] looks like a char: {cmd}"

    def test_create_start_exec_cp_sequence(self, manifest, skills_dir):
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "deadbeef", "run_007")
        host_cmds = [c for c in _flat_docker_commands(plan)]
        kinds = [c[1] for c in host_cmds]
        # rm -f → create → start → exec* → cp → exec*
        assert "create" in kinds and "start" in kinds and "cp" in kinds
        assert kinds.index("rm") < kinds.index("create") < kinds.index("start")
        assert kinds.index("cp") > kinds.index("start")
        create = next(c for c in host_cmds if c[1] == "create")
        assert "--name" in create
        name = create[create.index("--name") + 1]
        assert name.endswith("run_007"), "container must be run-scoped"
        assert "--entrypoint" in create, "keepalive entrypoint must be explicit"

    def test_pinned_image_and_platform_in_create(self, manifest, skills_dir):
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        env = {"docker_image": "img/name",
               "docker_image_digest": "sha256:" + "ab" * 32,
               "docker_image_platform": "linux/amd64"}
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "h", "run_001", env)
        create = next(c for c in _flat_docker_commands(plan)
                      if c[1] == "create")
        assert "img/name@sha256:" + "ab" * 32 in create
        assert "--platform" in create
        assert create[create.index("--platform") + 1] == "linux/amd64"

    def test_clone_refuses_nonempty_and_verifies_head(self, manifest,
                                                      skills_dir):
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "h", "run_001")
        shells = [s for step in plan["steps"]
                  for s in step.get("container_shell", [])]
        assert any("refusing to clone into non-empty" in s for s in shells)
        assert any("git fetch --depth 1" in s
                   and manifest["repo"]["commit"] in s for s in shells)
        assert any("rev-parse HEAD" in s and manifest["repo"]["commit"] in s
                   for s in shells)
        assert any(".claude" in s and "rm -rf" in s for s in shells)

    def test_skill_injection_verified_in_container(self, manifest, skills_dir):
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "h", "run_001")
        inject = next(s for s in plan["steps"] if s["name"] == "inject_skill")
        assert inject["verify"]["kind"] == "file_listing_sha256"
        assert inject["container_shell"], \
            "container-side listing must be planned"

    def test_ownership_fix_step_present(self, manifest, skills_dir):
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        plan = setup_mod.build_setup_plan(manifest, task, skills_dir,
                                          "h", "run_001")
        own = next(s for s in plan["steps"] if s["name"] == "fix_ownership")
        assert any("chown -R dev" in c for c in own["container_shell"])
        assert any("test -w" in c for c in own["container_shell"])


class TestRunDryRun:
    def test_no_side_effects_and_no_test_leak(self, tmp_path, skills_dir,
                                              capsys):
        out_root = tmp_path / "runs"
        rc = run_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(out_root),
            "--agent-cmd", "claude -p '$TASK'",
            "--dry-run",
        ])
        assert rc == 0
        assert not out_root.exists()
        out = json.loads(capsys.readouterr().out)
        assert out["no_side_effects"] is True
        all_cmds = json.dumps(out["commands"])
        assert CONTAINER_TEST_STAGING in all_cmds

    def test_dry_run_commands_are_argv_lists(self, tmp_path, skills_dir,
                                             capsys):
        rc = run_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
            "--agent-cmd", "claude -p '$TASK'",
            "--dry-run",
        ])
        out = json.loads(capsys.readouterr().out)
        for entry in out["commands"]:
            argv = entry["argv"]
            assert isinstance(argv, list)
            assert argv[0] == "docker"
            assert len(argv) >= 2 and len(argv[1]) > 1

    def test_dry_run_task_passed_via_env_not_prefix(self, tmp_path, skills_dir,
                                                    capsys):
        """TASK 必须经 docker exec --env 传入，不做宿主侧 TASK=... 前缀赋值。"""
        rc = run_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
            "--agent-cmd", "claude -p \"$TASK\"",
            "--dry-run",
        ])
        out = json.loads(capsys.readouterr().out)
        agent_entries = [e for e in out["commands"]
                         if "--env" in e["argv"]]
        assert agent_entries, "agent launch must use docker exec --env"
        envs = [a for e in agent_entries for a in e["argv"]
                if a.startswith("TASK=")]
        assert envs, "TASK must be passed as --env TASK=..."
        assert "Smart Coupon Calculator" in envs[0], \
            "task text must actually reach the command"
        # 不得以 TASK='...' 前缀形式拼进 shell 字符串
        for e in agent_entries:
            shell = e["argv"][-1]
            assert not shell.startswith("TASK=")

    def test_requires_agent_cmd(self, tmp_path, skills_dir):
        with pytest.raises(SystemExit):
            run_mod.main([
                "--task-id", "tdd-workflow-batch1",
                "--skills-dir", str(skills_dir),
                "--output-dir", str(tmp_path / "runs"),
            ])

    def test_real_run_requires_image_digest(self, tmp_path, skills_dir):
        rc = run_mod.main([
            "--task-id", "tdd-workflow-batch1",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
            "--agent-cmd", "claude -p '$TASK'",
        ])
        assert rc == 2  # 无 --image-digest → 拒绝浮动 tag 真实执行

    def test_real_run_refuses_unrunnable_task(self, tmp_path, skills_dir):
        rc = run_mod.main([
            "--task-id", "tdd-workflow-batch9",
            "--skills-dir", str(skills_dir),
            "--output-dir", str(tmp_path / "runs"),
            "--agent-cmd", "claude -p '$TASK'",
            "--image-digest", "sha256:" + "ab" * 32,
        ])
        assert rc == 2


class _FakeExec(common.Executor):
    """可脚本化的 Executor：按 argv 内容分派出结果，记录全部调用。"""

    def __init__(self, agent_exit=0, agent_exit_code_file="0",
                 dead=True, listing=None):
        super().__init__(dry_run=False)
        self.agent_exit = agent_exit
        self.agent_exit_code_file = agent_exit_code_file
        self.dead = dead
        self.listing = listing
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))

        def R(**k):
            base = dict(argv=list(argv), exit_code=0, stdout="", stderr="",
                        duration_sec=0.01)
            base.update(k)
            return common.CommandResult(**base)
        joined = " ".join(argv)
        if any(a.startswith("AGENT_CMD=") for a in argv):
            return R(exit_code=self.agent_exit)
        if "pkill -TERM -U dev" in joined or "pkill -KILL -U dev" in joined:
            return R(exit_code=0)
        if "pgrep -U dev" in joined and "echo $dead" in joined:
            return R(exit_code=0,
                     stdout=("1" if self.dead else "0") + "\n")
        if "cat /tmp/agent.exit" in joined or "test -f /tmp/agent.exit" in joined:
            return R(exit_code=0, stdout=self.agent_exit_code_file + "\n")
        if "rev-parse HEAD" in joined:
            return R(exit_code=0,
                     stdout=getattr(self, "head", "") + "\n")
        if "sha256sum" in joined and "skills" in joined:
            listing = self.listing
            if listing is None:
                host = getattr(self, "skills_host", None)
                listing = "\n".join(common.skill_tree_listing(host)) + "\n" \
                    if host else ""
            return R(exit_code=0, stdout=listing)
        if "/tmp/agent.stdout" in joined:
            return R(exit_code=0, stdout="AGENTOUT\n")
        if "/tmp/agent.stderr" in joined:
            return R(exit_code=0, stdout="AGENTERR\n")
        if "benchmark_tests" in joined:
            return R(exit_code=0, stdout="clean\n")
        if "pgrep -U dev" in joined and "case $rc" in joined:
            return R(exit_code=0,
                     stdout=("1" if self.dead else "0") + "\n")
        if "command -v pgrep" in joined or "pgrep -U dev" in joined:
            return R(exit_code=0)
        return R(exit_code=0)


class TestRunExecution:
    def _run_dir(self, tmp_path, skills_dir, manifest, status="pending"):
        rd = tmp_path / "runs" / "run_001"
        rd.mkdir(parents=True)
        cfg = {
            "task_id": "tdd-workflow-batch1",
            "run_id": "aa11bb22cc33",
            "setup_plan": {"container_name":
                           "swesk-tdd-workflow-batch1-run_001-aa11bb22cc33"},
            "skills": {"host_dir": str(skills_dir),
                       "container_dir": "/home/dev/.claude/skills",
                       "tree_sha256": common.tree_sha256(skills_dir)},
            "repo": manifest["repo"],
        }
        (rd / "config.json").write_text(json.dumps(cfg))
        (rd / "run_state.json").write_text(json.dumps(
            {"status": status, "task_id": "tdd-workflow-batch1"}))
        return rd

    def _args(self, rd):
        return [
            "--task-id", "tdd-workflow-batch1",
            "--run-dir", str(rd),
            "--agent-cmd", "claude -p '$TASK'",
            "--image-digest", "sha256:" + "ab" * 32,
            "--image-platform", "linux/arm64",
        ]

    def _fake(self, skills_dir, **kw):
        fake = _FakeExec(**kw)
        fake.skills_host = skills_dir
        return fake

    def test_runner_error_marks_invalid(self, tmp_path, skills_dir, manifest,
                                        monkeypatch):
        fake = self._fake(skills_dir, agent_exit=1)
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        rc = run_mod.main(self._args(rd))
        assert rc == 0
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] == "invalid"
        assert ex["outcome_reason"] == "runner_error"

    def test_agent_termination_failure_marks_invalid(self, tmp_path,
                                                     skills_dir, manifest,
                                                     monkeypatch):
        fake = self._fake(skills_dir, dead=False)
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        rc = run_mod.main(self._args(rd))
        assert rc == 0
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] == "invalid"
        assert ex["outcome_reason"] == "agent_termination_failed"

    def test_success_path_executed(self, tmp_path, skills_dir, manifest,
                                   monkeypatch):
        fake = self._fake(skills_dir, dead=True)
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        rc = run_mod.main(self._args(rd))
        assert rc == 0
        st = json.loads((rd / "run_state.json").read_text())
        assert st["status"] == "executed"
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["outcome"] is None  # 等判分
        # 完整 stdout/stderr 应落 raw_log，不只 tail
        raw = json.loads((rd / "raw_log.json").read_text())
        assert raw["agent_stdout"] == "AGENTOUT\n"

    def test_run_dir_overwrite_refused(self, tmp_path, skills_dir, manifest):
        """已执行/已判分 run 目录禁止被 --run-dir 覆盖。"""
        for st in ("executed", "evaluated", "running"):
            rd = self._run_dir(tmp_path, skills_dir, manifest, status=st)
            with pytest.raises(SystemExit):
                run_mod.main(self._args(rd))
            import shutil
            shutil.rmtree(rd)

    def test_task_mismatch_refused(self, tmp_path, skills_dir, manifest):
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        cfg = json.loads((rd / "config.json").read_text())
        cfg["task_id"] = "tdd-workflow-batch3"
        (rd / "config.json").write_text(json.dumps(cfg))
        with pytest.raises(SystemExit):
            run_mod.main(self._args(rd))

    def test_config_written_running_before_docker(self, tmp_path, skills_dir,
                                                  manifest, monkeypatch):
        """run 开始前即落盘完整 config+running（mutation 前持久化）。"""
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        fake = self._fake(skills_dir, dead=True)
        monkeypatch.setattr(run_mod, "Executor", lambda **kw: fake)
        rc = run_mod.main(self._args(rd))
        assert rc == 0
        cfg = json.loads((rd / "config.json").read_text())
        st = json.loads((rd / "run_state.json").read_text())
        # 完整 config 与 run_id/setup_plan/environment 已持久化
        assert cfg["run_id"] and cfg["setup_plan"]["container_name"]
        assert cfg["environment"]["docker_image_digest"] == "sha256:" + "ab" * 32
        ex = json.loads((rd / "execution.json").read_text())
        assert ex["container_name"] == cfg["setup_plan"]["container_name"]
        assert ex["run_id"] == cfg["run_id"]

    def test_env_record_conflicting_cli_refused(self, tmp_path, skills_dir,
                                                manifest):
        """CLI digest 与登记不同时拒绝。"""
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        cfg = json.loads((rd / "config.json").read_text())
        cfg["environment"] = {"docker_image": "img",
                              "docker_image_digest": "sha256:" + "cd" * 32,
                              "docker_image_platform": "linux/arm64"}
        (rd / "config.json").write_text(json.dumps(cfg))
        with pytest.raises(SystemExit):
            run_mod.main(self._args(rd) +
                         ["--image-digest", "sha256:" + "ab" * 32])

    def test_registered_plan_disagreeing_ref_refused(self, tmp_path,
                                                     skills_dir, manifest):
        """登记时 digest 未知（浮动 tag plan）而本次补齐 digest → 拒绝，
        提示重新登记。"""
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        cfg = json.loads((rd / "config.json").read_text())
        cfg["environment"] = {"docker_image": "img/name",
                              "docker_image_digest": None,
                              "docker_image_platform": None}
        import setup as _sm
        task = next(t for t in manifest["tasks"]
                    if t["task_id"] == "tdd-workflow-batch1")
        cfg["setup_plan"] = _sm.build_setup_plan(
            manifest, task, skills_dir, "deadbeef", "run_001",
            {"docker_image": "img/name", "docker_image_digest": None,
             "docker_image_platform": None}, cfg["run_id"])
        (rd / "config.json").write_text(json.dumps(cfg))
        rc = run_mod.main(self._args(rd) +
                          ["--image-digest", "sha256:" + "ab" * 32,
                           "--image-platform", "linux/arm64"])
        assert rc == 2

    def test_invalid_digest_format_refused(self, tmp_path, skills_dir, manifest):
        rd = self._run_dir(tmp_path, skills_dir, manifest)
        rc = run_mod.main(self._args(rd) +
                          ["--image-digest", "sha256:tooshort"])
        assert rc == 2


class TestTrajectoryImport:
    def _write_jsonl(self, path, entries):
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    def test_imports_tool_use_steps_by_id(self, tmp_path):
        """并行 tool_use 的观察必须按 tool_use_id 配对，不按 last_action。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Read",
                 "input": {"file_path": "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}},
                {"type": "tool_use", "id": "u2", "name": "Bash",
                 "input": {"command": "ls"}}]}},
            # u2 的 result 先回来；观察必须落回 u2 而不是最后一条 u1
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u2",
                 "content": "listing"}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1",
                 "content": "file contents here"}]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert len(t["steps"]) == 2
        assert "file contents here" in t["steps"][0]["observation"]
        assert "listing" in t["steps"][1]["observation"]

    def test_read_class_only_records_files_read(self, tmp_path):
        """Write/Bash 提到 skills 路径不算已读；失败 read 也不算。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "w1", "name": "Write",
                 "input": {"file_path": "/home/dev/.claude/skills/tdd-workflow/SKILL.md",
                           "content": "x"}},
                {"type": "tool_use", "id": "b1", "name": "Bash",
                 "input": {"command": "cat ~/.claude/skills/tdd-workflow/SKILL.md"}},
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}},
                {"type": "tool_use", "id": "r2", "name": "Read",
                 "input": {"file_path": "/home/dev/.claude/skills/tdd-workflow/missing.md"}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "w1", "content": "ok"},
                {"type": "tool_result", "tool_use_id": "b1", "content": "text"},
                {"type": "tool_result", "tool_use_id": "r1", "content": "skill body"},
                {"type": "tool_result", "tool_use_id": "r2", "content": "ENOENT",
                 "is_error": True},
            ]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert t["steps"][0]["files_read"] == []   # Write 不算
        assert t["steps"][0]["skills_used"] == []
        assert t["steps"][1]["files_read"] == []   # Bash 不算
        assert t["steps"][2]["files_read"] == ["tdd-workflow/SKILL.md"]
        assert t["steps"][2]["skills_used"] == ["tdd-workflow"]
        assert t["steps"][3]["files_read"] == []   # 读取失败不算 consult

    def test_empty_or_invalid_jsonl_rejected(self, tmp_path):
        """坏行是硬错误：strict 下任意损坏行不得生成正式轨迹。"""
        p = tmp_path / "log.jsonl"
        p.write_text("not json\n{also bad\n")
        with pytest.raises(run_mod.TrajectoryImportError, match="unparsable"):
            run_mod.import_trajectory(p, "task", "run_001", "pending")

    def test_bad_line_between_valid_events_rejected(self, tmp_path):
        """损坏行夹在两条有效事件中：不能静默跳行产出正式轨迹。"""
        p = tmp_path / "log.jsonl"
        p.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "ls"}}]}}) + "\n"
            + "CORRUPTED-LINE\n"
            + json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1",
                 "content": "ok"}]}}) + "\n")
        with pytest.raises(run_mod.TrajectoryImportError, match="line 2"):
            run_mod.import_trajectory(p, "task", "run_001", "pending")
        # 非 strict 只产出诊断草稿性质的结果（warnings 标记）
        t = run_mod.import_trajectory(p, "task", "run_001", "pending",
                                      strict=False, allow_partial=True)
        assert t["trajectory_import"]["warnings"]

    def test_list_or_null_entry_rejected(self, tmp_path):
        p = tmp_path / "log.jsonl"
        p.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u1", "name": "Bash", "input": {}}]}})
            + "\n[1,2,3]\nnull\n")
        with pytest.raises(run_mod.TrajectoryImportError):
            run_mod.import_trajectory(p, "task", "run_001", "pending")

    def test_missing_or_duplicate_ids_rejected(self, tmp_path):
        for bad in (
            [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {}}]}}],
            [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash", "input": {}},
                {"type": "tool_use", "id": "u1", "name": "Bash", "input": {}}]}}],
        ):
            p = tmp_path / "log.jsonl"
            p.write_text("\n".join(json.dumps(e) for e in bad) + "\n")
            with pytest.raises(run_mod.TrajectoryImportError):
                run_mod.import_trajectory(p, "task", "run_001", "pending")

    def test_unpaired_and_multiple_results_rejected(self, tmp_path):
        """未知 id / 重复 result / 未配对 result 都是硬错误。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "ls"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u9",
                 "content": "ghost"}]}},
        ])
        with pytest.raises(run_mod.TrajectoryImportError, match="unknown"):
            run_mod.import_trajectory(p, "task", "run_001", "pending")

        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "ls"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content": "a"}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content": "b"}]}},
        ])
        with pytest.raises(run_mod.TrajectoryImportError, match="second"):
            run_mod.import_trajectory(p, "task", "run_001", "pending")

    def test_tool_use_without_result_rejected(self, tmp_path):
        """tool_use 无对应观察 => 正式导出拒绝（缺观察不得导出）。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "ls"}}]}},
        ])
        with pytest.raises(run_mod.TrajectoryImportError, match="no tool_result"):
            run_mod.import_trajectory(p, "task", "run_001", "pending")
        # allow_partial 可以产出草稿并显式标 partial
        t = run_mod.import_trajectory(p, "task", "run_001", "pending",
                                      allow_partial=True)
        assert t["trajectory_import"]["partial"] is True
        assert t["steps"][0]["observation"] == ""  # 不伪造观察

    def test_out_of_order_parallel_pairing_kept(self, tmp_path):
        """out-of-order 并行结果按 id 精确配对回各自的 tool_use。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "a"}},
                {"type": "tool_use", "id": "u2", "name": "Bash",
                 "input": {"command": "b"}},
                {"type": "tool_use", "id": "u3", "name": "Bash",
                 "input": {"command": "c"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u3", "content": "C"},
                {"type": "tool_result", "tool_use_id": "u1", "content": "A"},
                {"type": "tool_result", "tool_use_id": "u2", "content": "B"}]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert [s["observation"] for s in t["steps"]] == ["A", "B", "C"]

    def test_observation_not_truncated(self, tmp_path):
        """超过 500 字符的观察必须完整保留——截断会丢证据。"""
        p = tmp_path / "log.jsonl"
        big = "x" * 5000
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash",
                 "input": {"command": "cat f"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1",
                 "content": big}]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert t["steps"][0]["observation"] == big

    def test_grep_glob_not_files_read(self, tmp_path):
        """Glob/Grep 是检索，不等于已读整文件——不记 files_read。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "g1", "name": "Glob",
                 "input": {"pattern": "skills/**"}},
                {"type": "tool_use", "id": "g2", "name": "Grep",
                 "input": {"pattern": "x", "path":
                           "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "g1",
                 "content": "SKILL.md"},
                {"type": "tool_result", "tool_use_id": "g2",
                 "content": "match line"}]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert t["steps"][0]["files_read"] == []
        assert t["steps"][1]["files_read"] == []

    def test_path_outside_skills_root_not_read(self, tmp_path):
        """file_path 含任意 'skills/' 字符串不算规范根内文件。"""
        p = tmp_path / "log.jsonl"
        self._write_jsonl(p, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": "/workspace/python/myskills/x.md"}},
                {"type": "tool_use", "id": "r2", "name": "Read",
                 "input": {"file_path":
                           "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r1", "content": "c"},
                {"type": "tool_result", "tool_use_id": "r2",
                 "content": "skill body"}]}},
        ])
        t = run_mod.import_trajectory(p, "task", "run_001", "pending")
        assert t["steps"][0]["files_read"] == []
        assert t["steps"][1]["files_read"] == ["tdd-workflow/SKILL.md"]
        assert t["steps"][1]["skills_used"] == ["tdd-workflow"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(run_mod.TrajectoryImportError):
            run_mod.import_trajectory(
                tmp_path / "nope.jsonl", "task", "run_001", "pending")
