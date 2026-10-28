#!/usr/bin/env python3
"""SWE-Skills-Bench 任务执行适配（setup -> agent run -> 终止核验 -> 暂存待判分）。

显式输入：--task-id、--skills-dir、--output-dir（或 --run-dir 复用已登记
且 status=pending 的目录）、--image-digest/--image-platform、以及**必须显
式给出的** ``--agent-cmd``（容器内以 dev 用户经 ``sh -c`` 执行的任务命
令；不会默认启动任何模型）。``--agent-timeout-sec`` 为任务超时；基础设施
命令超时见 ``--exec-timeout-sec``。

执行协议：
  * 非 ready 任务默认拒绝执行（dry-run 仍打印计划）；
  * 真实执行要求镜像 digest 固定（``image@sha256:<digest>`` + 显式
    ``--platform``）；dry-run 允许 digest 未知并如实记录；
  * 起点固定：clone + checkout manifest.repo.commit + ``rev-parse HEAD``
    逐一比对；clone 目标非空即拒绝；
  * Skill：清空 ``/home/dev/.claude/skills`` 后只注入本次树，容器内
    重算逐文件清单与宿主记录比对，不一致即 setup 失败；
  * 验收测试不进入 agent 可读工作区，终止核验通过后由 evaluate.py 注入；
  * agent 以 dev 身份后台启动，stdout/stderr/退出码落容器文件；宿主轮询
    退出文件直到退出或 ``--agent-timeout-sec`` 到时——docker 断连/命令
    错误是 infra 失败 => invalid，不记 task_timeout；
  * 任务超时按固定协议记 ``fail``（outcome=fail, reason=task_timeout）；
  * run 目录身份核验：--run-dir 的 config.task_id、repo commit 必须与
    本次请求一致且 status==pending；
  * 镜像/计划不可变：--run-dir 复用 setup 登记的环境与 plan，
    --image-digest/--image-platform 只能补登记缺失字段，与登记值冲突
    即拒绝；
  * 正式 ``trajectory.json`` 只有一个导出来源：``export_formal_trajectory``
    （--export-only 与 evaluate 判分后共用）；``--trajectory-jsonl`` 在
    run 阶段只写 ``trajectory_draft.json`` 诊断草稿；``--cleanup`` 只清
    本 run 容器。

用法（dry-run，今日可验）：
  python run.py --task-id tdd-workflow-batch1 \
      --skills-dir $PWD/datasets/swe_skills_bench/skills \
      --output-dir /tmp/swesk_runs --agent-cmd 'claude -p "$TASK"' --dry-run
  python run.py --run-dir /path/run_001 --export-only \
      --trajectory-jsonl /path/agent.jsonl   # 判分后导出正式轨迹
  python run.py --run-dir /path/run_001 --cleanup  # 只清本 run 容器
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from common import (
    CONTAINER_AGENT_EXIT,
    CONTAINER_AGENT_ERR,
    CONTAINER_AGENT_OUT,
    CONTAINER_AGENT_PID,
    CONTAINER_REPO_DIR,
    CONTAINER_SKILLS_DIR,
    CONTAINER_TEST_STAGING,
    DATASET_DIR,
    INVALID_RUNNER,
    INVALID_SETUP,
    OUTCOME_FAIL,
    OUTCOME_INVALID,
    OUTCOME_SUCCESS,
    STATUS_EVALUATED,
    STATUS_EXECUTED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Executor,
    build_cleanup_plan,
    check_skills_dir,
    check_task_file,
    dev_uid_check_shell,
    dev_uid_kill_shell,
    docker_env_exec_argv,
    docker_exec_argv,
    get_task,
    load_execution_evidence,
    load_manifest,
    next_run_dir,
    read_json,
    shlex_join,
    skill_tree_listing,
    task_is_runnable,
    tree_sha256,
    validate_env_record,
    verify_execution_evidence,
    write_json,
)

TASK_INSTRUCTION = (
    "INTERNAL_INSTRUCTION: DO_NOT_ASK_OR_PLAN\n"
    "You MUST directly modify files in the repository under the workspace to implement the task.\n"
    "Do NOT output a design plan or ask clarifying questions.\n"
    "Write/update the necessary files (provide full file paths and contents).\n"
    "Only output a concise summary of files changed and the final status.\n"
    "EndInstruction\n\n"
)

# agent 外壳：以后台子进程起 agent 命令，退出码落 ``/tmp/agent.exit``，
# stdout/stderr 落容器内文件（完整保存，不只 tail）。TASK/AGENT_CMD 由
# ``docker exec --env`` 传入——容器内 sh 展开 "$TASK"，不经宿主 shell 赋值。
# 以 dev 身份运行（--user dev）：整个终止边界协议依赖固定 UID。
AGENT_WRAPPER_SHELL = (
    f"cd {CONTAINER_REPO_DIR} && "
    f"( sh -c \"$AGENT_CMD\"; echo $? > {CONTAINER_AGENT_EXIT} ) "
    f"> {CONTAINER_AGENT_OUT} 2> {CONTAINER_AGENT_ERR} & "
    f"echo $! > {CONTAINER_AGENT_PID}"
)

# 轮询：agent.exit 出现即结束；顺带 cat 出退出码
POLL_SHELL = f"cat {CONTAINER_AGENT_EXIT} 2>/dev/null || true"


def _write_run_artifacts(run_dir: Path, *, config: dict, state: dict,
                         execution: dict | None, raw: dict) -> None:
    write_json(run_dir / "config.json", config)
    write_json(run_dir / "run_state.json", state)
    if execution is not None:
        write_json(run_dir / "execution.json", execution)
    if raw:
        write_json(run_dir / "raw_log.json", raw)


def _run_setup_steps(executor: Executor, plan: dict, setup_log: dict,
                     exec_timeout: float, skills_dir: Path | None) -> bool:
    """执行初始化计划；任一步骤失败即返回 False（invalid setup）。

    每步先跑 ``docker_argv``（宿主 argv），再跑 ``container_shell``
    （经 ``docker exec <container> sh -c``）；``allow_failure`` 步骤失败
    不算 setup 失败。``verify.kind == file_listing_sha256`` 时取最后一条
    container_shell 的 stdout 与宿主 ``skills_dir`` 的逐文件哈希清单
    逐行比对，不一致判失败。
    """
    ok = True
    for step in plan["steps"]:
        step_log = {"name": step["name"], "commands": []}
        setup_log["steps"].append(step_log)
        step_ok = True

        def _run(argv):
            res = executor.run(list(argv), timeout=exec_timeout)
            step_log["commands"].append({
                "argv": list(argv),
                "exit_code": res.exit_code,
                "timed_out": res.timed_out,
                "error": res.error,
                "stderr_tail": res.stderr[-1000:],
            })
            return res

        def _check(res):
            return (res.ok or executor.dry_run
                    or step.get("allow_failure"))

        for argv in step.get("docker_argv", []):
            if not _check(_run(argv)):
                step_ok = False

        shells = step.get("container_shell", [])
        for i, shell in enumerate(shells):
            res = _run(docker_exec_argv(plan["container_name"], shell))
            if not _check(res):
                step_ok = False
            if i == len(shells) - 1 \
                    and step.get("verify", {}).get("kind") \
                    == "file_listing_sha256" \
                    and skills_dir is not None and not executor.dry_run \
                    and res.ok:
                expected = skill_tree_listing(skills_dir)
                got = [ln for ln in res.stdout.splitlines() if ln.strip()]
                last = step_log["commands"][-1]
                last["listing_match"] = got == expected
                if got != expected:
                    last["expected_listing"] = expected
                    last["container_listing"] = got
                    step_ok = False

        if not step_ok:
            ok = False
            step_log["failed"] = True
            break
    setup_log["ok"] = ok
    return ok


def _collect_diff(executor: Executor, container: str, diff_out: dict,
                  exec_timeout: float) -> dict:
    """收集 repo 改动证据：HEAD diff（含 staged）+ untracked 内容清单。

    全部以 dev 身份执行（root 对 dev 拥有的 repo 跑 git 会被 dubious
    ownership 拒）；untracked 文件逐份收集完整内容。任一命令失败落
    ``diff_out.ok=False`` + 错误明细——调用方据此可判 invalid，而不是
    把残缺 diff 当完整证据。
    """
    ws = CONTAINER_REPO_DIR
    diff_out["ok"] = True

    def _exec(shell, key, label):
        res = executor.run(docker_exec_argv(
            container, shell, user="dev"), timeout=exec_timeout)
        diff_out[key] = res.stdout
        diff_out[f"{key}_exit_code"] = res.exit_code
        if not res.ok:
            diff_out["ok"] = False
            diff_out.setdefault("errors", []).append(
                f"{label}: {res.error or res.stderr[:300]}")
        return res

    _exec(f"cd {ws} && git --no-pager diff HEAD -- .",
          "git_diff_stdout", "git diff HEAD")
    _exec(f"cd {ws} && git status --porcelain=v1",
          "git_status_porcelain", "git status")
    res3 = _exec(f"cd {ws} && git ls-files --others --exclude-standard",
                 "untracked_list_raw", "git ls-files")
    untracked = [line for line in res3.stdout.splitlines() if line.strip()]
    diff_out["untracked_files"] = untracked
    if res3.ok and untracked:
        # 逐份读全量内容（不改 index）；失败由 _exec 记 ok=False
        quoted = shlex_join(untracked)
        _exec(f"cd {ws} && for f in {quoted}; do "
              f"printf '===== %s =====\\n' \"$f\"; cat -- \"$f\"; echo; done",
              "untracked_contents", "untracked contents")
    res4 = _exec(f"cd {ws} && git rev-parse HEAD", "head_after_raw",
                 "git rev-parse")
    diff_out["head_after"] = res4.stdout.strip() if res4.exit_code == 0 else None
    return diff_out


def _start_agent(executor: Executor, container: str, agent_cmd: str,
                 task_text: str, exec_timeout: float):
    """后台启动 agent：TASK/AGENT_CMD 经 ``docker exec --env`` 传入。"""
    env = {"TASK": task_text, "AGENT_CMD": agent_cmd}
    argv = docker_env_exec_argv(
        container, AGENT_WRAPPER_SHELL, env=env, user="dev")
    return executor.run(argv, timeout=exec_timeout)


def _poll_agent_exit(executor: Executor, container: str, deadline: float,
                     exec_timeout: float) -> dict:
    """轮询 ``/tmp/agent.exit`` 直到出现或超时。

    返回 {timed_out, exit_code, error}。docker 断连/命令启动失败是
    infra 错误——立即返回 ``error``，调用方判 invalid，不等 deadline
    误记 task_timeout。dry-run 下不循环。
    """
    def _done(timed_out=None, exit_code=None, error=None):
        return {"timed_out": timed_out, "exit_code": exit_code,
                "error": error}
    if executor.dry_run:
        return _done()
    while True:
        res = executor.run(docker_exec_argv(container, POLL_SHELL),
                           timeout=exec_timeout)
        if res.error:
            return _done(error=f"poll exec failed: {res.error}")
        if res.timed_out:
            return _done(
                error="poll command timed out (container unreachable?)")
        if res.ok:
            text = res.stdout.strip()
            if text:
                try:
                    exit_code = int(text)
                except ValueError:
                    pass
                else:
                    if time.monotonic() >= deadline:
                        return _done(timed_out=True)
                    return _done(timed_out=False, exit_code=exit_code)
        else:
            # cat 非零退出（如容器已停）——infra 失败
            return _done(error=f"poll exit {res.exit_code}: "
                               f"{res.stderr[:300]}")
        if time.monotonic() >= deadline:
            return _done(timed_out=True)
        time.sleep(2)


def _stop_agent(executor: Executor, container: str,
                exec_timeout: float) -> dict:
    """终止 dev UID 下全部进程并核验；返回 {terminated, ...}。

    agent 及其后代都跑在固定 dev UID 下（见 setup 的
    precheck_dev_identity），由 root 身份对整个 UID TERM→KILL 后
    pgrep 核验——不依赖命令行正则、pid 文件或进程树。
    """
    kill_res = executor.run(
        docker_exec_argv(container, dev_uid_kill_shell()),
        timeout=exec_timeout)
    if not kill_res.ok:
        kill_err = kill_res.error or (
            "kill command timed out" if kill_res.timed_out
            else f"kill exit {kill_res.exit_code}: "
                 f"{kill_res.stderr[:300]}")
        check_res = check_out = None
        terminated = False
        check_err = None
    else:
        kill_err = None
        check_res = executor.run(
            docker_exec_argv(container, dev_uid_check_shell()),
            timeout=exec_timeout)
        terminated = check_res.ok and check_res.stdout.strip() == "1"
        check_out = check_res.stdout.strip()
        check_err = check_res.error or (
            f"check exit {check_res.exit_code}: "
            f"{check_res.stderr[:200]}" if not check_res.ok else None)
    return {
        "terminated": bool(terminated),
        "kill_exit": kill_res.exit_code,
        "kill_error": kill_err,
        "check_stdout": check_out,
        "check_error": check_err,
    }


def _read_agent_artifacts(executor: Executor, container: str,
                        exec_timeout: float) -> dict:
    """拉回 agent 的完整 stdout/stderr（不只 tail）。"""
    out_res = executor.run(docker_exec_argv(
        container, f"cat {CONTAINER_AGENT_OUT} 2>/dev/null || true"),
        timeout=exec_timeout)
    err_res = executor.run(docker_exec_argv(
        container, f"cat {CONTAINER_AGENT_ERR} 2>/dev/null || true"),
        timeout=exec_timeout)
    return {
        "agent_stdout": out_res.stdout,
        "agent_stderr": err_res.stdout,
    }


class TrajectoryImportError(Exception):
    """导入契约违规：不得生成正式 trajectory（调用方落诊断草稿）。"""


def import_trajectory(jsonl_path: Path, task_id: str, run_id: str,
                      outcome: str,
                      skills_root: str = CONTAINER_SKILLS_DIR,
                      strict: bool = True,
                      allow_partial: bool = False) -> dict:
    """把 Claude Code JSONL 转成接口 JSON（正式轨迹的唯一导入路径）。

    每条 assistant ``tool_use`` 一个 step，观察按 ``tool_use_id`` 与
    ``tool_result.tool_use_id`` 精确配对，完整保留不截断；源文件
    sha256 记入 ``trajectory_import.source_sha256``。

    strict（正式导出的默认）下硬错误 => ``TrajectoryImportError``：坏行/
    非 dict、缺/重复 tool_use id、result 无 id/多 result/未知 id/result
    缺观察（``allow_partial=True`` 时降级为 partial draft 标记，不伪造
    观察）。

    只有 ``Read`` 成功且 ``file_path`` 落在 ``skills_root`` 下才记
    ``files_read``/``skills_used``——Glob/Grep 是检索不算已读整文件，
    Write/Bash 字符串命中也不算。
    """
    try:
        raw_bytes = Path(jsonl_path).read_bytes()
    except OSError as e:
        raise TrajectoryImportError(f"unreadable: {e}")
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines()

    steps: list[dict] = []
    pending: dict[str, int] = {}
    seen_ids: set[str] = set()
    warnings: list[str] = []
    unmatched_results: list[dict] = []
    n_tool_use = n_tool_result = 0

    def _err(msg):
        if strict:
            raise TrajectoryImportError(msg)
        warnings.append(msg)

    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            _err(f"line {lineno}: unparsable JSON: {e}")
            continue
        if not isinstance(entry, dict):
            _err(f"line {lineno}: JSONL entry is not an object")
            continue
        etype = entry.get("type")
        if etype not in ("assistant", "user"):
            continue
        msg = entry.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if content is None:
            continue
        if not isinstance(content, list):
            _err(f"line {lineno}: message.content is not a list")
            continue
        if etype == "assistant":
            for item in content:
                if not (isinstance(item, dict)
                        and item.get("type") == "tool_use"):
                    continue
                n_tool_use += 1
                tid = item.get("id")
                name = item.get("name")
                inp = item.get("input") or {}
                if not tid:
                    _err(f"line {lineno}: tool_use missing id")
                elif tid in seen_ids:
                    _err(f"line {lineno}: duplicate tool_use id {tid!r}")
                if not name:
                    _err(f"line {lineno}: tool_use missing name")
                if not isinstance(inp, dict):
                    _err(f"line {lineno}: tool_use input not an object")
                    inp = {}
                steps.append({
                    "action": _format_action(name or "?", inp),
                    "observation": "",
                    "skills_used": [],
                    "files_read": [],
                    "tool_use_id": tid,
                    "tool_name": name,
                    "tool_input": inp,
                    "tool_result": None,
                })
                if tid:
                    seen_ids.add(tid)
                    pending[tid] = len(steps) - 1
        else:  # user
            for item in content:
                if not (isinstance(item, dict)
                        and item.get("type") == "tool_result"):
                    continue
                n_tool_result += 1
                tid = item.get("tool_use_id")
                if not tid:
                    _err(f"line {lineno}: tool_result missing tool_use_id")
                    continue
                if tid not in pending:
                    if tid in seen_ids:
                        _err(f"line {lineno}: second tool_result for "
                             f"{tid!r} (already paired)")
                    else:
                        _err(f"line {lineno}: tool_result for unknown "
                             f"tool_use id {tid!r}")
                    unmatched_results.append({"line": lineno,
                                              "tool_use_id": tid})
                    continue
                idx = pending.pop(tid)
                step = steps[idx]
                try:
                    text = _result_text(item.get("content"))
                except TrajectoryImportError as e:
                    _err(f"line {lineno}: {e}")
                    text = ""
                step["observation"] = text
                step["tool_result"] = {
                    "content": item.get("content"),
                    "is_error": bool(item.get("is_error")),
                }
                step["skills_used"], step["files_read"] = _extract_skill_reads(
                    step["tool_name"], step["tool_input"],
                    bool(item.get("is_error")), skills_root)

    unpaired_uses = [{"index": i, "tool_use_id": steps[i]["tool_use_id"]}
                     for i in pending.values()]
    if unpaired_uses and not allow_partial:
        _err(f"{len(unpaired_uses)} tool_use call(s) have no tool_result — "
             "missing observations cannot be exported as a formal "
             "trajectory (allow_partial permits a diagnostic draft)")
    elif unpaired_uses:
        warnings.append(f"{len(unpaired_uses)} tool_use call(s) lack "
                        "tool_result — logged as partial, observations "
                        "left empty, not fabricated")
    partial = bool(unpaired_uses)

    return {
        "task_id": task_id,
        "run_id": run_id,
        "task": None,
        "outcome": outcome,
        "steps": steps,
        "trajectory_import": {
            "source": str(jsonl_path),
            "source_sha256": source_sha256,
            "strict": strict,
            "partial": partial,
            "tool_use": n_tool_use,
            "tool_result": n_tool_result,
            "unmatched_results": unmatched_results or None,
            "unpaired_tool_uses": unpaired_uses or None,
            "warnings": warnings or None,
        },
    }


def _result_text(content) -> str:
    """tool_result.content → 完整文本（str 或多段 text 拼接，不截断）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
        return "\n".join(parts)
    if content is None:
        return ""
    raise TrajectoryImportError(
        f"unsupported tool_result content shape: {type(content).__name__}")


