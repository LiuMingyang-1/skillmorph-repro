# P1-B：SWE-Skills-Bench batch1 适配审阅 + 正式三实现判分验证报告

日期：2026-10-28。会话：SWE-2-high（P1-B）。范围：独立审阅 P1-A 的适配修复、冻结 batch1 nodeids、用 `setup.py → run.py → evaluate.py` 正式入口对三种实现各做一次干净 run 判分。工件在 `experiments/exp_002_swe_pilot/{preflight,runs}/`。**全部 synthetic preflight——agent 动作是确定性 `--agent-cmd` 文件写入，不是模型轨迹，不能当 agent 能力证据。**

## 结论

batch1 判分链路可用且有区分度，**可以进入一次真实模型试跑**。三个独立起点的正式 run 结果：

| run | 实现 | evaluation.outcome / reason | total→passed | 证据 |
| --- | --- | --- | --- | --- |
| run_005 | 未改 scaffold | **fail** / test_failures | 14→0 | `runs/run_005/evaluation.json` |
| run_006 | 已知错误（只实现 progressive，忽略 category/tier） | **fail** / test_failures | 14→9 | `runs/run_006/evaluation.json` |
| run_007 | 已知正确（category→progressive→tier 顺序） | **success** / all_passed | 14→14 | `runs/run_007/evaluation.json` |

每次 run 均为独立 `docker create` 起点（不同容器名/run_id），setup.ok、agent_termination.terminated、dev_process_verify.clean、diff.ok、HEAD==a1a2d04 全部核验通过；run_006/007 的 `untracked_files=['src/calculator.py']` 与注入实现一致。非「在已 evaluated 容器上改完重跑」。每 run 有 `PREFLIGHT_NOTE.json` 标注 synthetic。

run_006 的 5 个失败恰是部分实现缺失的维度（2×category + VIP + SVIP + stacking）——区分度是细粒度的，不是粗糙的全过/全挂。

## batch1 nodeids 冻结

`preflight/batch1_frozen_nodeids.json`：14 个 nodeid（`test_tdd_workflow.py::TestTddWorkflow::*`），与 manifest `test_count=14` 一致，`required_tests_check.count_mismatch=false`（三次 run 均一致）。来源与采集命令记录在同文件 `source` 字段。

## 独立审阅：P1-A 修复复核 + 本会话追加修复

复核了 `common.py` / `setup.py` / `run.py` / `evaluate.py` 的 diff，并**在真实容器内逐项实测**（probe 容器已清理）。

### P1-A 修复确认有效

- `docker exec` 显式 `--user root`/`--user dev`（setup/run/evaluate 各侧）——正确，dev-UID 协议依赖它。
- `revoke_dev_sudo`：grep `^\s*dev\s+ALL=.*NOPASSWD` 命中镜像实际的 `dev ALL=(ALL) NOPASSWD:ALL`（/etc/sudoers:58），重写后 `su dev -c 'sudo -n true'` 失败 = 无实际提权。注意 dev 仍在 `%sudo` 组（要求密码、dev 无密码可用）——行为核验覆盖此情形，属可接受的残余（有密码即非免密，且 `sudo -n` 探测的就是免密路径）。`chmod 440` 保持 sudoers 权限位。`sudoers.d/` 只含 README、无 dev 规则，`rm -f` 兜底合理。
- fail-closed 语义：pgrep exit ≥2 → 非零退出；kill/check 均不被 `|| true` 吞错（见下修复 2）。

### 本会话追加的修复（已改代码 + 针对性测试）

1. **`/proc/<pid>/stat` 用 `awk '{print $3}'` 不可靠 — 实测证实。**
   comm 字段 `(<name>)` 可含空格与括号（进程名任意字节、截断到 15）。实测容器内起 `sl eep (x)` 进程：`awk $3` 输出 `eep` 而非 `S`——state 完全错位。若真实 agent 进程名含空格/括号，state 取错值可能把存活进程误判（跳过 KILL 或误判 zombie）。
   **修复**：`_st()` shell 函数取最后一个 `)` 之后的第一个空白字段（`${line##*) }` + `${st%% *}`，POSIX sh，不依赖 awk）。已验证 `sl eep (x)`、`z)evil`、普通进程、PID1 均正确取 S/Z。

