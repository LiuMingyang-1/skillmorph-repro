# P1-A：SWE-Skills-Bench batch1 Docker 环境实测报告

日期：2026-10-28。范围：OrbStack Docker 环境核验 + batch1 干净环境预检（不调模型、不跑付费 agent）。详细命令日志与运行工件在 `experiments/exp_002_swe_pilot/{preflight,runs}/`。

## 环境核验（宿主）

| 项 | 实测值 |
| --- | --- |
| Docker CLI | `/usr/local/bin/docker` + `/Users/lmy/.orbstack/bin/docker`，client/server 28.5.2 |
| context | `orbstack`（当前），`unix:///Users/lmy/.orbstack/run/docker.sock` |
| daemon 平台 | linux/arm64（宿主 Apple Silicon；amd64 镜像经 Rosetta 运行，`orbctl config` rosetta=true） |
| OrbStack 数据 | 已位于外置盘 `/Volumes/LMY/docker`（data.img.raw，22G 已用）；盘余量 66Gi |
| 宿主磁盘 | `/` 余量 31Gi |
| 网络 | hub.docker.com HTTP 200；容器内 `pip install` 实测可达 PyPI |

## 镜像固定（manifest 已回填）

- `zhangyiiiiii/swe-skills-bench-python:latest`
- **RepoDigest**：`sha256:51d40310cdf44d00b3e383af1c4467bc460e6a3a25fedb1f9fab6a8d7b77b974`
- **平台**：`linux/amd64`（manifest list 未对 host 暴露 arm64 变体；拉取即 amd64，经 Rosetta 运行正常）
- 内容：Ubuntu 24.04、Python 3.12.3、pytest 9.0.2、git 2.43.0、procps-ng 4.0.4（pgrep/pkill 支持 -U）、sha256sum/su/sudo 齐备
- **pytest-cov 未预装**（batch10 仍 `pending_pytest_cov`；容器内有网，运行时 `pip install` 可行但不保证离线）

## 实测发现并修复的适配问题（改动清单）

全部在适配层修复并复核（adapter_tests 101 passed），未改任务/测试/Skill：

1. **`docker exec` 继承镜像 `User=dev`**——所有 root 侧命令（chown/su/UID-kill/staging）必须显式 `--user root`，否则 chown "Operation not permitted"、su 要密码。已修 `run.py`（setup steps、kill/check/verify）与 `evaluate.py`（stage/pres）。
2. **镜像给 dev 配 `NOPASSWD:ALL`（/etc/sudoers:58）**——agent 可免密 sudo 拿 root，破坏 dev-UID 终止边界。setup plan 新增 `revoke_dev_sudo` 步（root 侧删除 NOPASSWD 行，容器内一次性修复、不动镜像）；`precheck_dev_identity` 的 sudo 检查从读 `sudo -l` 文本改为**行为核验** `su dev -c 'sudo -n true'`（旧检查在 dev-exec 语境下本身失真）。
3. **UID 终止边界把容器 init 算进去了**——镜像 `User=dev` 使 PID 1（`sleep infinity`）也是 dev 进程且不可杀；被杀进程因 init 不回收而以僵尸滞留。`dev_uid_kill_shell`/`dev_uid_check_shell` 改为枚举 dev 进程时排除 PID 1 与 Z state；pgrep 退出码 >=2 仍 fail closed。

## batch1 干净环境预检结果

- **固定起点**：容器内 `git init + fetch --depth 1 origin a1a2d04 + checkout --detach FETCH_HEAD` 成功；`rev-parse HEAD` 与固定 commit 逐一核验通过（execution.diff.head_after 一致）。
- **dev 身份**：uid=1001 非 root；NOPASSWD 撤销后 `su dev -c 'sudo -n true'` 失败 = 无实际提权；`/workspace`、`/home/dev/.claude/skills`、`/tmp` dev 可写（chown + 行为核验通过）。
- **Skill 注入**：`docker cp` 后容器内逐文件 sha256 清单与宿主逐行一致。
- **UID 协议**：kill/check shell 在真实容器内 TERM→KILL 后 check 返回 1（clean），dev 无存活非 init 进程。
- **判分区分度（双侧验证）**：
  - 未改 scaffold → `fail`（14/14 collected 全 fail，`required_tests_check` count_mismatch=false，manifest test_count=14 与实际收集一致）；
  - 注入已知正确 `src/calculator.py`（category→progressive→tier 顺序）→ 14/14 PASSED。
- **pytest 隔离**：`-c /dev/null -p no:cacheprovider`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、清 PYTHONPATH 下收集/执行正常。
- **两次连续初始化**（run_003/run_004）起点一致、容器互不干扰。

## 真实运行记录（experiments/exp_002_swe_pilot/runs/）

| run | 结果 | 说明 |
| --- | --- | --- |
| run_001 | invalid(setup_failure) | 暴露 User=dev 继承问题（chown 被拒、su 要密码）→ 促成本次修复 1 |
| run_002 | invalid(agent_termination_failed) | 暴露 init 计入 UID 检查 → 促成修复 3 |
| run_003 | executed → evaluated | 判分链路打通；evaluate 的 stage_shell 漏加 --user root → 修复 1 的补充（evaluate 端） |
| run_004 | executed → **evaluated fail**(test_failures) | 未改 scaffold 正确判 fail；容器内再注入正确实现 → 14/14 通过 |

## 资源状态与清理

- 存活容器：`swesk-tdd-workflow-batch1-run_00{1,2,3,4}-*`（5 个，含 run_001 两个名字）。
- 清理：逐 run `python run.py --run-dir <dir> --cleanup`（只 rm 本 run 容器、保留 artifacts）；或 `docker rm -f swesk-tdd-workflow-batch1-run_*`。镜像与 OrbStack 数据不动。
- batch10 需 pytest-cov：镜像未预装；容器内 pip 有网可装。若要离线可靠，建议固化含 pytest-cov 的派生镜像（P1-B 前决定）。

## 遗留 / 给 P1-B 的输入

- nodeids/数量冻结：batch1 实际收集 14 = manifest 14；P1-B 需对全部拟用批次重复此核对（parametrize 任务 manifest 数不可信）。
- 未修改/已知错误/已知正确三类实现判分：batch1 已证未修改→fail、正确→success；P1-B 补「部分正确/明显错误」实现确认失败细分。
- 确切入口：`setup.py → run.py --run-dir（--agent-cmd 必填）→ evaluate.py --run-dir`；环境即 manifest.environment 的 digest+platform。
- amd64-on-arm64 经 Rosetta：功能正常；性能/行为差异未量化，多任务并发前留意。
- NOPASSWD 撤销是 per-run 容器内修复；若重建镜像可把该修复 bake 进 Dockerfile。