def _format_action(name: str, inp: dict) -> str:
    if "command" in inp:
        return f"{name}(command={inp['command']!r})"
    if "file_path" in inp:
        return f"{name}(path={inp['file_path']!r})"
    if "pattern" in inp:
        return f"{name}(pattern={inp['pattern']!r})"
    return name


def _extract_skill_reads(tool_name: str, inp: dict, is_error: bool,
                         skills_root: str) -> tuple[list[str], list[str]]:
    """只把可验证的「Read 成功 + file_path 解析在 skills 根下」记为
    files_read/skills_used——检索类工具与读取失败不算 consult。
    """
    if tool_name != "Read" or is_error:
        return [], []
    val = inp.get("file_path")
    if not isinstance(val, str):
        return [], []
    v = val.strip().strip("'\"")
    if not v:
        return [], []
    root = skills_root.rstrip("/")
    if v.startswith(root + "/"):
        rel = v[len(root) + 1:]
    elif not v.startswith("/"):
        # 协议相对路径：<skill>/<file> 或 skills/<skill>/<file>
        parts = v.split("/")
        if parts and parts[0] == "skills":
            parts = parts[1:]
        rel = "/".join(parts)
    else:
        return [], []
    if not rel or rel.startswith("/"):
        return [], []
    return [rel.split("/", 1)[0]], [rel]