2. **kill shell 第二次 `pgrep || true` 掩盖工具错误 — 修复。**
   原第二遍 `pids=$(pgrep ...) || true`：pgrep 工具异常（exit≥2）时被吞、按空列表静默跳过 KILL pass。改为与第一遍一致的 fail-closed（捕获 rc、≥2 即 `exit`）。

3. **容器 init 以 dev 运行（PID 1 = `sleep infinity` 是 dev 进程）— 结构性修复。**
   P1-A 用「枚举时排除 PID 1」绕开。本会话改为 `docker create --user root --init`：
   - `--user root`：init 是 root 进程，dev-UID 枚举根本不出现 init——消除一整类「init 被误算/不可杀」的边界，比过滤更可靠（PID-1 排除保留作兜底）。
   - `--init`（docker-init/tini）：实测会回收 reparent 到 PID 1 的 dev 孤儿进程（`sleep infinity` 不 `wait()`，普通 init 下 dev 僵尸永久滞留）。有 dev 父进程存活的僵尸仍显示 Z 属正确，check shell 的 Z-exclusion 保留。
   - agent 仍经 `docker exec --user dev` 以 dev 运行；UID 终止边界与 chown/dev-可写核验不变。

   相关过时注释（「镜像 User=dev，docker exec 默认继承」）已在 run.py/setup.py 更新——现在 exec 身份始终显式指定、不依赖镜像 User。

4. **复核 sudo 撤销与失败关闭**：`sudo -n true` 行为核验（非文本读 `sudo -l`）正确捕捉 NOPASSWD/缓存凭据；pgrep/pkill `-U` 语义探测、kill 非 ok → terminated=False → `agent_termination_failed` invalid 的链路完整。

### 测试

- `adapter_tests`：**101 passed**（本会话改动后）。
- 根 `tests/`：**52 passed**。
- 新增针对性验证均落在真实容器实测（comm 空格/括号、僵尸、PID1、sudo 撤销、--init 回收），非仅 mock。

## 资源与清理

- 任务容器 run_005/006/007 已 `run.py --cleanup` 清除；probe 容器（p1b-probe*）已删。`docker ps -a` 无 swesk 残留。镜像与 OrbStack 数据不动。
- run_001–004（P1-A）工件保留；run_003 evaluation 是 setup_failure invalid（当时 evaluate 缺 `--user root`）、run_004 是修复后 fail——见 P1-A 报告。

## 对 P1-A 报告的修正

- 「资源状态」一节已过时：P1-A 列的 5 个存活容器已被 P1-A 会话清理，本会话开始时为 0。
- 证据强度：P1-A「注入正确实现 14/14 过」是在已 evaluated 容器内手动注入后跑 pytest，非新 run 正式 evaluate；本会话 run_007 提供了正式的 setup→run→evaluate success 证据。

## 进入真实模型试跑前需明确（父会话决定）

1. **模型/agent CLI**：用什么 `--agent-cmd`（如 `claude -p "$TASK"`）？容器内是否预装该 CLI、是否需登录/API key 注入？
2. **轨迹日志**：JSONL 输出路径与 `--trajectory-jsonl` 提取方式（`--export-only` 需真实 Claude Code JSONL）。
3. **预算**：`--agent-config-json` 注入 model/预算上限；`--agent-timeout-sec`（默认 1800）是否调整。
4. **范围**：只做 batch1。batch9 unsuitable、batch10 pending_pytest_cov 不纳入；多批次前注意 amd64-on-arm64 Rosetta 性能未量化。
5. 镜像未预装 pytest-cov：batch10 若启用需联网 pip 或固化派生镜像（未定，本次不动）。
