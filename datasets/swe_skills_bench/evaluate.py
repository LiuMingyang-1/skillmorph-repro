#!/usr/bin/env python3
"""SWE-Skills-Bench 验收判分与轨迹导出。

执行协议：
  * 只在 run_state.status == "executed" 后运行；pending/running/evaluated
    一律拒绝；
  * 测试文件（哈希与 manifest 复核）注入容器内 ``/tmp/benchmark_tests/``，
    从该目录执行 ``python -m pytest --junitxml``；每步 docker cp/exec
    退出码都检查，staging 失败 => invalid(evaluator_error)；
  * 完整保存原始 stdout/stderr 与 JUnit XML 原文；
  * 成功判据 = 收集到的全部测试均通过（min_pass_rate=1.0）；collection
    error / 0 个测试 / skip / error 一律不成功；
  * 判分以 JUnit XML 为准 + exit code 双向一致性：任何矛盾（exit0 但
    XML 有失败、exit!=0 但 XML 全过、计数不完整）都判 invalid；pytest
    exit 2/3/4（中断/内部/用法错）与收集/环境错误保守判 invalid；
  * execution.outcome 已是终局（task_timeout fail、setup/runner
    invalid）尊重其结果，不覆盖、不重复判分；
  * ``--trajectory-jsonl`` 与 run.py --export-only 共用同一实现
    （run.export_formal_trajectory）；必需证据缺一即拒，无效日志只落
    ``trajectory_draft.json`` 诊断。

用法：
  python evaluate.py --run-dir /abs/path/run_001 [--dry-run]
  python evaluate.py --run-dir ... --trajectory-jsonl /abs/agent.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    CONTAINER_REPO_DIR,
    CONTAINER_TEST_STAGING,
    DATASET_DIR,
    INVALID_EVALUATOR,
    OUTCOME_FAIL,
    OUTCOME_INVALID,
    OUTCOME_SUCCESS,
    STATUS_EVALUATED,
    STATUS_EXECUTED,
    Executor,
    dev_uid_check_shell,
    docker_env_exec_argv,
    docker_exec_argv,
    get_task,
    load_execution_evidence,
    load_manifest,
    parse_junit_xml,
    read_json,
    sha256_file,
    shlex_join,
    verify_execution_evidence,
    write_json,
)
import run as run_mod  # 复用 JSONL 配对导入逻辑与 --export-only


def _verdict(stats, pytest_exit: int | None) -> tuple[str, str]:
    """JUnit 统计 + pytest 退出码 → (outcome, reason)。

    pytest 退出码：0 全过；1 有失败；2 中断；3 内部错误；4 用法错；
    5 未收集到测试。
      * exit 0：XML 必须全部通过且无 skip/error/0 测试，否则 invalid；
      * exit 1：XML 有 error => invalid；有失败 => fail；XML 干净 => invalid；
      * exit 2/3/4：pytest 中断/内部/用法错 => invalid；
      * exit 5 / 0 测试 / 计数矛盾 => invalid；
      * 其余非零 exit：XML 有失败 => fail，否则 invalid。
    """
    if stats.total == 0:
        return OUTCOME_INVALID, "zero_tests_collected"
    if any(c < 0 for c in (stats.passed, stats.failed, stats.errors,
                          stats.skipped)):
        return OUTCOME_INVALID, "negative_test_counts"
    if stats.testcase_count != stats.total:
        return OUTCOME_INVALID, "incomplete_testcase_listing"
    if pytest_exit in (2, 3, 4):
        return OUTCOME_INVALID, f"pytest_internal_exit_{pytest_exit}"
    if pytest_exit == 5:
        return OUTCOME_INVALID, "zero_tests_collected"
    # 只 0/1 是合法结论；其它退出（含 137/OOM）与 XML 无关判 invalid
    if pytest_exit not in (0, 1):
        return OUTCOME_INVALID, f"unexpected_exit_code_{pytest_exit}"
    if stats.errors > 0:
        return OUTCOME_INVALID, "collection_or_test_errors"
    if stats.failed > 0:
        return OUTCOME_FAIL, "test_failures"
    if stats.skipped > 0:
        return OUTCOME_FAIL, "skipped_tests_not_success"
    if pytest_exit == 0:
        return OUTCOME_SUCCESS, "all_passed"
    # pytest_exit == 1 但 XML 无失败/skip/error —— 产物矛盾
    return OUTCOME_INVALID, "exit_xml_contradiction"


def evaluate_from_pytest(junit_xml_text: str, pytest_exit: int | None,
                         stdout: str, stderr: str) -> dict:
    """把一次 pytest 产物转成结构化判分（可离线测试的纯函数）。

    XML 缺失/损坏/计数非法 => invalid(evaluator_error)；exit 与 XML 双向
    矛盾 => invalid；完整统计以 ``stats`` 返回；原始 stdout/stderr 全量
    保留在 ``stdout``/``stderr`` 字段。
    """
    try:
        stats = parse_junit_xml(junit_xml_text)
    except Exception as e:
        return {
            "outcome": OUTCOME_INVALID,
            "outcome_reason": INVALID_EVALUATOR,
            "detail": f"junit xml unparsable: {e}",
            "pytest_exit_code": pytest_exit,
            "stats": None,
            "stdout": stdout,
            "stderr": stderr,
        }
    outcome, reason = _verdict(stats, pytest_exit)
    # exit 与 XML 双向一致性：exit=0 但 XML 有失败，或 outcome=success
    # 但 exit!=0，都是产物不可信。
    xml_has_failures = (stats.failed > 0 or stats.errors > 0
                        or stats.skipped > 0)
    if pytest_exit == 0 and xml_has_failures:
        outcome, reason = OUTCOME_INVALID, "exit_xml_contradiction"
    elif outcome == OUTCOME_SUCCESS and pytest_exit != 0:
        outcome, reason = OUTCOME_INVALID, "exit_xml_contradiction"
    return {
        "outcome": outcome,
        "outcome_reason": reason,
        "pytest_exit_code": pytest_exit,
        "junit_xml": junit_xml_text,
        "stats": {
            "total": stats.total,
            "passed": stats.passed,
            "failed": stats.failed,
            "skipped": stats.skipped,
            "errors": stats.errors,
            "testcase_count": stats.testcase_count,
            "test_names": stats.test_names,
            "duration_sec": stats.duration_sec,
            "failed_tests": stats.failed_tests,
            "skipped_tests": stats.skipped_tests,
        },
        "stdout": stdout,
        "stderr": stderr,
    }


def _verify_execution_evidence(run_dir: Path, config: dict,
                               state: dict) -> str | None:
    """判分前核验执行证据：读 run_dir/execution.json 并过共享证据门。

    execution.outcome == invalid 时返回 None——调用方早退走尊重协议，
    不需要终止证据。
    """
    exec_ev, err = load_execution_evidence(run_dir)
    if err:
        return err
    return verify_execution_evidence(run_dir, config, exec_ev, state)


def export_trajectory(run_dir: Path, config: dict, state: dict,
                      eval_record: dict, jsonl_path: Path,
                      dataset_dir: Path, manifest: dict) -> dict:
    """判分流程内的正式轨迹导出——委托 run.export_formal_trajectory。"""
    return run_mod.export_formal_trajectory(
        run_dir, config, state, eval_record, jsonl_path, dataset_dir,
        manifest)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    p.add_argument("--eval-timeout-sec", type=int, default=300)
    p.add_argument("--exec-timeout-sec", type=int, default=60,
                   help="staging/cp/cat 等辅助命令超时；默认 60")
    p.add_argument("--container", default=None,
                   help="显式容器名——必须与 config.setup_plan 登记一致")
    p.add_argument("--trajectory-jsonl", type=Path, default=None,
                   help="真实 Claude Code JSONL；判分有效时导出 trajectory.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    run_dir = args.run_dir.resolve()
    if not (run_dir / "config.json").is_file() \
            or not (run_dir / "run_state.json").is_file():
        print(f"error: run_dir 缺 config.json/run_state.json: {run_dir}",
              file=sys.stderr)
        return 2
    config = read_json(run_dir / "config.json")
    state = read_json(run_dir / "run_state.json")
    manifest = load_manifest(args.dataset_dir / "manifest.json")
    task = get_task(manifest, config["task_id"])
    test_file = (args.dataset_dir / task["test_file"]).resolve()

    # --- 状态门：只有 executed 才可判分 -------------------------------------
    status = state.get("status")
    if status != STATUS_EXECUTED and not args.dry_run:
        print(f"error: run_dir status={status!r} — 只有 executed 可判分"
              f"（pending/running/evaluated 一律拒绝）", file=sys.stderr)
        return 2
    if not args.dry_run:
        ev_err = _verify_execution_evidence(run_dir, config, state)
        if ev_err:
            print(f"error: {ev_err} — 未核验的终止/运行证据，拒绝判分",
                  file=sys.stderr)
            return 2
    exec_ev = read_json(run_dir / "execution.json") \
        if (run_dir / "execution.json").is_file() else {}
    # 终局 execution 结果（task_timeout fail / setup+runner invalid）直接
    # 尊重——不重跑 pytest，只补写 evaluation 记录。
    settled = None
    if exec_ev.get("outcome") == OUTCOME_FAIL \
            and exec_ev.get("outcome_reason") == "task_timeout":
        settled = (OUTCOME_FAIL, "task_timeout",
                   "task timeout is a fixed-protocol fail; pytest not run")
    elif exec_ev.get("outcome") == OUTCOME_INVALID and not args.dry_run:
        settled = (OUTCOME_INVALID, exec_ev.get("outcome_reason"),
                   "execution-level invalid — pytest not run")
    if settled is not None:
        outcome_s, reason_s, note_s = settled
        eval_record = {
            "task_id": task["task_id"],
            "test_file": task["test_file"],
            "evaluator": "pytest+junitxml",
            "outcome": outcome_s,
            "outcome_reason": reason_s,
            "note": note_s,
        }
        state["status"] = STATUS_EVALUATED
        if not args.dry_run:
            write_json(run_dir / "evaluation.json", eval_record)
            write_json(run_dir / "run_state.json", state)
            if args.trajectory_jsonl and outcome_s == OUTCOME_FAIL:
                res = export_trajectory(
                    run_dir, config, state, eval_record,
                    args.trajectory_jsonl, args.dataset_dir, manifest)
                print(json.dumps({"trajectory": res}, ensure_ascii=False))
            print(json.dumps({"run_dir": str(run_dir),
                              "outcome": outcome_s,
                              "reason": reason_s}, ensure_ascii=False))
        else:
            print(json.dumps(eval_record, indent=2, ensure_ascii=False))
        return 0

    if not test_file.is_file():
        print(f"error: test file missing {test_file}", file=sys.stderr)
        return 2

    executor = Executor(dry_run=args.dry_run)
    eval_record: dict = {
        "task_id": task["task_id"],
        "test_file": task["test_file"],
        "evaluator": "pytest+junitxml",
        "staged_at": CONTAINER_TEST_STAGING,
        "outcome": None,
    }

    # ---- 容器模式：注入隔离测试目录并执行 ----------------------------------
    plan = config.get("setup_plan") or {}
    registered_container = plan.get("container_name")
    if args.container and registered_container \
            and args.container != registered_container:
        print(f"error: --container {args.container!r} != registered "
              f"{registered_container!r} — 判分只允许本 run 登记的容器，"
              "拒绝覆盖", file=sys.stderr)
        return 2
    container = args.container or registered_container \
        or f"swesk-{task['task_id']}-{run_dir.name}"
    stage_shell = (f"rm -rf {CONTAINER_TEST_STAGING} && "
                   f"mkdir -p {CONTAINER_TEST_STAGING} && "
                   f"chown -R dev:dev {CONTAINER_TEST_STAGING} && "
                   f"su -s /bin/sh dev -c 'test -w {CONTAINER_TEST_STAGING}'")
    copy_argv = ["docker", "cp", str(test_file),
                 f"{container}:{CONTAINER_TEST_STAGING}/{test_file.name}"]
    verify_shell = (f"cd {CONTAINER_TEST_STAGING} && "
                    f"sha256sum {test_file.name}")
    pytest_argv = docker_env_exec_argv(
        container,
        f"cd {CONTAINER_TEST_STAGING} && "
        f"python -m pytest -c /dev/null -p no:cacheprovider "
        f"{test_file.name} -v --tb=short "
        f"--junitxml={CONTAINER_TEST_STAGING}/junit.xml",
        env={"REPO_DIR": CONTAINER_REPO_DIR,
             "PYTHONPATH": "",
             "PYTEST_ADDOPTS": "",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        user="dev")
    stage_cmds = [
        docker_exec_argv(container, stage_shell, user="root"),
        copy_argv,
        docker_exec_argv(container, verify_shell),
        pytest_argv,
        docker_exec_argv(
            container, f"cat {CONTAINER_TEST_STAGING}/junit.xml"),
    ]
    cat_xml_argv = stage_cmds[-1]

    xml_text = ""
    pytest_exit = None
    stdout = stderr = ""
    staging_error = None
    if not args.dry_run:
        def _step(argv, timeout, label):
            """执行一步 staging；失败时返回错误字符串。"""
            nonlocal staging_error
            res = executor.run(argv, timeout=timeout)
            if not res.ok:
                staging_error = (f"{label}: "
                                 f"{res.error or res.stderr[:500]}")
            return res

        # 判分前 root 复核：dev UID 不得有存活 agent 进程
        pres = executor.run(docker_exec_argv(container,
                                             dev_uid_check_shell(),
                                             user="root"),
                            timeout=args.exec_timeout_sec)
        if not (pres.ok and pres.stdout.strip() == "1"):
            staging_error = ("residual dev/agent processes still alive "
                             f"(probe: {pres.stdout.strip()!r} "
                             f"err={pres.error or pres.stderr[:200]!r}) "
                             "— refusing to score an unverified stop")
        if staging_error is None:
            _step(docker_exec_argv(container, stage_shell, user="root"),
                  args.exec_timeout_sec,
                  "stage dir failed (chown/writable check included)")
        if staging_error is None:
            _step(copy_argv, args.exec_timeout_sec,
                  "docker cp test failed")
        if staging_error is None:
            res = _step(docker_exec_argv(container, verify_shell),
                        args.exec_timeout_sec, "sha256sum failed")
            if staging_error is None:
                got = res.stdout.split()[0] if res.stdout.split() else None
                want = sha256_file(test_file)
                if got != want:
                    staging_error = ("staged test hash mismatch "
                                     f"(expected {want}, got {got})")
        if staging_error is None:
            res = executor.run(pytest_argv, timeout=args.eval_timeout_sec)
            pytest_exit, stdout, stderr = res.exit_code, res.stdout, res.stderr
            if res.timed_out:
                eval_record["pytest_timed_out"] = True
                staging_error = ("pytest run timed out — infra/timeout, "
                                 "not a task verdict")
            elif res.error:
                staging_error = f"pytest exec failed: {res.error}"
            elif pytest_exit not in (0, 1):
                xres = executor.run(cat_xml_argv,
                                    timeout=args.exec_timeout_sec)
                if xres.ok:
                    xml_text = xres.stdout
                staging_error = (f"pytest exit {pytest_exit} is not a "
                                 "legit verdict exit (only 0/1 allowed) — "
                                 "any XML present is not trustworthy")
            else:
                xres = executor.run(cat_xml_argv,
                                    timeout=args.exec_timeout_sec)
                if xres.ok:
                    xml_text = xres.stdout
                else:
                    staging_error = ("junit xml unreadable: "
                                     f"{xres.error or xres.stderr[:500]}")
    if staging_error is not None:
        eval_record.update({
            "outcome": OUTCOME_INVALID,
            "outcome_reason": INVALID_EVALUATOR,
            "detail": staging_error,
            "pytest_exit_code": pytest_exit,
            "stdout": stdout,
            "stderr": stderr,
        })
    elif not args.dry_run:
        verdict = evaluate_from_pytest(xml_text, pytest_exit, stdout, stderr)
        verdict["mode"] = "container"
        eval_record.update(verdict)
        # 收集到的测试集合与 manifest 登记的 test_count/test_functions
        # 核对——判分仍以 JUnit 结论为准，覆盖缺失是「判分没考到」的证据。
        if eval_record["stats"]:
            collected = set(eval_record["stats"]["test_names"])
            expected_funcs = task.get("test_functions") or []
            eval_record["required_tests_check"] = {
                "manifest_test_count": task.get("test_count"),
                "collected_count": len(collected),
                "expected_functions": expected_funcs or None,
                "missing_functions": [n for n in expected_funcs
                                      if n not in collected] or None,
                "count_mismatch": task.get("test_count") is not None
                    and len(collected) != task["test_count"],
            }
    else:
        eval_record["would_run"] = [shlex_join(a) for a in stage_cmds]
        eval_record["mode"] = "container(dry-run)"

    eval_record["command_log"] = executor.log
    if eval_record.get("outcome"):
        state["status"] = STATUS_EVALUATED
    if not args.dry_run:
        write_json(run_dir / "evaluation.json", eval_record)
        write_json(run_dir / "run_state.json", state)
        traj_res = None
        if args.trajectory_jsonl:
            traj_res = export_trajectory(run_dir, config, state, eval_record,
                                         args.trajectory_jsonl,
                                         args.dataset_dir, manifest)
        print(json.dumps({"run_dir": str(run_dir),
                          "outcome": eval_record.get("outcome"),
                          "reason": eval_record.get("outcome_reason"),
                          "trajectory": traj_res},
                         ensure_ascii=False))
    else:
        print(json.dumps(eval_record, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
