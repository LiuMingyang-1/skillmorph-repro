"""evaluate.py 判分逻辑测试：严格 exit/XML 一致性、状态门、导出。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
from evaluate import evaluate_from_pytest, _verdict, export_trajectory  # noqa: E402
from common import parse_junit_xml  # noqa: E402
from conftest import make_junit, make_run_dir  # noqa: E402


def _stats(total, failures=0, errors=0, skipped=0, cases=None):
    return parse_junit_xml(make_junit(total, failures, errors, skipped, cases))


class TestVerdict:
    def test_success_requires_all_passed_exit0(self):
        s = _stats(14, cases=[("t", None)] * 14)
        assert _verdict(s, 0) == ("success", "all_passed")

    def test_failure_exit1(self):
        cases = [("ok", None)] * 13 + [("bad", "failure")]
        s = _stats(14, failures=1, cases=cases)
        outcome, reason = _verdict(s, 1)
        assert outcome == "fail" and reason == "test_failures"

    def test_skip_is_not_success(self):
        cases = [("ok", None)] * 19 + [("cov", "skipped")]
        s = _stats(20, skipped=1, cases=cases)
        outcome, reason = _verdict(s, 0)
        assert outcome == "fail"
        assert reason == "skipped_tests_not_success"

    def test_errors_are_invalid_not_fail(self):
        """error（collection/单测级错误）保守判 invalid——环境混入不计任务失败。"""
        cases = [("ok", None), ("e", "error")]
        s = _stats(2, errors=1, cases=cases)
        outcome, reason = _verdict(s, 1)
        assert outcome == "invalid" and "error" in reason

    def test_zero_tests_invalid(self):
        s = _stats(0)
        outcome, reason = _verdict(s, 5)
        assert outcome == "invalid" and reason == "zero_tests_collected"

    def test_pytest_internal_exits_invalid(self):
        """exit 2/3/4（中断/内部/用法错）保守 invalid，不算任务失败。"""
        s = _stats(3, cases=[("a", None)] * 3)
        for code in (2, 3, 4):
            outcome, reason = _verdict(s, code)
            assert outcome == "invalid", code
        # 即便 XML 记录失败，exit 3 也仍偏 invalid（infra 不混入任务）
        s2 = _stats(2, failures=1, cases=[("a", "failure"), ("b", None)])
        outcome, _ = _verdict(s2, 3)
        assert outcome == "invalid"

    def test_exit1_clean_xml_invalid(self):
        """exit=1 但 XML 全过 → 矛盾 invalid，不是 success。"""
        s = _stats(3, cases=[("a", None)] * 3)
        outcome, reason = _verdict(s, 1)
        assert outcome == "invalid" and reason == "exit_xml_contradiction"

    def test_incomplete_testcase_listing_invalid(self):
        """attr total 与实际 testcase 数不符 → 解析拒绝 → evaluate 判 invalid。"""
        xml = ('<testsuite tests="5" failures="0" errors="0" skipped="0">'
               '<testcase classname="T" name="only_one"/></testsuite>')
        with pytest.raises(ValueError, match="disagree"):
            parse_junit_xml(xml)
        v = evaluate_from_pytest(xml, 0, "", "")
        assert v["outcome"] == "invalid"

    def test_unknown_exit_and_bad_xml_invalid(self):
        """exit 137 等非 0/1 + XML 损坏 => invalid；exit 5 => zero_tests。"""
        xml = make_junit(3, failures=1,
                         cases=[("a", "failure"), ("b", None), ("c", None)])
        v = evaluate_from_pytest(xml, 137, "", "")
        assert v["outcome"] == "invalid"
        assert "unexpected_exit_code" in v["outcome_reason"]
        v2 = evaluate_from_pytest("<broken", 137, "", "")
        assert v2["outcome"] == "invalid"


class TestEvaluateFromPytest:
    def test_exit0_failed_xml_invalid(self):
        """exit 0 + XML 有失败 → 矛盾 invalid（原缺陷曾判 fail/混乱）。"""
        xml = make_junit(3, failures=1,
                         cases=[("a", "failure"), ("b", None), ("c", None)])
        v = evaluate_from_pytest(xml, 0, "", "")
        assert v["outcome"] == "invalid"
        assert v["outcome_reason"] == "exit_xml_contradiction"

    def test_exit3_failed_xml_invalid_not_fail(self):
        xml = make_junit(2, failures=1,
                         cases=[("a", "failure"), ("b", None)])
        v = evaluate_from_pytest(xml, 3, "", "")
        assert v["outcome"] == "invalid"
        assert v["outcome_reason"] == "pytest_internal_exit_3"

    def test_unparsable_xml_invalid(self):
        v = evaluate_from_pytest("<garbage", 0, "", "")
        assert v["outcome"] == "invalid"
        assert v["stats"] is None

    def test_negative_counts_invalid(self):
        v = evaluate_from_pytest(
            '<testsuite tests="-2" failures="0" errors="0" skipped="0"/>',
            0, "", "")
        assert v["outcome"] == "invalid"

    def test_success_path_full_artifacts(self):
        xml = make_junit(2, cases=[("a", None), ("b", None)])
        v = evaluate_from_pytest(xml, 0, "OUT", "ERR")
        assert v["outcome"] == "success"
        assert v["stats"]["passed"] == 2
        # 完整原文保存，不只 tail
        assert v["stdout"] == "OUT" and v["stderr"] == "ERR"
        assert v["junit_xml"] == xml


class TestEvaluateStateGate:
    def test_pending_run_refused(self, tmp_path):
        rd = make_run_dir(tmp_path, status="pending")
        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 2
        assert not (rd / "evaluation.json").exists()

    def test_running_run_refused(self, tmp_path):
        rd = make_run_dir(tmp_path, status="running")
        assert ev.main(["--run-dir", str(rd)]) == 2

    def test_evaluated_run_refused_reevaluation(self, tmp_path):
        rd = make_run_dir(tmp_path, status="evaluated")
        assert ev.main(["--run-dir", str(rd)]) == 2

    def test_task_timeout_fail_not_overwritten(self, tmp_path):
        """task_timeout 的 fail 不得被后续评测覆盖。"""
        rd = make_run_dir(
            tmp_path, status="executed",
            execution={"outcome": "fail", "outcome_reason": "task_timeout",
                       "exit_code": None, "timed_out": True})
        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 0
        rec = json.loads((rd / "evaluation.json").read_text())
        assert rec["outcome"] == "fail"
        assert rec["outcome_reason"] == "task_timeout"
        st = json.loads((rd / "run_state.json").read_text())
        assert st["status"] == "evaluated"

    def test_execution_invalid_respected(self, tmp_path):
        rd = make_run_dir(
            tmp_path, status="executed",
            execution={"outcome": "invalid", "outcome_reason": "setup_failure"})
        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 0
        rec = json.loads((rd / "evaluation.json").read_text())
        assert rec["outcome"] == "invalid"
        assert rec["outcome_reason"] == "setup_failure"

    def test_staging_failure_marks_invalid(self, tmp_path, manifest,
                                           monkeypatch):
        """staging/cp 失败 => invalid(evaluator_error)，状态仍记 evaluated。"""
        rd = make_run_dir(tmp_path, status="executed",
                          execution={"outcome": None, "outcome_reason": None},
                          manifest=manifest)

        class FailCp(common.Executor):
            def run(self, argv, **kw):
                self.log.append({"argv": list(argv)})
                if argv[:2] == ["docker", "cp"]:
                    return common.CommandResult(
                        argv=list(argv), exit_code=1, stdout="",
                        stderr="no such container", duration_sec=0.01)
                return common.CommandResult(
                    argv=list(argv), exit_code=0, stdout="", stderr="",
                    duration_sec=0.01)

        monkeypatch.setattr(ev, "Executor", lambda **kw: FailCp())
        rc = ev.main(["--run-dir", str(rd)])
        assert rc == 0
        rec = json.loads((rd / "evaluation.json").read_text())
        assert rec["outcome"] == "invalid"
        assert rec["outcome_reason"] == "evaluator_error"
        st = json.loads((rd / "run_state.json").read_text())
        assert st["status"] == "evaluated"

    def test_dry_run_no_staging_writes(self, tmp_path):
        rd = make_run_dir(tmp_path, status="executed",
                          execution={"outcome": None, "outcome_reason": None})
        rc = ev.main(["--run-dir", str(rd), "--dry-run"])
        assert rc == 0
        assert not (rd / "evaluation.json").exists()


def _jsonl(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _tool_jsonl(path):
    _jsonl(path, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u1", "name": "Read",
             "input": {"file_path": "/home/dev/.claude/skills/tdd-workflow/SKILL.md"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u1",
             "content": "skill body"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "u2", "name": "Edit",
             "input": {"file_path": "/workspace/python/src/calculator.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u2",
             "content": "edited"}]}},
    ])


class TestTrajectoryExport:
    def _evaluated(self, tmp_path, manifest, outcome="success"):
        rec = {"outcome": outcome, "outcome_reason": "all_passed"}
        rd = make_run_dir(tmp_path, status="evaluated",
                          execution={"outcome": None, "outcome_reason": None},
                          manifest=manifest, evaluation=rec)
        cfg = json.loads((rd / "config.json").read_text())
        state = json.loads((rd / "run_state.json").read_text())
        return rd, cfg, state, rec

    def test_success_exports_pipeline_ready(self, tmp_path, manifest):
        rd, cfg, state, rec = self._evaluated(tmp_path, manifest, "success")
        log = tmp_path / "agent.jsonl"
        _tool_jsonl(log)
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is True
        traj = json.loads((rd / "trajectory.json").read_text())
        assert traj["task"], "task text must be filled in"
        assert "Smart Coupon Calculator" in traj["task"]
        assert traj["outcome"] == "success"
        assert len(traj["steps"]) == 2
        assert traj["steps"][0]["files_read"] == ["tdd-workflow/SKILL.md"]
        assert traj["steps"][0]["skills_used"] == ["tdd-workflow"]
        # pipeline 输入契约字段
        for k in ("task_id", "run_id", "task", "outcome", "steps"):
            assert k in traj

    def test_invalid_outcome_no_export(self, tmp_path, manifest):
        rd, cfg, state, rec = self._evaluated(tmp_path, manifest, "invalid")
        rec["outcome_reason"] = "evaluator_error"
        log = tmp_path / "agent.jsonl"
        _tool_jsonl(log)
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert not (rd / "trajectory.json").exists()

    def test_missing_log_writes_draft_not_fake(self, tmp_path, manifest):
        rd, cfg, state, rec = self._evaluated(tmp_path, manifest, "fail")
        rec["outcome_reason"] = "test_failures"
        res = export_trajectory(rd, cfg, state, rec,
                                tmp_path / "gone.jsonl", DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert not (rd / "trajectory.json").exists()
        draft = json.loads((rd / "trajectory_draft.json").read_text())
        assert draft["diagnostic"]
        assert draft["task"], "draft may carry task text but is clearly marked"

class TestExportEvidenceGate:
    """verify_export_evidence 证据门：缺任一必需证据保守拒绝。"""

    def _evaluated_full(self, tmp_path, manifest, *,
                        execution_evidence="full", evaluation=None):
        rec = evaluation or {"outcome": "success",
                             "outcome_reason": "all_passed"}
        rd = make_run_dir(tmp_path, status="evaluated",
                          execution={"outcome": None,
                                     "outcome_reason": None},
                          manifest=manifest, evaluation=rec,
                          execution_evidence=execution_evidence)
        cfg = json.loads((rd / "config.json").read_text())
        state = json.loads((rd / "run_state.json").read_text())
        log = tmp_path / "agent.jsonl"
        _tool_jsonl(log)
        return rd, cfg, state, rec, log

    def test_missing_execution_json_refused(self, tmp_path, manifest):
        rd, cfg, state, rec, log = self._evaluated_full(
            tmp_path, manifest, execution_evidence="none")
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "execution.json missing" in res["reason"]

    def test_missing_termination_refused(self, tmp_path, manifest):
        rd, cfg, state, rec, log = self._evaluated_full(
            tmp_path, manifest,
            execution_evidence={"agent_termination": {"terminated": True},
                                "dev_process_verify": {"clean": True},
                                "diff": {"head_after":
                                         manifest["repo"]["commit"],
                                         "ok": True},
                                "container_name":
                                    "swesk-tdd-workflow-batch1-run_001-aa11bb22cc33"})
        # 移除终止证据
        ex = json.loads((rd / "execution.json").read_text())
        del ex["agent_termination"]
        (rd / "execution.json").write_text(json.dumps(ex))
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "termination" in res["reason"].lower()

    def test_missing_dpv_refused(self, tmp_path, manifest):
        rd, cfg, state, rec, log = self._evaluated_full(tmp_path, manifest)
        ex = json.loads((rd / "execution.json").read_text())
        ex["dev_process_verify"] = None
        (rd / "execution.json").write_text(json.dumps(ex))
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "dev_process_verify" in res["reason"]

    def test_wrong_container_in_execution_refused(self, tmp_path, manifest):
        rd, cfg, state, rec, log = self._evaluated_full(tmp_path, manifest)
        ex = json.loads((rd / "execution.json").read_text())
        ex["container_name"] = "swesk-OTHER-run_001-ff00"
        (rd / "execution.json").write_text(json.dumps(ex))
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "container" in res["reason"]

    def test_container_override_differs_refused(self, tmp_path, manifest):
        """--container 与登记不同 → 判分入口拒绝。"""
        rd = make_run_dir(tmp_path, status="executed",
                          execution={"outcome": None,
                                     "outcome_reason": None},
                          manifest=manifest)
        rc = ev.main(["--run-dir", str(rd), "--container", "swesk-OTHER"])
        assert rc == 2

    def test_head_evidence_missing_refused(self, tmp_path, manifest):
        rd, cfg, state, rec, log = self._evaluated_full(tmp_path, manifest)
        ex = json.loads((rd / "execution.json").read_text())
        ex["diff"] = {"ok": True}  # 无 head_after
        (rd / "execution.json").write_text(json.dumps(ex))
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "HEAD" in res["reason"] or "head_after" in res["reason"]

    def test_timeout_reason_consistency(self, tmp_path, manifest):
        """execution 记 task_timeout 但判分理由不同 → 拒绝。"""
        rd, cfg, state, rec, log = self._evaluated_full(
            tmp_path, manifest,
            evaluation={"outcome": "fail", "outcome_reason": "test_failures"})
        ex = json.loads((rd / "execution.json").read_text())
        ex["outcome"] = "fail"
        ex["outcome_reason"] = "task_timeout"
        (rd / "execution.json").write_text(json.dumps(ex))
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is False
        assert "timeout" in res["reason"].lower()


    def test_task_timeout_still_exportable(self, tmp_path, manifest):
        """task_timeout 是有效 fail 判分，允许导出。"""
        rec = {"outcome": "fail", "outcome_reason": "task_timeout"}
        rd = make_run_dir(
            tmp_path, status="evaluated",
            execution={"outcome": "fail", "outcome_reason": "task_timeout"},
            manifest=manifest, evaluation=rec)
        cfg = json.loads((rd / "config.json").read_text())
        state = json.loads((rd / "run_state.json").read_text())
        log = tmp_path / "agent.jsonl"
        _tool_jsonl(log)
        res = export_trajectory(rd, cfg, state, rec, log, DATASET_DIR_PATH,
                                manifest)
        assert res["exported"] is True
        traj = json.loads((rd / "trajectory.json").read_text())
        assert traj["outcome"] == "fail"


DATASET_DIR_PATH = Path(__file__).resolve().parent.parent
