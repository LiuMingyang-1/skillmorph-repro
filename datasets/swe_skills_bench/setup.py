#!/usr/bin/env python3
"""SWE-Skills-Bench 运行目录登记与初始化计划（不执行 Docker）。

从 manifest 核对任务/测试/Skill 哈希，在 --output-dir 下分配 run_NNN 并
写入 ``config.json`` + ``run_state.json``（status=pending），构建 setup
plan（rm/create/start/precheck dev/clone/审计/Skill 注入/所有权/泄漏检查）。

计划步骤含两种命令组：``docker_argv``（宿主 argv list）与
``container_shell``（经 ``docker exec <container> sh -c`` 逐行执行）；
同一步内 docker_argv 排在 container_shell 之前，``verify.kind ==
file_listing_sha256`` 时 container_shell 输出与宿主清单逐行比对。

用法：
  python setup.py --task-id tdd-workflow-batch1 \
      --skills-dir /abs/path/to/skills \
      --output-dir /abs/path/to/experiment/runs \
      [--image-digest sha256:...] [--image-platform linux/arm64] \
      [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from common import (
    CONTAINER_REPO_DIR,
    CONTAINER_SKILLS_DIR,
    CONTAINER_TEST_STAGING,
    DATASET_DIR,
    STATUS_PENDING,
    base_environment_record,
    check_skills_dir,
    get_task,
    load_manifest,
    next_run_dir,
    resolve_image_ref,
    shlex_join,
    task_is_runnable,
    tree_sha256,
    validate_env_record,
    write_json,
)


def build_setup_plan(manifest: dict, task: dict, skills_dir: Path,
                     skill_tree_hash: str, run_name: str,
                     env_record: dict | None = None,
                     run_id: str | None = None) -> dict:
    """生成初始化阶段的命令计划（不执行）。

    - 容器名含 run_NNN + run_id 哈希，跨输出根不冲突；``docker rm -f``
      先清同名残留，``--entrypoint sleep ... infinity`` 保活，镜像引用
      优先 ``image@sha256:digest`` + 显式 ``--platform``；
    - dev 身份预检（存在、非 root、无 sudo）——执行/终止协议依赖该 UID；
    - clone 固定到 manifest.repo.commit，目标非空即拒绝，``rev-parse HEAD``
      逐一比对；清残留 ``.claude``；
    - ``/home/dev/.claude/skills`` 清空后注入本次 Skill 树，注入后容器内
      重算逐文件哈希清单与宿主比对；
    - 收尾 chown 给 dev 并验证可写，dev 不存在即 setup 失败。
    """
    repo = manifest["repo"]
    env_record = env_record or base_environment_record(manifest)
    ident = (run_id or run_name or "unknown")[:12]
    container = f"swesk-{task['task_id']}-{run_name}-{ident}"
    ws = CONTAINER_REPO_DIR
    ws_q = shlex_join([ws])
    image_ref = resolve_image_ref(env_record)
    platform = env_record.get("docker_image_platform")

    create_argv = ["docker", "create", "--name", container]
    if platform:
        create_argv += ["--platform", platform]
    create_argv += [
        "--workdir", "/workspace",
        "--network", manifest["environment"].get("network_mode", "bridge"),
        "--entrypoint", "sleep",
        "--tty",
        image_ref, "infinity",
    ]

    commit_q = shlex_join([repo["commit"]])
    return {
        "container_name": container,
        "image": env_record.get("docker_image"),
        "image_ref": image_ref,
        "image_platform": platform,
        "steps": [
            {
                "name": "remove_stale_container",
                "docker_argv": [["docker", "rm", "-f", container]],
                "allow_failure": True,
                "purpose": "per-run container name should not exist; "
                           "clears leftovers of an aborted run with the same run dir",
            },
            {
                "name": "create_container",
                "docker_argv": [create_argv],
            },
            {
                "name": "start_container",
                "docker_argv": [["docker", "start", container]],
            },
            {
                "name": "precheck_dev_identity",
                "container_shell": [
                    # 固定执行身份：dev 必须存在、非 root、无 sudo——
                    # 终止边界（pkill -U dev 全量 TERM/KILL）依赖它
                    "id -u dev >/dev/null 2>&1 && "
                    "test \"$(id -u dev)\" != \"0\"",
                    "! sudo -l -U dev >/dev/null 2>&1",
                    # pgrep/pkill 必须存在且支持 -U（busybox 无此 flag →
                    # 协议失效）；对存在的 UID 只应返回 0/1，>=2 fail closed
                    "command -v pgrep >/dev/null && "
                    "command -v pkill >/dev/null",
                    "pgrep -U dev >/dev/null 2>&1; "
                    "rc=$?; test $rc -eq 0 -o $rc -eq 1",
                ],
                "purpose": "dev must exist, be non-root, and have no sudo — "
                           "the UID-scoped kill/verify boundary relies on it; "
                           "pgrep/pkill with -U support must exist "
                           "(unknown => fail closed)",
            },
            {
                "name": "clone_repo",
                "container_shell": [
                    f"if [ -d {ws_q} ] && [ -n \"$(ls -A {ws_q} 2>/dev/null)\" ]; then "
                    f"echo 'refusing to clone into non-empty {ws}; recreate the container' >&2; "
                    f"exit 1; fi",
                    f"mkdir -p {ws_q} && git init {ws_q}",
                    f"cd {ws_q} && git remote add origin {shlex_join([repo['url']])}",
                    f"cd {ws_q} && git fetch --depth 1 origin {commit_q}",
                    f"cd {ws_q} && git checkout --detach FETCH_HEAD",
                    # 强制核验实际 HEAD == 固定 commit
                    f"cd {ws_q} && test \"$(git rev-parse HEAD)\" = {commit_q}",
                ],
                "record": {"repo_url": repo["url"], "commit": repo["commit"]},
            },
            {
                "name": "audit_extra_instructions",
                "container_shell": [
                    f"find {ws_q} -type d -name '.claude' -prune -exec rm -rf {{}} +",
                    f"find {ws_q} -type f \\( -name 'CLAUDE.md' -o -name '.claudeignore' \\) -print",
                ],
                "purpose": "remove repo-borne .claude dirs; report any remaining instruction files",
            },
            {
                "name": "prepare_skills_dir",
                "container_shell": [
                    f"rm -rf {CONTAINER_SKILLS_DIR} && mkdir -p {CONTAINER_SKILLS_DIR}",
                ],
            },
            {
                "name": "inject_skill",
                "docker_argv": [
                    ["docker", "cp", str(skills_dir) + "/.",
                     f"{container}:{CONTAINER_SKILLS_DIR}/"],
                ],
                "container_shell": [
                    # 容器内输出逐文件 ``<sha256>  ./<relpath>`` 排序清单；
                    # run.py 与宿主按同一规则生成的期望清单逐行比对。
                    f"cd {CONTAINER_SKILLS_DIR} && find . -type f "
                    f"-exec sha256sum {{}} + | sort -k2",
                ],
                "verify": {"kind": "file_listing_sha256"},
                "record": {
                    "skill_tree_sha256": skill_tree_hash,
                    "skills_dir_host": str(skills_dir),
                    "skills_dir_container": CONTAINER_SKILLS_DIR,
                },
            },
            {
                "name": "fix_ownership",
                "container_shell": [
                    # 以 root 执行；镜像没有 dev 用户时 chown 失败 → setup 失败
                    f"chown -R dev:dev /workspace {CONTAINER_SKILLS_DIR}",
                    f"su -s /bin/sh dev -c "
                    f"'test -w {ws_q} && test -w {CONTAINER_SKILLS_DIR} && test -w /tmp'",
                ],
                "purpose": "repo + skills + /tmp must be writable by the dev user "
                           "the agent runs as; fails setup if the dev identity is absent",
            },
            {
                "name": "no_test_exposure_check",
                "container_shell": [
                    f"test ! -e {CONTAINER_TEST_STAGING} || "
                    f"(echo 'acceptance tests leaked into container' >&2; exit 1)",
                    f"! find {ws_q} \\( -name 'benchmark_tests' -o "
                    f"-name 'test_tdd_workflow.py' \\) | grep .",
                ],
                "purpose": "assert acceptance tests are absent before agent runs",
            },
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--task-id", required=True)
    p.add_argument("--skills-dir", required=True, type=Path,
                   help="要注入的 Skill 树（如 datasets/.../skills/）")
    p.add_argument("--output-dir", required=True, type=Path,
                   help="运行输出根目录；在下面分配 run_NNN")
    p.add_argument("--image-digest", default=None,
                   help="镜像 digest；未知则必须省略，不得凭标签假填")
    p.add_argument("--image-platform", default=None)
    p.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    p.add_argument("--dry-run", action="store_true",
                   help="只登记配置并打印将执行的命令计划，不触碰 Docker/文件系统")
    args = p.parse_args(argv)

    manifest = load_manifest(args.dataset_dir / "manifest.json")
    task = get_task(manifest, args.task_id)
    try:
        skills_dir = check_skills_dir(args.skills_dir)
        skill_tree_hash = tree_sha256(skills_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    env_record = base_environment_record(manifest)
    if args.image_digest:
        env_record["docker_image_digest"] = args.image_digest
    if args.image_platform:
        env_record["docker_image_platform"] = args.image_platform
    # 已提供值必须格式合法；缺失合法（登记未知，run 前再补/拒绝）
    for e in validate_env_record(env_record):
        print(f"error: {e}", file=sys.stderr)
        return 2

    run_dir = next_run_dir(args.output_dir.resolve())
    run_id = uuid.uuid4().hex[:12]
    config = {
        "dataset": manifest["dataset"],
        "task_id": task["task_id"],
        "batch": task["batch"],
        "task_status": task.get("status"),
        "task_file": task["task_file"],
        "test_file": task["test_file"],
        "repo": manifest["repo"],
        "environment": env_record,
        "evaluation": manifest["evaluation"],
        "skills": {
            "host_dir": str(skills_dir),
            "container_dir": CONTAINER_SKILLS_DIR,
            "tree_sha256": skill_tree_hash,
        },
        "run_id": run_id,
        "dry_run": bool(args.dry_run),
    }
    state = {
        "status": STATUS_PENDING,
        "task_id": task["task_id"],
        "run_dir": str(run_dir),
        "setup": None,
        "execution": None,
        "evaluation": None,
    }

    if args.dry_run:
        plan = build_setup_plan(manifest, task, skills_dir, skill_tree_hash,
                                run_dir.name, env_record, run_id)
        config["setup_plan"] = plan
        config["task_runnable"] = task_is_runnable(task)
        config["environment_unresolved"] = [
            k for k in ("docker_image_digest", "docker_image_platform")
            if not env_record.get(k)] or None
        print(json.dumps({"run_dir_would_be": str(run_dir), "config": config},
                         indent=2, ensure_ascii=False))
        return 0

    if not task_is_runnable(task):
        print(f"error: task {task['task_id']} status="
              f"{task.get('status')!r} — 非 ready 任务默认拒绝执行"
              f"（可用 --dry-run 打印计划供审查）", file=sys.stderr)
        return 2

    plan = build_setup_plan(manifest, task, skills_dir, skill_tree_hash,
                            run_dir.name, env_record, run_id)
    config["setup_plan"] = plan
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "config.json", config)
    write_json(run_dir / "run_state.json", state)
    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
