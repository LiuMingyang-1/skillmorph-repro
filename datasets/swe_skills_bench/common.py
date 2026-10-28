"""SWE-Skills-Bench 数据集适配的共享工具。

固定输入加载、sha256、Skill 树哈希、Docker 命令构造、Executor（dry_run
下只记录不执行）、JUnit 解析、运行目录约定与共享执行证据门。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = DATASET_DIR / "manifest.json"

CONTAINER_REPO_DIR = "/workspace/python"
CONTAINER_TEST_STAGING = "/tmp/benchmark_tests"
CONTAINER_SKILLS_DIR = "/home/dev/.claude/skills"
CONTAINER_AGENT_PID = "/tmp/agent.pid"
CONTAINER_AGENT_EXIT = "/tmp/agent.exit"
CONTAINER_AGENT_OUT = "/tmp/agent.stdout"
CONTAINER_AGENT_ERR = "/tmp/agent.stderr"
CONTAINER_DEV_USER = "dev"

# 运行状态（status 字段，持久化到 run_state.json）
#   pending    已登记，尚未开始
#   running    初始化/执行中
#   executed   agent 执行结束，尚未判分（含 setup/runner invalid 情形）
#   evaluated  已判分（evaluation.outcome 有效）
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_EXECUTED = "executed"
STATUS_EVALUATED = "evaluated"

# 判分结论（evaluation.outcome / execution.outcome）
OUTCOME_SUCCESS = "success"
OUTCOME_FAIL = "fail"
OUTCOME_INVALID = "invalid"

# invalid 细分原因
INVALID_SETUP = "setup_failure"
INVALID_RUNNER = "runner_error"
INVALID_EVALUATOR = "evaluator_error"

# 固定执行身份：kill/pkill -U 按 UID 匹配，整个终止边界协议依赖它
_EXEC_IDENTITY = CONTAINER_DEV_USER


# dev-UID 存活进程枚举规则（内联在 kill/check shell 中）：排除容器
# init（PID 1）与僵尸（Z state——容器 init ``sleep infinity`` 不
# wait() 孤儿，被杀的 agent 后代长期以 defunct 滞留，若计入则永
# 远判定「有残余」）。存活 = 非 PID 1 且 /proc stat 非 Z。
# /proc/<pid>/stat 的 comm 字段可含空格与括号（进程名截断 15 字节
# 内允许任意字符），按空白取 $3 会错位——必须取最后一个 ')' 之
# 后的第一个字段。pgrep 退出码语义：0=有匹配 / 1=无匹配 / 其它
# =工具异常（fail closed，不得当「无残余」处理）。

# POSIX sh 函数：从 /proc/<pid>/stat 提取 state 字段（最后一
# 个 ')' 之后第一个空白分隔字段）。读取失败输出空串。
_PROC_STATE_FN = (
    '_st() { '
    'read -r _l < /proc/$1/stat 2>/dev/null || { echo; return; }; '
    '_l=${_l##*) }; echo "${_l%% *}"; '
    '}; '
)


def dev_uid_kill_shell() -> str:
    """对 dev UID 下全部**存活非 init**进程 TERM→KILL（root 侧执行）。

    pgrep 异常 → 非零退出（fail closed）；kill 送错不阻断，终止判
    定由 dev_uid_check_shell 的存活性核验给出。
    """
    u = _EXEC_IDENTITY
    return (
        _PROC_STATE_FN +
        f"pgrep_rc=0; pids=$(pgrep -U {u} 2>/dev/null) || pgrep_rc=$?; "
        f"case $pgrep_rc in 0|1) : ;; *) exit $pgrep_rc ;; esac; "
        f"for p in $pids; do "
        f"st=$(_st \"$p\"); "
        f"[ \"$p\" != \"1\" ] && [ \"$st\" != \"Z\" ] "
        f"&& kill -TERM \"$p\" 2>/dev/null; done; "
        f"sleep 2; "
        f"pgrep_rc=0; pids=$(pgrep -U {u} 2>/dev/null) || pgrep_rc=$?; "
        f"case $pgrep_rc in 0|1) : ;; *) exit $pgrep_rc ;; esac; "
        f"for p in $pids; do "
        f"st=$(_st \"$p\"); "
        f"[ \"$p\" != \"1\" ] && [ \"$st\" != \"Z\" ] "
        f"&& kill -KILL \"$p\" 2>/dev/null; done; "
        f"exit 0")


def dev_uid_check_shell() -> str:
    """核验 dev UID 无存活非 init 进程；stdout 输出 1（无）/0（有）。

    pgrep 异常（退出码 >=2）→ shell 非零退出，fail closed。
    """
    u = _EXEC_IDENTITY
    return (
        _PROC_STATE_FN +
        f"pgrep_rc=0; pids=$(pgrep -U {u} 2>/dev/null) || pgrep_rc=$?; "
        f"case $pgrep_rc in "
        f"0|1) : ;; "
        f"*) echo \"pgrep -U {u} exited $pgrep_rc\" >&2; "
        f"exit $pgrep_rc ;; esac; "
        f"leftover=0; "
        f"for p in $pids; do "
        f"st=$(_st \"$p\"); "
        f"[ \"$p\" != \"1\" ] && [ \"$st\" != \"Z\" ] && leftover=1; "
        f"done; "
        f"echo $((1 - leftover))")


def build_cleanup_plan(container: str) -> dict:
    """只清本 run 容器的显式清理计划（默认保留 artifacts）。"""
    return {
        "container_name": container,
        "steps": [{
            "name": "remove_run_container",
            "docker_argv": [["docker", "rm", "-f", container]],
            "allow_failure": True,
            "purpose": "remove only this run's container; run artifacts "
                       "are kept on the host",
        }],
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _iter_tree_files(root: Path) -> list[Path]:
    root = Path(root).resolve()
    return [p for p in root.rglob("*") if p.is_file()]


def check_skills_dir(skills_dir: Path) -> Path:
    """校验 Skill 根：必须是非空目录。"""
    skills_dir = Path(skills_dir).resolve()
    if not skills_dir.is_dir():
        raise ValueError(f"skills dir does not exist: {skills_dir}")
    if not _iter_tree_files(skills_dir):
        raise ValueError(f"skills dir is an empty tree: {skills_dir}")
    return skills_dir


def tree_sha256(root: Path) -> str:
    """对一棵 Skill/文件树计算确定性哈希（相对路径 + 内容）。"""
    root = Path(root)
    if root.is_file():
        return sha256_file(root)
    h = hashlib.sha256()
    for path in sorted(_iter_tree_files(root)):
        rel = path.relative_to(root.resolve()).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def skill_tree_listing(root: Path) -> list[str]:
    """``<sha256>  ./<relpath>`` 排序清单，与容器内
    ``find . -type f -exec sha256sum {} + | sort -k2`` 格式一致。
    """
    root = Path(root)
    lines = []
    for path in sorted(_iter_tree_files(root)):
        rel = "./" + path.relative_to(root.resolve()).as_posix()
        lines.append(f"{sha256_file(path)}  {rel}")
    return lines


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST_PATH).read_text(encoding="utf-8"))


def get_task(manifest: dict, task_id: str) -> dict:
    for task in manifest["tasks"]:
        if task["task_id"] == task_id:
            return task
    known = [t["task_id"] for t in manifest["tasks"]]
    raise KeyError(f"unknown task_id {task_id!r}; known: {known}")


def task_is_runnable(task: dict) -> bool:
    """只有 manifest 显式标 ``status == "ready"`` 的任务才可真实执行。"""
    return task.get("status") == "ready"


def check_task_file(manifest: dict, task: dict,
                    dataset_dir: Path | None = None) -> str:
    """读取任务正文并返回文本；文件缺失抛 ValueError。"""
    dataset_dir = Path(dataset_dir or DATASET_DIR)
    rel = task["task_file"]
    path = dataset_dir / rel
    if not path.is_file():
        raise ValueError(f"missing file: {rel}")
    return path.read_text(encoding="utf-8")


def shlex_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def docker_exec_argv(container: str, shell: str, user: str | None = None) -> list[str]:
    """容器内 ``sh -c`` 执行 argv；``user`` 非空时加 ``--user``。"""
    argv = ["docker", "exec"]
    if user:
        argv += ["--user", user]
    argv += [container, "sh", "-c", shell]
    return argv


def docker_env_exec_argv(container: str, shell: str, *,
                         env: dict[str, str] | None = None,
                         user: str | None = None) -> list[str]:
    """带 ``--env KEY=VAL`` 的 ``docker exec`` argv。

    长字符串（task 文本等）走 --env 由容器内 sh 展开，不经宿主 shell。
    """
    argv = ["docker", "exec"]
    if user:
        argv += ["--user", user]
    for k, v in (env or {}).items():
        argv += ["--env", f"{k}={v}"]
    argv += [container, "sh", "-c", shell]
    return argv


# ---------------------------------------------------------------------------
# 执行器：真实模式走 subprocess；dry_run 只记录不执行
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool = False
    error: str | None = None  # OSError 等启动失败（区分于命令非零退出）

    @property
    def ok(self) -> bool:
        """命令正常启动且 exit 0。"""
        return self.error is None and not self.timed_out and self.exit_code == 0


@dataclass
class Executor:
    """子进程执行器。``dry_run=True`` 时只记录不执行。"""

    dry_run: bool = False
    log: list[dict] = field(default_factory=list)

    def run(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
        env: dict | None = None,
        input_bytes: bytes | None = None,
    ) -> CommandResult:
        argv = list(argv)
        entry: dict = {"argv": argv, "cwd": str(cwd) if cwd else None}
        if timeout is not None:
            entry["timeout_sec"] = timeout
        self.log.append(entry)
        if self.dry_run:
            entry["dry_run"] = True
            return CommandResult(
                argv=list(argv),
                exit_code=None,
                stdout="",
                stderr="",
                duration_sec=0.0,
            )
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd) if cwd else None,
                env=env,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
            )
            result = CommandResult(
                argv=list(argv),
                exit_code=proc.returncode,
                stdout=proc.stdout.decode("utf-8", errors="replace"),
                stderr=proc.stderr.decode("utf-8", errors="replace"),
                duration_sec=time.monotonic() - start,
            )
        except subprocess.TimeoutExpired as e:
            result = CommandResult(
                argv=list(argv),
                exit_code=None,
                stdout=(e.stdout or b"").decode("utf-8", errors="replace")
                if isinstance(e.stdout, (bytes, bytearray))
                else (e.stdout or ""),
                stderr=(e.stderr or b"").decode("utf-8", errors="replace")
                if isinstance(e.stderr, (bytes, bytearray))
                else (e.stderr or ""),
                duration_sec=time.monotonic() - start,
                timed_out=True,
            )
        except OSError as e:
            # docker 不存在/不可执行等：记录为启动失败而非「命令成功」
            result = CommandResult(
                argv=list(argv),
                exit_code=None,
                stdout="",
                stderr=str(e),
                duration_sec=time.monotonic() - start,
                error=f"{type(e).__name__}: {e}",
            )
        entry["exit_code"] = result.exit_code
        entry["timed_out"] = result.timed_out
        entry["duration_sec"] = result.duration_sec
        if result.error:
            entry["error"] = result.error
        entry["stdout_tail"] = result.stdout[-1000:]
        entry["stderr_tail"] = result.stderr[-1000:]
        return result


# ---------------------------------------------------------------------------
# 执行证据门（evaluate 判分前 / run --export-only 共用）
# ---------------------------------------------------------------------------


def verify_execution_evidence(run_dir: Path, config: dict,
                              exec_ev: dict,
                              state: dict | None = None) -> str | None:
    """返回 None（证据完备）或拒绝原因。evaluate 判分与 run --export-only 共用。

    核验：容器名/run_id 与 config 登记一致、agent_termination.terminated、
    dev_process_verify.clean、diff.ok 与 diff.head_after == repo commit；
    传入 ``state`` 时同时核验 ``state.setup.ok``。
    execution.outcome == invalid 时跳过终止类证据——调用方走尊重协议。
    """
    plan = config.get("setup_plan") or {}
    if exec_ev.get("container_name") != plan.get("container_name"):
        return ("container identity mismatch: execution ran "
                f"{exec_ev.get('container_name')!r} but plan registered "
                f"{plan.get('container_name')!r}")
    if exec_ev.get("run_id") and config.get("run_id") \
            and exec_ev["run_id"] != config["run_id"]:
        return (f"execution run_id {exec_ev['run_id']!r} != config run_id "
                f"{config['run_id']!r}")
    if exec_ev.get("outcome") == OUTCOME_INVALID:
        return None
    term = exec_ev.get("agent_termination")
    if not isinstance(term, dict) or term.get("terminated") is not True:
        return ("no verified agent termination "
                "(agent_termination.terminated="
                f"{(term or {}).get('terminated')!r})")
    dpv = exec_ev.get("dev_process_verify")
    if not isinstance(dpv, dict) or dpv.get("clean") is not True:
        return ("post-stop dev-UID process verify missing or not clean "
                f"(dev_process_verify.clean={(dpv or {}).get('clean')!r})")
    if state is not None:
        setup_ev = state.get("setup") or {}
        if setup_ev.get("ok") is not True:
            return f"setup not verified ok ({setup_ev!r})"
    diff = exec_ev.get("diff") or {}
    if diff.get("ok") is False:
        return "diff collection recorded as incomplete"
    repo_pin = (config.get("repo") or {}).get("commit")
    head_after = diff.get("head_after")
    if repo_pin:
        if not head_after:
            return "no HEAD evidence recorded (diff.head_after missing)"
        if head_after != repo_pin:
            return (f"repo HEAD moved off the pinned commit "
                    f"({head_after} != {repo_pin})")
    return None


def load_execution_evidence(run_dir: Path) -> tuple[dict | None, str | None]:
    """读 run_dir/execution.json；返回 (evidence, 拒绝原因)。"""
    exec_path = Path(run_dir) / "execution.json"
    if not exec_path.is_file():
        return None, "execution.json missing — required evidence absent"
    try:
        return read_json(exec_path), None
    except Exception as e:
        return None, f"execution.json unreadable: {e}"


# ---------------------------------------------------------------------------
# JUnit XML 解析：判分的首选事实来源
# ---------------------------------------------------------------------------


@dataclass
class PytestStats:
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_sec: float | None
    failed_tests: list[str]
    skipped_tests: list[str]
    testcase_count: int  # 实际解析到的 <testcase> 数，用于完整性核验
    test_names: list[str] = field(default_factory=list)
    # 每个 testcase 的 name（不含 parametrization id）——供与 manifest
    # 登记的 test_count/test_functions 核对使用


def parse_junit_xml(text: str) -> PytestStats:
    """解析 pytest ``--junitxml`` 输出为统计。

    testsuite/testsuites 两种根都接受。skip/error 分开统计，不并入
    passed。逐 case 状态分类后的计数与 suite 的
    ``tests``/``failures``/``errors``/``skipped`` 属性不一致即
    ValueError——判分层据此判 invalid 而不是硬算。
    """
    root = ET.fromstring(text)
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = [s for s in root if s.tag == "testsuite"]
    else:
        raise ValueError(f"unexpected junit root <{root.tag}>")

    total = passed = failed = skipped = errors = 0
    duration = 0.0
    have_duration = False
    failed_tests: list[str] = []
    skipped_tests: list[str] = []
    testcase_count = 0
    test_names: list[str] = []
    for suite in suites:
        s_tests = int(suite.get("tests") or 0)
        s_failures = int(suite.get("failures") or 0)
        s_errors = int(suite.get("errors") or 0)
        s_skipped = int(suite.get("skipped") or 0)
        t = suite.get("time")
        if t is not None:
            tf = float(t)
            if not math.isfinite(tf) or tf < 0:
                raise ValueError(f"invalid suite time={t!r}")
            duration += tf
            have_duration = True

        c_failures = c_errors = c_skipped = c_cases = 0
        for case in suite.iter("testcase"):
            c_cases += 1
            raw_name = case.get('name', '')
            test_names.append(raw_name.split("[", 1)[0])
            name = f"{case.get('classname','')}::{raw_name}"
            if case.find("failure") is not None:
                c_failures += 1
                failed_tests.append(name)
            elif case.find("error") is not None:
                c_errors += 1
                failed_tests.append(name)
            elif case.find("skipped") is not None:
                c_skipped += 1
                skipped_tests.append(name)

        # suite 属性与实际子 case 分类必须一致
        mismatch = []
        for attr, count, tag in (
                ("tests", c_cases, "testcase"),
                ("failures", c_failures, "<failure>"),
                ("errors", c_errors, "<error>"),
                ("skipped", c_skipped, "<skipped>")):
            expected = int(suite.get(attr) or 0)
            if count != expected:
                mismatch.append(f"{attr}={expected} vs {count} {tag}")
        if mismatch:
            raise ValueError("junit suite attrs disagree with cases: "
                             + "; ".join(mismatch))

        total += s_tests
        failed += c_failures
        errors += c_errors
        skipped += c_skipped
        testcase_count += c_cases

    passed = total - failed - errors - skipped
    return PytestStats(
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_sec=duration if have_duration else None,
        failed_tests=failed_tests,
        skipped_tests=skipped_tests,
        testcase_count=testcase_count,
        test_names=test_names,
    )


# ---------------------------------------------------------------------------
# 结果与运行目录约定
# ---------------------------------------------------------------------------

def next_run_dir(output_root: Path) -> Path:
    """在 output_root 下选下一个不存在的 run_NNN 目录名（不创建）。"""
    output_root = Path(output_root)
    n = 1
    if output_root.is_dir():
        for child in output_root.iterdir():
            m = re.match(r"run_(\d+)$", child.name)
            if m:
                n = max(n, int(m.group(1)) + 1)
    return output_root / f"run_{n:03d}"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def base_environment_record(manifest: dict) -> dict:
    env = manifest.get("environment", {})
    return {
        "docker_image": env.get("docker_image"),
        "docker_image_digest": env.get("docker_image_digest"),
        "docker_image_platform": env.get("docker_image_platform"),
    }


def resolve_image_ref(env_record: dict) -> str:
    """固定镜像引用：有 digest 时 ``image@sha256:...``，否则退回 tag。
    未知引用标 ``unknown-image``，不伪造。
    """
    image = env_record.get("docker_image")
    digest = env_record.get("docker_image_digest")
    if image and digest:
        return f"{image}@{digest}"
    return image or "unknown-image"


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLATFORM_RE = re.compile(r"^[a-z0-9]+/[a-z0-9_]+(?:/[a-z0-9_]+)?$")


def validate_env_record(env_record: dict) -> list[str]:
    """已提供的 digest/platform 必须格式合法；缺失属合法（返回空列表）。

    只核对格式；缺失值由调用方决定（真实执行拒绝，dry-run 可展示 unknown）。
    """
    errors: list[str] = []
    digest = env_record.get("docker_image_digest")
    if digest and not _DIGEST_RE.match(digest):
        errors.append(
            f"docker_image_digest {digest!r} must match "
            "'sha256:' + 64 lowercase hex")
    platform = env_record.get("docker_image_platform")
    if platform and not _PLATFORM_RE.match(platform):
        errors.append(
            f"docker_image_platform {platform!r} must look like "
            "'linux/amd64' (os/arch[/variant])")
    return errors
