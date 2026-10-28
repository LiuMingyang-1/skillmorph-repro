"""数据集适配层离线测试共用的夹具。

只使用 stdlib/临时目录/假 pytest 输出；绝不调用 docker、不 clone、不联网、
不启动模型、也不运行 tests/ 下的原版验收测试。
"""

import json
import sys
from pathlib import Path

import pytest

ADAPTER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADAPTER_DIR))

import common  # noqa: E402
import evaluate  # noqa: E402
import run as run_mod  # noqa: E402
import setup as setup_mod  # noqa: E402

DATASET_DIR = ADAPTER_DIR


@pytest.fixture()
def manifest():
    return common.load_manifest(DATASET_DIR / "manifest.json")


@pytest.fixture()
def skills_dir(tmp_path):
    root = tmp_path / "skills"
    (root / "tdd-workflow").mkdir(parents=True)
    (root / "tdd-workflow" / "SKILL.md").write_text("# tdd\n")
    return root


@pytest.fixture()
def repo_stub(tmp_path):
    """假的上游 scaffold：含 python_starter/calculator.py 和 tests/。"""
    repo = tmp_path / "repo"
    (repo / "src" / "python_starter").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "python_starter" / "__init__.py").write_text("")
    (repo / "src" / "python_starter" / "calculator.py").write_text(
        "def add(numbers):\n    return 0\n")
    (repo / "tests" / "test_calculator.py").write_text(
        "def test_placeholder():\n    assert True\n")
    return repo


def make_junit(total, failures=0, errors=0, skipped=0, cases=None):
    """构造一份最小 JUnit XML 文本。

    ``cases`` 是 [(name, kind)]；同名 case 自动加 ``#i`` 后缀保证唯一
    （真实 pytest 不产生重名 testcase，fixture 也不该产生）。
    """
    cases_xml = ""
    if cases is not None:
        seen = {}
        for name, kind in cases:
            inner = ""
            if kind == "failure":
                inner = "<failure>bad</failure>"
            elif kind == "error":
                inner = "<error>oops</error>"
            elif kind == "skipped":
                inner = "<skipped/>"
            n = seen.get(name, 0)
            seen[name] = n + 1
            cname = name if n == 0 else f"{name}#{n}"
            cases_xml += f'<testcase classname="T" name="{cname}">{inner}</testcase>'
    else:
        for i in range(total):
            cases_xml += f'<testcase classname="T" name="t{i}"/>'
    return (
        f'<testsuite tests="{total}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}" time="1.5">'
        f"{cases_xml}</testsuite>"
    )


def make_run_dir(tmp_path, *, task_id="tdd-workflow-batch1", status="executed",
                 execution=None, skills_dir=None, manifest=None,
                 execution_evidence="full", evaluation=None):
    """造一个 run_NNN 目录，含 config.json/run_state.json/execution.json。

    ``execution`` 合并进 execution.json；skills_dir 给出时写入
    config.skills.host_dir/tree_sha256 实算值。

    execution_evidence="full" 时 execution.json 带完整终止/核验证据
    （evaluate 的证据门要求：agent_termination.terminated=true、
    dev_process_verify.clean、容器名与 plan 一致、HEAD 固定 commit）；
    "none" 时不写 execution.json；dict 则原样写入。
    """
    run_dir = tmp_path / "run_001"
    run_dir.mkdir(exist_ok=True)
    container = f"swesk-{task_id}-run_001-aa11bb22cc33"
    cfg = {
        "task_id": task_id,
        "task_file": f"tasks/{task_id}.md",
        "setup_plan": {"container_name": container},
    }
    if skills_dir is not None:
        cfg["skills"] = {
            "host_dir": str(skills_dir),
            "container_dir": common.CONTAINER_SKILLS_DIR,
            "tree_sha256": common.tree_sha256(skills_dir),
        }
    if manifest is not None:
        cfg["repo"] = manifest["repo"]
    (run_dir / "config.json").write_text(json.dumps(cfg))
    state = {
        "status": status,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "setup": {"ok": True},
    }
    (run_dir / "run_state.json").write_text(json.dumps(state))
    if evaluation is not None:
        rec = {"task_id": task_id, "test_file":
               f"tests/batch1/test_tdd_workflow.py", **evaluation}
        (run_dir / "evaluation.json").write_text(json.dumps(rec))
    if isinstance(execution_evidence, dict):
        (run_dir / "execution.json").write_text(
            json.dumps(execution_evidence))
    elif execution_evidence == "full":
        head = (manifest or {}).get("repo", {}).get("commit", "")
        (run_dir / "execution.json").write_text(json.dumps({
            "agent_termination": {"terminated": True},
            "dev_process_verify": {"clean": True},
            "diff": {"head_after": head, "ok": True},
            "container_name": container,
            **(execution or {}),
        }))
    return run_dir