def _load_run_dir(run_dir: Path, task_id: str,
                  repo_commit: str) -> dict:
    """核验 --run-dir 身份并返回其 config。

    config.task_id/repo.commit 必须与请求/manifest 一致，
    run_state.status 必须是 pending。
    """
    files = ("config.json", "run_state.json")
    missing = [f for f in files if not (run_dir / f).is_file()]
    if missing:
        raise SystemExit(f"error: --run-dir 缺 {missing}: {run_dir}")
    config = read_json(run_dir / "config.json")
    state = read_json(run_dir / "run_state.json")
    if config.get("task_id") != task_id:
        raise SystemExit(
            f"error: task mismatch — run_dir registered for "
            f"{config.get('task_id')!r}, requested {task_id!r}")
    if state.get("status") != STATUS_PENDING:
        raise SystemExit(
            f"error: run_dir status={state.get('status')!r} — "
            f"只有 pending 的 run 可以执行")
    recorded_commit = (config.get("repo") or {}).get("commit")
    if recorded_commit and recorded_commit != repo_commit:
        raise SystemExit(
            f"error: repo commit mismatch — run_dir pinned "
            f"{recorded_commit}, manifest now {repo_commit}")
    return config


def _resolve_env_record(config: dict | None, manifest: dict, args) -> dict:
    """按已登记参数解析镜像环境：登记值 > CLI > manifest，冲突即拒绝。"""
    reg = dict((config or {}).get("environment") or {})
    for k, cli in (("docker_image_digest", args.image_digest),
                   ("docker_image_platform", args.image_platform)):
        man = (manifest.get("environment") or {}).get(k)
        if cli and reg.get(k) and cli != reg[k]:
            raise SystemExit(
                f"error: {k} conflicts with registered plan "
                f"({reg[k]!r} vs {cli!r}) — refusing to run under a "
                "different image identity than recorded")
        if not reg.get(k):
            reg[k] = cli or man
    if not reg.get("docker_image"):
        reg["docker_image"] = (manifest.get("environment") or {}).get(
            "docker_image")
    return reg


