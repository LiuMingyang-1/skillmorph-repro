"""common.py 的纯函数测试：哈希、判分统计、dry-run 执行器、树哈希。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import (  # noqa: E402
    Executor,
    check_task_file,
    dev_uid_check_shell,
    dev_uid_kill_shell,
    parse_junit_xml,
    resolve_image_ref,
    sha256_file,
    skill_tree_listing,
    task_is_runnable,
    tree_sha256,
    validate_env_record,
)

from conftest import make_junit  # noqa: E402


def test_tree_sha256_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a"
    (a / "x").mkdir(parents=True)
    (a / "x" / "f.txt").write_text("hello")
    h1 = tree_sha256(a)
    (a / "x" / "g.txt").write_text("world")
    h2 = tree_sha256(a)
    assert h1 != h2
    (a / "x" / "g.txt").write_text("worle")
    assert tree_sha256(a) != h2
    # 单文件退化为内容哈希
    assert tree_sha256(a / "x" / "f.txt") == sha256_file(a / "x" / "f.txt")


def test_skill_tree_listing_matches_sha256sum_format(tmp_path):
    root = tmp_path / "skills"
    (root / "s1").mkdir(parents=True)
    (root / "s1" / "SKILL.md").write_text("# s\n")
    (root / "s1" / "ref" ).mkdir()
    (root / "s1" / "ref" / "a.txt").write_text("a\n")
    lines = skill_tree_listing(root)
    assert lines == sorted(lines, key=lambda ln: ln.split("  ", 1)[1])
    for ln in lines:
        digest, rel = ln.split("  ", 1)
        assert len(digest) == 64
        assert rel.startswith("./")
        assert (root / rel[2:]).is_file()


class TestParseJunit:
    def test_all_passed(self):
        s = parse_junit_xml(make_junit(14, cases=[("t0", None)] * 14))
        assert (s.total, s.passed, s.failed, s.errors, s.skipped) == \
            (14, 14, 0, 0, 0)
        assert s.testcase_count == 14
        assert s.failed_tests == []

    def test_mixed_outcomes(self):
        cases = [("ok1", None), ("bad1", "failure"),
                 ("err1", "error"), ("sk1", "skipped"), ("ok2", None)]
        s = parse_junit_xml(make_junit(5, failures=1, errors=1,
                                     skipped=1, cases=cases))
        assert (s.passed, s.failed, s.errors, s.skipped) == (2, 1, 1, 1)
        assert "T::bad1" in s.failed_tests
        assert "T::sk1" in s.skipped_tests

    def test_testsuites_root(self):
        xml = ('<testsuites>' + make_junit(2, cases=[("a", None), ("b", None)])
               + "</testsuites>")
        s = parse_junit_xml(xml)
        assert s.total == 2 and s.passed == 2

    def test_zero_tests(self):
        s = parse_junit_xml(make_junit(0))
        assert s.total == 0 and s.passed == 0

    def test_bad_xml_raises(self):
        with pytest.raises(Exception):
            parse_junit_xml("<notxml")


class TestExecutor:
    def test_dry_run_no_side_effects(self, tmp_path):
        ex = Executor(dry_run=True)
        target = tmp_path / "victim"
        res = ex.run(["rm", "-rf", str(target)])
        assert res.exit_code is None
        assert not target.exists()
        assert len(ex.log) == 1
        assert ex.log[0]["dry_run"] is True

    def test_real_run_executes(self):
        ex = Executor(dry_run=False)
        res = ex.run([sys.executable, "-c", "print('hi')"])
        assert res.exit_code == 0 and "hi" in res.stdout
        assert res.error is None

    def test_oserror_recorded_not_success(self):
        ex = Executor(dry_run=False)
        res = ex.run(["/nonexistent/definitely-missing-binary-xyz"])
        assert res.exit_code is None
        assert res.error is not None
        assert not res.ok

    def test_none_timeout_is_success_when_exit0(self):
        """timeout=None 时不得误判成功——exit_code 0 就是成功。"""
        ex = Executor(dry_run=False)
        res = ex.run([sys.executable, "-c", "pass"], timeout=None)
        assert res.ok


def test_resolve_image_ref():
    assert resolve_image_ref({"docker_image": "img", "docker_image_digest": None}) == "img"
    assert resolve_image_ref({"docker_image": "img",
                              "docker_image_digest": "sha256:ab"}) == "img@sha256:ab"
    assert resolve_image_ref({}) == "unknown-image"


def test_task_is_runnable(manifest):
    t = {t_["task_id"]: t_ for t_ in manifest["tasks"]}
    assert task_is_runnable(t["tdd-workflow-batch1"]) is True
    assert task_is_runnable(t["tdd-workflow-batch9"]) is False  # unsuitable
    assert task_is_runnable(t["tdd-workflow-batch10"]) is False  # pending_cov
    assert task_is_runnable({"task_id": "x"}) is False  # 无 status


def _stub_bin(tmp_path, name, script):
    d = tmp_path / "stubbin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(script)
    p.chmod(0o755)
    return d


def _run_sh_with_path(shell, stub_dir):
    """真实 sh 调用，PATH 指向 stub 目录（不真正 kill/pgrep）。"""
    import os, subprocess
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{os.environ.get('PATH','')}"
    return subprocess.run(["sh", "-c", shell], env=env,
                          capture_output=True, text=True, timeout=10)


class TestDevUidShellRealSh:
    """pgrep/pkill 退出码语义：纯 shell PATH stub 真实 sh 调用（绝不真杀进程）。"""

    def test_pgrep_exit0_means_alive_output0(self, tmp_path):
        stub = _stub_bin(tmp_path, "pgrep", "#!/bin/sh\nexit 0\n")
        r = _run_sh_with_path(dev_uid_check_shell(), stub)
        assert r.returncode == 0 and r.stdout.strip() == "0"

    def test_pgrep_exit1_means_dead_output1(self, tmp_path):
        stub = _stub_bin(tmp_path, "pgrep", "#!/bin/sh\nexit 1\n")
        r = _run_sh_with_path(dev_uid_check_shell(), stub)
        assert r.returncode == 0 and r.stdout.strip() == "1"

    def test_pgrep_exit2_fails_not_dead(self, tmp_path):
        stub = _stub_bin(tmp_path, "pgrep",
                         "#!/bin/sh\necho 'pgrep: invalid option' >&2\nexit 2\n")
        r = _run_sh_with_path(dev_uid_check_shell(), stub)
        assert r.returncode != 0 and "invalid option" in r.stderr
        assert r.stdout.strip() not in ("0", "1")

    def test_pgrep_127_fails_not_dead(self, tmp_path):
        stub = _stub_bin(tmp_path, "pgrep", "#!/bin/sh\nexit 127\n")
        r = _run_sh_with_path(dev_uid_check_shell(), stub)
        assert r.returncode != 0

    def test_pkill_0_and_1_legal(self, tmp_path):
        stub = _stub_bin(tmp_path, "pkill", "#!/bin/sh\nexit ${PKILL_RC:-1}\n")
        for rc in (0, 1):
            import os
            os.environ["PKILL_RC"] = str(rc)
            r = _run_sh_with_path(dev_uid_kill_shell(), stub)
            assert r.returncode == 0, rc

    def test_pkill_2_fails(self, tmp_path):
        stub = _stub_bin(tmp_path, "pkill",
                         "#!/bin/sh\necho 'pkill: bad flag' >&2\nexit 2\n")
        r = _run_sh_with_path(dev_uid_kill_shell(), stub)
        assert r.returncode != 0 and "bad flag" in r.stderr

    def test_pkill_127_fails(self, tmp_path):
        stub = _stub_bin(tmp_path, "pkill", "#!/bin/sh\nexit 127\n")
        r = _run_sh_with_path(dev_uid_kill_shell(), stub)
        assert r.returncode != 0


def test_validate_env_record():
    assert validate_env_record({}) == []
    assert validate_env_record({"docker_image_digest": None}) == []
    ok = {"docker_image_digest": "sha256:" + "ab" * 32,
          "docker_image_platform": "linux/amd64"}
    assert validate_env_record(ok) == []
    assert validate_env_record({"docker_image_digest": "sha256:short"})
    assert validate_env_record({"docker_image_digest": "md5:" + "ab" * 32})
    assert validate_env_record({"docker_image_platform": "LINUX/amd64"})
    assert validate_env_record({"docker_image_platform": "weird"})
    assert validate_env_record(
        {"docker_image_platform": "linux/arm64/v8"}) == []


def test_check_task_file_reads_text(manifest):
    task = next(t for t in manifest["tasks"]
                if t["task_id"] == "tdd-workflow-batch1")
    text = check_task_file(manifest, task)
    assert "Smart Coupon Calculator" in text