def verify_export_evidence(run_dir: Path, config: dict, state: dict,
                           eval_record: dict) -> str | None:
    """正式轨迹导出/判分共用的证据门：返回 None（通过）或拒绝原因。

    读**传入的 run_dir** 下的 execution.json。核验：state.status ==
    evaluated、evaluation.outcome 有效（success/fail）、判分与 execution
    的 timeout 理由一致、共享证据门
    ``common.verify_execution_evidence``（容器/run 身份、terminated、
    dpv.clean、diff.head_after、setup.ok）。
    """
    if state.get("status") != STATUS_EVALUATED:
        return (f"state.status={state.get('status')!r} — formal export "
                "requires an evaluated run")
    outcome = eval_record.get("outcome")
    reason = eval_record.get("outcome_reason")
    if outcome not in (OUTCOME_SUCCESS, OUTCOME_FAIL):
        return (f"no valid scored verdict ({outcome!r}/{reason!r}) — "
                "refusing export")
    if eval_record.get("task_id") and \
            eval_record["task_id"] != config.get("task_id"):
        return "evaluation task_id != config task_id"

    ev, err = load_execution_evidence(run_dir)
    if err:
        return err
    if ev.get("outcome") == OUTCOME_INVALID:
        return "execution-level invalid — no valid verdict to export"
    shared_err = verify_execution_evidence(run_dir, config, ev, state)
    if shared_err:
        return shared_err
    # timeout 理由一致性：execution 说 task_timeout 时判分理由必须相同
    if ev.get("outcome_reason") == "task_timeout" \
            and reason != "task_timeout":
        return (f"execution timed out but evaluation reason is "
                f"{reason!r} — inconsistent timeout accounting")
    if reason == "task_timeout" \
            and ev.get("outcome_reason") != "task_timeout":
        return ("evaluation claims task_timeout but execution does not "
                "record it")
    return None


def export_formal_trajectory(run_dir: Path, config: dict, state: dict,
                             eval_record: dict, jsonl_path: Path,
                             dataset_dir: Path, manifest: dict,
                             dry_run: bool = False) -> dict:
    """唯一的正式轨迹导出函数——evaluate 判分后与 --export-only 共用。

    只读已有事实（不重评分、不跑 pytest）；先过
    ``verify_export_evidence`` 证据门，再严格导入真实 JSONL；正式
    trajectory.json 不可覆盖。返回 ``{"exported": bool, ...}``。
    """
    run_dir = Path(run_dir)
    err = verify_export_evidence(run_dir, config, state, eval_record)
    if err:
        return {"exported": False, "reason": err}
    if (run_dir / "trajectory.json").is_file():
        return {"exported": False,
                "reason": "trajectory.json already exists — formal "
                          "trajectories are immutable, refusing overwrite"}
    try:
        task = get_task(manifest, config["task_id"])
        task_text = check_task_file(manifest, task, dataset_dir)
    except (KeyError, ValueError) as e:
        return {"exported": False,
                "reason": f"registered task file fails integrity: {e}"}
    outcome = eval_record.get("outcome")
    try:
        traj = import_trajectory(jsonl_path, config["task_id"],
                                 run_dir.name, outcome, strict=True,
                                 allow_partial=False)
    except TrajectoryImportError as e:
        traj = None
        draft = {"task_id": config["task_id"], "run_id": run_dir.name,
                 "task": task_text, "outcome": outcome, "steps": [],
                 "diagnostic": f"import refused: {e}",
                 "trajectory_import": {"source": str(jsonl_path)}}
        reason = f"log violates import contract: {e} — "
    if traj is not None and not traj["steps"]:
        draft = {**traj, "task": task_text,
                 "diagnostic": "no usable steps parsed — draft only, "
                               "NOT a pipeline-ready trajectory"}
        reason = "empty step list — "
    if traj is None or not traj["steps"]:
        if not dry_run:
            write_json(run_dir / "trajectory_draft.json", draft)
        return {"exported": False,
                "reason": reason + "wrote trajectory_draft.json"}
    traj["task"] = task_text
    if eval_record.get("outcome_reason") == "task_timeout":
        traj["outcome"] = OUTCOME_FAIL
        traj["outcome_reason"] = "task_timeout"
    if not dry_run:
        write_json(run_dir / "trajectory.json", traj)
    return {"exported": not dry_run, "dry_run": bool(dry_run),
            "steps": len(traj["steps"]),
            "path": str(run_dir / "trajectory.json")}


def _export_only(args, manifest) -> int:
    """显式 export-only：读已存有效判分（evaluation.json），不重跑
    pytest，不改判分状态。
    """
    run_dir = args.run_dir.resolve() if args.run_dir else None
    if run_dir is None or not args.trajectory_jsonl:
        need = "--run-dir" if run_dir is None else "--trajectory-jsonl"
        print(f"error: --export-only 需要 {need}", file=sys.stderr)
        return 2
    files = ("config.json", "run_state.json", "evaluation.json")
    missing = [f for f in files if not (run_dir / f).is_file()]
    if missing:
        print(f"error: run_dir 缺 {missing}: {run_dir}", file=sys.stderr)
        return 2
    config = read_json(run_dir / "config.json")
    state = read_json(run_dir / "run_state.json")
    eval_record = read_json(run_dir / "evaluation.json")
    res = export_formal_trajectory(run_dir, config, state, eval_record,
                                   args.trajectory_jsonl, args.dataset_dir,
                                   manifest, dry_run=args.dry_run)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if (res["exported"] or "trajectory_draft" in
                 (res.get("reason") or "")) else 2


def _cleanup_run(run_dir, executor) -> int:
    """显式清理：只删本 run 容器，保留 artifacts。"""
    run_dir = Path(run_dir).resolve() if run_dir else None
    if run_dir is None or not (run_dir / "config.json").is_file():
        print("error: --cleanup 需要带 config.json 的 --run-dir",
              file=sys.stderr)
        return 2
    config = read_json(run_dir / "config.json")
    container = (config.get("setup_plan") or {}).get("container_name")
    if not container:
        print("error: config 无 setup_plan.container_name —— 拒绝清理"
              "未知容器", file=sys.stderr)
        return 2
    try:
        plan = build_cleanup_plan(container)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for step in plan["steps"]:
        for argv in step["docker_argv"]:
            executor.run(argv)
    print(json.dumps({"cleaned": container, "kept": str(run_dir)},
                     ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--task-id", default=None,
                   help="执行任务用；--export-only/--cleanup 不需要")
    p.add_argument("--skills-dir", type=Path,
                   help="Skill 树；--run-dir 复用已有 config 时可省略")
    p.add_argument("--output-dir", type=Path,
                   help="运行输出根目录（与 --run-dir 二选一）")
    p.add_argument("--run-dir", type=Path,
                   help="复用 setup.py 已登记的 run_NNN 目录")
    p.add_argument("--agent-cmd", default=None,
                   help="容器内以 dev 用户经 sh -c 执行的任务命令")
    p.add_argument("--agent-timeout-sec", type=int, default=1800,
                   help="任务超时；默认 1800")
    p.add_argument("--exec-timeout-sec", type=int, default=300,
                   help="单条基础设施命令超时；默认 300")
    p.add_argument("--image-digest", default=None)
    p.add_argument("--image-platform", default=None)
    p.add_argument("--agent-config-json", type=Path, default=None,
                   help="可选 JSON：agent 显式配置，原样并入 config.agent")
    p.add_argument("--trajectory-jsonl", type=Path, default=None,
                   help="真实 Claude Code JSONL；run 模式只写诊断草稿，"
                        "正式 trajectory 经 --export-only")
    p.add_argument("--export-only", action="store_true",
                   help="只导出轨迹：读已存判分；需 --trajectory-jsonl")
    p.add_argument("--cleanup", action="store_true",
                   help="只清理本 run 的容器")
    p.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    executor = Executor(dry_run=args.dry_run)
    manifest = load_manifest(args.dataset_dir / "manifest.json")

    # --- 独立子模式：cleanup/export-only ------------------------------------
    if args.cleanup:
        return _cleanup_run(args.run_dir, executor)
    if args.export_only:
        return _export_only(args, manifest)
    if not args.task_id:
        p.error("需要 --task-id")
    if not args.agent_cmd:
        p.error("需要 --agent-cmd（容器内以 dev 身份执行的命令；"
                "不显式给则不运行模型）")

    task = get_task(manifest, args.task_id)
    repo_commit = manifest["repo"]["commit"]

    # --- 解析/建立 run 目录 -------------------------------------------------
    skills_dir = None
    skill_tree_hash = None
    if args.skills_dir:
        try:
            skills_dir = check_skills_dir(args.skills_dir)
            skill_tree_hash = tree_sha256(skills_dir)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    if args.run_dir:
        run_dir = args.run_dir.resolve()
        config = _load_run_dir(run_dir, task["task_id"], repo_commit)
        if skills_dir is None:
            try:
                skills_dir = check_skills_dir(
                    Path(config["skills"]["host_dir"]))
                skill_tree_hash = tree_sha256(skills_dir)
            except (ValueError, KeyError) as e:
                raise SystemExit(f"error: registered skills_dir: {e}")
    else:
        if skills_dir is None or args.output_dir is None:
            p.error("需要 --skills-dir 与 --output-dir，或提供 --run-dir")
        run_dir = next_run_dir(args.output_dir.resolve())
        config = None

    # 环境/计划按已登记参数为准（登记即冻结）；仅登记缺失字段可补，冲突拒绝
    env_record = _resolve_env_record(config, manifest, args)

    # 已提供的 digest/platform 必须格式合法（非法值即使登记过也拒绝；
    # dry-run 允许缺失但不容忍伪造/乱写的值）
    env_errors = validate_env_record(env_record)
    if env_errors:
        for e in env_errors:
            print(f"error: {e}", file=sys.stderr)
        return 2

    # 真实执行必须固定 image@digest 与 platform；dry-run 允许 unknown
    if not args.dry_run:
        missing = [k for k in ("docker_image_digest", "docker_image_platform")
                   if not env_record.get(k)]
        if missing:
            print(f"error: 真实执行要求固定镜像参数，缺少: {missing} —— "
                  "提供 --image-digest/--image-platform（首拉后回填 "
                  "manifest），不得依赖浮动 tag", file=sys.stderr)
            return 2

    # 登记时 digest/platform 缺失导致 plan 失真的，直接拒绝——不重建
    old_plan = config.get("setup_plan") if config else None
    if isinstance(old_plan, dict) and old_plan.get("steps"):
        expect_ref = f"{env_record.get('docker_image')}@" \
            f"{env_record.get('docker_image_digest')}" \
            if env_record.get("docker_image") \
            and env_record.get("docker_image_digest") else None
        if (expect_ref and old_plan.get("image_ref") != expect_ref) \
                or (env_record.get("docker_image_platform")
                    and old_plan.get("image_platform")
                    != env_record.get("docker_image_platform")):
            print("error: registered setup_plan's image_ref/platform "
                  "disagrees with the resolved env record — refusing "
                  "a floating-tag plan; re-register via setup.py",
                  file=sys.stderr)
            return 2

    if not args.dry_run and not task_is_runnable(task):
        print(f"error: task {task['task_id']} status="
              f"{task.get('status')!r} — 非 ready 任务默认拒绝执行"
              f"（可用 --dry-run 打印计划供审查）", file=sys.stderr)
        return 2

    if config is None:
        config = {
            "dataset": manifest["dataset"],
            "task_id": task["task_id"],
            "batch": task["batch"],
            "task_status": task.get("status"),
            "task_file": task["task_file"],
            "test_file": task["test_file"],
            "repo": manifest["repo"],
            "evaluation": manifest["evaluation"],
            "skills": {
                "host_dir": str(skills_dir),
                "container_dir": CONTAINER_SKILLS_DIR,
                "tree_sha256": skill_tree_hash,
            },
            "agent_cmd": args.agent_cmd,
            "agent_timeout_sec": args.agent_timeout_sec,
            "exec_timeout_sec": args.exec_timeout_sec,
        }
    # config 与 argv 一致：显式同步 environment（补登 digest/platform 后
    # 不得残留旧登记值）——保存的 config.environment == 本次实际解析值。
    config["environment"] = env_record
    config["dry_run"] = bool(args.dry_run)
    run_id = config.get("run_id") or uuid.uuid4().hex[:12]
    config["run_id"] = run_id

    # 显式 agent 配置：只记录提供过的字段，缺省不伪造
    agent_config = {
        "agent_cmd": args.agent_cmd,
        "agent_timeout_sec": args.agent_timeout_sec,
    }
    if args.agent_config_json:
        try:
            extra = json.loads(
                args.agent_config_json.read_text(encoding="utf-8"))
            if isinstance(extra, dict):
                agent_config.update(extra)
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: --agent-config-json 不可读: {e}", file=sys.stderr)
            return 2
    config["agent"] = agent_config

    import setup as setup_mod
    plan = config.get("setup_plan")
    if not isinstance(plan, dict) or not plan.get("steps"):
        plan = setup_mod.build_setup_plan(
            manifest, task, skills_dir, skill_tree_hash, run_dir.name,
            env_record, run_id)
    config["setup_plan"] = plan
    container = plan["container_name"]

    state = {"status": STATUS_RUNNING, "task_id": task["task_id"],
             "run_dir": str(run_dir), "setup": None}
    setup_log: dict = {"steps": [], "ok": False}
    execution: dict = {
        "agent_cmd": args.agent_cmd,
        "agent_timeout_sec": args.agent_timeout_sec,
        "container_name": container,
        "run_id": run_id,
    }
    raw: dict = {"command_log": executor.log}

    # 登记 task 正文按 manifest 哈希核验后实际使用——喂给 agent 与导出的
    # 正文必须与登记一致
    try:
        task_text = check_task_file(manifest, task, args.dataset_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    injected_task = task_text if task_text.startswith("INTERNAL_INSTRUCTION") \
        else TASK_INSTRUCTION + task_text

    if not args.dry_run:
        # 在任何 Docker mutation 之前：占用 run 目录（mkdir 已存在即拒绝）
        # 并落盘完整 config（含最终 setup_plan/environment/run_id）与
        # status=running——先于状态存在的 pending 期间不允许任何执行。
        if not args.run_dir:
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                print(f"error: run dir already exists: {run_dir}",
                      file=sys.stderr)
                return 2
        _write_run_artifacts(run_dir, config=config, state=state,
                             execution=None, raw=None)

    def _finish_invalid(reason: str) -> int:
        state.update(status=STATUS_EXECUTED,
                     setup={"ok": setup_log["ok"]})
        execution.update(outcome=OUTCOME_INVALID, outcome_reason=reason)
        if not args.dry_run:
            run_dir.mkdir(parents=True, exist_ok=True)
            _write_run_artifacts(run_dir, config=config, state=state,
                                 execution=execution,
                                 raw={**raw, "setup_log": setup_log})
            print(json.dumps({"run_dir": str(run_dir), "outcome": "invalid",
                              "reason": reason}, ensure_ascii=False))
        else:
            print(json.dumps({"dry_run": True, "invalid_reason": reason,
                              "no_side_effects": True,
                              "commands": executor.log}, indent=2,
                             ensure_ascii=False))
        return 0

    # --- 1) 初始化 ----------------------------------------------------------
    if not _run_setup_steps(executor, plan, setup_log,
                            args.exec_timeout_sec, skills_dir):
        return _finish_invalid(INVALID_SETUP)

    # --- 2) 启动 agent（后台 pid 文件 + 输出落盘；TASK 经 --env 传入）-------
    start_res = _start_agent(executor, container, args.agent_cmd,
                             injected_task, args.exec_timeout_sec)
    if not start_res.ok and not executor.dry_run:
        # 启动失败仍尝试终止并记录——容器里可能已有半截 agent 进程
        term = _stop_agent(executor, container, args.exec_timeout_sec)
        execution["agent_termination"] = term
        return _finish_invalid(INVALID_RUNNER)

    # --- 3) 等待 agent 退出或任务超时 ---------------------------------------
    started = time.monotonic()
    deadline = started + args.agent_timeout_sec
    poll = _poll_agent_exit(executor, container, deadline,
                            args.exec_timeout_sec)
    execution["timed_out"] = poll["timed_out"]
    execution["duration_sec"] = 0.0 if args.dry_run \
        else time.monotonic() - started
    agent_exit_code = poll["exit_code"]

    # --- 4) 终止边界：对 dev UID 全量 TERM/KILL 并核验，失败 => invalid -----
    term = _stop_agent(executor, container, args.exec_timeout_sec)
    execution["agent_termination"] = term
    if not args.dry_run and not term["terminated"]:
        return _finish_invalid("agent_termination_failed")

    # docker 断连/命令错误是 infra 失败——立即 invalid，不记 task_timeout
    if poll.get("error") and not args.dry_run:
        return _finish_invalid("poll_infra_error: " + poll["error"])

    artifacts = _read_agent_artifacts(executor, container,
                                      args.exec_timeout_sec)
    execution["exit_code"] = agent_exit_code
    raw["agent_stdout"] = artifacts["agent_stdout"]
    raw["agent_stderr"] = artifacts["agent_stderr"]

    leak_res = executor.run(docker_exec_argv(
        container,
        f"if [ -e {CONTAINER_TEST_STAGING} ]; then echo LEAK; else echo clean; fi"),
        timeout=args.exec_timeout_sec)
    execution["test_visibility_check"] = {
        "staging_dir_probe": leak_res.stdout.strip(),
    }
    if not args.dry_run and leak_res.stdout.strip() == "LEAK":
        return _finish_invalid("test_leak_detected")

    # 终局证据：root 复核 dev UID 无存活进程（与判分前的二次核验独立）
    verify_res = executor.run(
        docker_exec_argv(container, dev_uid_check_shell()),
        timeout=args.exec_timeout_sec)
    execution["dev_process_verify"] = {
        "clean": bool(verify_res.ok
                      and verify_res.stdout.strip() == "1"),
        "stdout": verify_res.stdout.strip(),
        "error": verify_res.error,
    }
    if not args.dry_run and not execution["dev_process_verify"]["clean"]:
        return _finish_invalid("agent_termination_failed")

    diff_out: dict = {}
    _collect_diff(executor, container, diff_out, args.exec_timeout_sec)
    execution["diff"] = diff_out
    if not args.dry_run and not diff_out.get("ok", True):
        return _finish_invalid("diff_collection_failed")
    if (not args.dry_run and diff_out.get("head_after")
            and diff_out["head_after"] != repo_commit):
        return _finish_invalid("repo_head_mismatch")

    # 退出文件只表达 wrapper 语义：正常退出必写；timeout 下 wrapper 被杀、
    # 文件缺席是协议允许的，不参与终止判定（终止已由 UID 核验给出证据）。
    execution["exit_file_present"] = agent_exit_code is not None
    if poll["timed_out"]:
        execution.update(outcome=OUTCOME_FAIL,
                         outcome_reason="task_timeout")
    elif poll.get("error"):
        execution.update(outcome=OUTCOME_INVALID,
                         outcome_reason=INVALID_RUNNER,
                         runner_stderr=poll["error"])
    elif agent_exit_code is None:
        execution.update(outcome=OUTCOME_INVALID,
                         outcome_reason="exit_file_missing_no_timeout")
    elif agent_exit_code != 0:
        execution.update(outcome=OUTCOME_INVALID,
                         outcome_reason=INVALID_RUNNER,
                         runner_stderr=(artifacts["agent_stderr"]
                                        or "")[:2000])
    else:
        # exit 0：运行本身完成，任务成败交给判分
        execution.update(outcome=None, outcome_reason=None)
    state["status"] = STATUS_EXECUTED
    state["setup"] = {"ok": setup_log["ok"]}

    # --- 5) 轨迹导入只做诊断草稿：正式 trajectory 只能在有效终局判分后
    # 经 --export-only 导出——run 阶段 outcome 未定，写出的文件不得像
    # pipeline 可用产物。
    if args.trajectory_jsonl:
        try:
            traj = import_trajectory(
                args.trajectory_jsonl, task["task_id"], run_dir.name,
                execution["outcome"] or "pending",
                strict=True, allow_partial=True)
            draft = {**traj,
                     "diagnostic": "run-stage draft — export the formal "
                                   "trajectory via run.py --export-only "
                                   "after evaluation",
                     "task": task_text}
        except TrajectoryImportError as e:
            draft = {"task_id": task["task_id"], "run_id": run_dir.name,
                     "task": task_text, "outcome": execution["outcome"],
                     "steps": [], "diagnostic": str(e),
                     "trajectory_import": {"source": str(args.trajectory_jsonl)}}
        if not args.dry_run:
            write_json(run_dir / "trajectory_draft.json", draft)

    if not args.dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_run_artifacts(
            run_dir, config=config, state=state, execution=execution,
            raw={**raw, "setup_log": setup_log})
        print(json.dumps({"run_dir": str(run_dir),
                          "status": state["status"],
                          "outcome": execution["outcome"]},
                         ensure_ascii=False))
    else:
        print(json.dumps({
            "dry_run": True,
            "run_dir_would_be": str(run_dir),
            "config": config,
            "commands": executor.log,
            "no_side_effects": True,
        }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
