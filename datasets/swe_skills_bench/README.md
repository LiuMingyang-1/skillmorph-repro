# SWE-Skills-Bench 数据包（试点：tdd-workflow）

来源、固定版本、适配差异与待验证项的完整清单见 `manifest.json`。本文件说明包的构成、选题理由与使用约束。

## 来源与固定版本

- **CTA 仓库**：`explicitcontextualunderstanding/cta` @ `8822baed308a74b5921e2a5be50394c1a4a8fc96`，MIT 许可（见 `LICENSE`）。CTA 是另一项研究（Counterfactual Trace Auditing）的复现框架，不是官方基准发布版。
- **HF 数据集**：`GeniusHTX/SWE-Skills-Bench` @ revision `a111a9d9e53722c7aafd951830b459b08439f2da`，MIT。49 条记录的 task_prompt / test_code / skill_document 与 CTA `batch1` 文件逐一比对完全一致（空白归一化后）。本包中 batch1 的任务与测试即 HF 原样。
- **目标项目**：`tdd-starters/python` @ `a1a2d04ae69bd50aba9dac2783737dfda8f048c9`（HF 中该字段为空，commit 取自 CTA 配置）。容器内路径 `/workspace/python`。
- **镜像**：`zhangyiiiiii/swe-skills-bench-python`。digest/平台**未知**，首次拉取时必须固定并回填 manifest——不得凭标签名假设。

## 目录内容

```text
tasks/tdd-workflow-batch{1,3,4,5,7,8,9,10}.md   # 8 个任务描述（喂给执行 agent）
tests/batch{1,3,4,5,7,8,9,10}/test_tdd_workflow.py  # 对应验收测试（原版未改）
skills/tdd-workflow/SKILL.md                     # 初始 Skill 包（繁体中文，409 行）
manifest.json                                    # 哈希、repo、镜像、评测协议、排除项、family 分组
LICENSE                                          # CTA MIT
setup.py / run.py / evaluate.py                  # 本数据集的环境/执行/判分适配
common.py                                        # 共享：哈希、manifest、JUnit、执行器、状态约定
adapter_tests/                                   # 离线适配测试（mock/临时目录；不跑原版验收、不用 Docker）
```

运行任务包不需要 CTA 检出：以上文件 + 固定 commit 的上游 repo + 镜像即闭包。所选批次测试均无 `_dependency_utils` 等本地辅助模块依赖（已逐文件核查 import）。

## 选题理由

候选为 `fix` 与 `tdd-workflow`，两者在 CTA 配置中均无 `pre_process`/`setup_commands`，评测都只有 L2 unit_test。

选择 `tdd-workflow` 的理由：

1. **任务—repo 基本自洽**：目标 repo 是最小 Python scaffold（`src/python_starter/` + `tests/`）。对照之下 `fix` 的多批次断言上游 repo（`michaelasper/upgradle` @ `5f292188`）中不存在的文件，属任务/repo 起点不匹配，不能直接算可用任务。注意**自洽不等于判分区分度已验证**——后者仍待 P1 用已知对/错实现核实。
2. **依赖闭包轻**：仅 Python + pytest；`fix` 依赖 node_modules/ESLint 工具链。
3. **同 skill 有多个任务**：见下「任务族 / 近重复」——**8 个批次不是 8 个互相独立的任务**。

## 任务族 / 近重复（防止泄漏）

manifest 给每个任务加了 `family`/`group`：

- `family: "string_calculator"`（batch3/4/5/7/8）——几乎相同的 StringCalculator 任务，近重复；
- `family: "evaluate_expr"`（batch9）——扩展现有 `evaluate()`；
- `family: "password_validator"`（batch10）；
- `family: "coupon_calculator"`（batch1）。

演化/留出划分**必须按 family 分组切**，绝不能随机按 batch 拆——那会让近重复任务同时进入训练与留出，造成泄漏。不同 family 的任务数量其实很少（~4 个），可用任务面有限；当前不冻结正式 split，也不按测试结果挑留出。

## batch9 起点核对（P0 修正）

任务描述假定 repo 已有可工作的 `evaluate()` 算术求值器和 `tests/test_calculator.py`。已对固定 commit `a1a2d04` 只读核验：`src/python_starter/calculator.py` **存在但只是 stub**（`evaluate` 直接返回 0，并未实现基本算术），`tests/test_calculator.py` 存在（1 个活跃测试 + 注释掉的用例），`Makefile`/`pyproject.toml` 存在。即「文件都存在」成立，但「已有可工作的 evaluate() 供扩展」**不成立**。结论：batch9 起点假设部分不满足，标记为**不适合作为干净演化样本**——保留在包内供参考，不列入默认可用任务。缺失文件本身非绝对不可修复；README 不再断言 fix 类任务「不可修复」，只记录起点不匹配、需另行验证。

## 排除项（原样记录，未改测试）

- **batch2**：测试以通用 AST/关键词启发式为主（类名含 "calc"、源码含 "category"），功能检查遇签名不符即 skip（11 处 `pytest.skip`），判分区分度不足。
- **batch6**：任务假定 TypeScript/Express/PostgreSQL 项目，与 Python scaffold repo 不匹配；测试断言的 `.ts`/`.sql` 文件在该 repo 语境下不成立。

## 评测协议（本包适配版，与 CTA 有意的差异）

- 命令：`python -m pytest <staged_test> -v --tb=short --junitxml=...`，`min_pass_rate = 1.0`，超时 300s。
- **判分以 JUnit XML 为准**（计数、失败名单、耗时），进程 exit code 作交叉核对；不解析终端 "passed" 字符串。exit≠0 而 XML 全过视为产物矛盾 → `invalid`。
- **成功 = 收集到的全部测试通过**。`skip`、collection error、单测 error、0 个测试均**不算成功**。
  - 与 CTA `unit_test_runner` 的差异（适配差异，已记录）：CTA 只看 summary 行 pass_rate，会把 skip 计入 total 仍可能判过；本协议收紧——**skip 不成功、环境异常 invalid**。
- **outcome 三态**：`success` / `fail` / `invalid`。初始化失败、agent 进程异常、判分器异常 → `invalid`，**不进入成功/失败覆盖统计**。任务超时按固定协议记 `fail`（`task_timeout`），与基础设施超时区分。
- **测试隔离**：验收测试只在判分阶段才注入容器 `/tmp/benchmark_tests/`（CTA eval.py 行为），从该目录运行且 `-o addopts=`、清 `PYTHONPATH`——**不进入 agent 工作区**，也不受项目 pytest 配置污染。
- **batch10 联网副作用**：其 `test_coverage_meets_threshold` 在运行时 `pip install pytest-cov`。这需要网络或镜像预装 pytest-cov；无法离线可靠运行，**该任务标 `pending`**（非 ready），不要在未确认 pytest-cov 可用前把它当普通任务跑。

## 适配差异

- HF 无 repo_commit，采用 CTA 固定 commit；两者 batch1 内容已全量对齐。
- 本包按批次组织任务/测试目录；task_id 采用 `tdd-workflow-batchN`。
- 未引入 CTA 的 orchestrator/evaluator 代码；`setup.py`/`run.py`/`evaluate.py`/`common.py` 为本包的离线可验适配实现（见下）。
- 判分协议收紧见上；哈希覆盖 `manifest.file_hashes` 中全部 18 个文件。

## 执行适配（setup.py / run.py / evaluate.py）

均为普通脚本，显式参数，**dry-run 保证零副作用**（无 clone/删除/容器/模型/写文件）。Docker 命令用 stdlib `subprocess` 以 argv `list[str]` 显式组装；`--agent-cmd` 必须显式给出，默认不启动任何模型。用法见各脚本 docstring 与 `--help`。

```bash
# 登记一个运行（生成 setup 计划 + run_NNN/config.json + run_state.json）
python setup.py --task-id tdd-workflow-batch1 \
    --skills-dir $PWD/skills --output-dir /path/to/runs --dry-run

# 执行（dry-run 只打印将执行的 docker/容器命令，无任何副作用）
python run.py --task-id tdd-workflow-batch1 --skills-dir $PWD/skills \
    --output-dir /path/to/runs --agent-cmd 'claude -p "$TASK"' --dry-run

# 判分（核验执行证据后把测试注入 /tmp/benchmark_tests，JUnit 判分）
python evaluate.py --run-dir /path/to/runs/run_001

# 判分后导出正式方法层轨迹（不重跑 pytest；仅有效判分；不可覆盖）
python run.py --run-dir /path/to/runs/run_001 --export-only \
    --trajectory-jsonl /path/to/agent.jsonl

# 只清本 run 的容器（保留 artifacts）
python run.py --run-dir /path/to/runs/run_001 --cleanup
```

协议要点（离线已实现并测试；Docker 运行时仍未验证，见「待验证 P1」）：

- **真实执行要求镜像固定**：digest 与 platform 均必填（`image@sha256:` + 显式 `--platform` + `--entrypoint sleep infinity`）；--run-dir 复用 setup 登记的环境/plan，命令行只能补登记缺失字段，冲突拒绝；已提供 digest/platform 必须匹配 `sha256:`+64hex / `os/arch[/variant]` 格式（非法值即便登记过也拒绝）；登记时 digest 未知（plan 浮动 tag）的，run 补齐后用同一 run_id 重建受控 plan，否则拒绝；dry-run 允许 unknown。
- **容器按 run 隔离**：`swesk-<task_id>-<run_NNN>-<run_id>`（run_id=uuid 前 12 位，跨输出根不重名）；开始前 `docker rm -f` 清同名残留；clone 目标非空即拒绝；`rev-parse HEAD` 与固定 commit 逐一核验。
- **Skill 注入核验**：清空 `/home/dev/.claude/skills` 后 `docker cp` 注入，再在容器内重算逐文件 sha256 清单与宿主记录比对，不一致即 setup 失败；空树/逃逸 symlink 的 skills 根直接拒绝。
- **固定执行身份**：setup 预检 dev 存在、非 root、无实际提权能力——整个执行/终止协议依赖该 UID；`chown -R dev:dev /workspace <skills>` 并以 dev 身份验证可写。CTA 镜像 `/etc/sudoers` 给 dev 配 `NOPASSWD:ALL`，setup 的 `revoke_dev_sudo` 步在容器内删该授权（不动镜像），随后以 `su dev -c 'sudo -n true'` 行为核验无提权。注意 `docker exec` 默认继承镜像 `User=dev`，所有 root 侧命令必须显式 `--user root`（P1-A 实机发现并修复）。
- **TASK 传递**：`docker exec --env TASK=<texto>` —— 容器内 sh 展开 `$TASK`，不做宿主侧前缀赋值。
- **终止边界（UID 范围）**：agent 以 dev 身份后台运行，stdout/stderr/退出码落容器文件；结束/到时后由 root 身份对 dev UID 下**存活非 init** 进程 TERM→KILL 并核验无残余——枚举时排除容器 init（PID 1，镜像 `User=dev` 下 `sleep infinity` 常驻不可杀）与僵尸（Z state，init 不回收会滞留）。不依赖命令行正则、pid 文件或 reparent 进程树。终止失败/有残余 => `invalid` 拒评；判分前再做一次 root 侧 UID 存活性核验。合法 timeout 下 exit 文件缺席是协议允许（记 `fail(task_timeout)`）；无 timeout 且 exit 文件缺席 => `runner_error` invalid。docker 断连/命令错误立即 `invalid`，绝不误记 task_timeout。
- **状态门**：`run.py` 只接受 `status=pending` 的 `--run-dir`（task/skills-hash/repo-commit 不一致即拒绝）；pending run 由 `run.lock`（O_EXCL 小文件）原子占锁、已存在即拒；新 run 目录在任何 mutation 前 `acquire_run_dir` 原子占用（exist_ok=False）并立刻落盘完整 config+running；`evaluate.py` 只判 `status=executed` 且要核验 execution.json 的终止证据（terminated/clean/容器名/HEAD 一致）、setup.ok、dev 进程已灭——不能只看 status 标签；`--container` 与登记不同一律拒绝。
- **任务白名单**：manifest `status != "ready"`（batch9 `unsuitable_starting_point`、batch10 `pending_pytest_cov`）默认拒绝真实执行；dry-run 仍可打印计划。
- **判分严格规则**：JUnit 解析核对 suite 属性与实际 case 逐状态分类（重复 case/多状态 case/计数不符/非法时间全部 invalid）；只 0/1 是合法 pytest 结论（exit 2/3/4/5、137 等其它退出 + 任何 XML => `invalid`）；errors 保守 `invalid`（不混环境）；skip => `fail`（非产物矛盾）；exit/XML 矛盾、0 测试 => `invalid`；全部通过 + exit 0 => `success`。stdout/stderr/JUnit XML 原文全量保存。staging 目录 root 建后 `chown dev` 并 dev 验证可写；pytest 以 `-c /dev/null`、`PYTEST_ADDOPTS=`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、清 PYTHONPATH 隔离运行（dev 身份）。
- **diff 取证**：判分以 dev 身份 `git diff HEAD` + untracked 文件全量内容收集，不碰 index（不再用 `add --intent-to-add`/`reset`）；任一 git 命令失败则 artifact 标不完整 => invalid。
- **agent 配置**：`--agent-config-json` 可注入显式配置（model/温度/预算）；`config.agent` 中 model/temperature/usage/cost 未知记 `null`，不伪零。

轨迹不编造 steps：真实 Claude Code thinking JSONL 经严格校验的 `import_trajectory` 转换——坏行/非 dict/缺 id/重复 id/未知或重复 result/未配对观察/路径逃逸一律拒绝；观察完整保留（不截断）；按 `tool_use_id` 精确配对；仅 `Read` 成功结果且路径解析在注入 skills 根下才记 `files_read`/`skills_used`（Glob/Grep 检索不算已读文件）。正式 `trajectory.json` 只有一个导出实现（`export_formal_trajectory`，`run.py --export-only` 与 `evaluate.py` 判分后共用）：证据门要求 status=evaluated、state.evaluation 与 evaluation.json 两个副本一致、execution.json 存在且容器/run/task/HEAD 与登记一致、setup.ok、`agent_termination.terminated=true`、`dev_process_verify.clean=true`、有效判分与 timeout 理由一致——缺任一必需证据保守拒绝；不重评分、不覆盖已有正式轨迹；无效日志/无效判分只写 `trajectory_draft.json` 诊断草稿。

## 许可状态

- CTA 根 `LICENSE` 为 MIT，已随包保留（`LICENSE`）。
- `skills/tdd-workflow/SKILL.md` 无单独许可文件；其上游权利**未独立核验**，不因 CTA 根 MIT 而认定。manifest `skill_package.license_note` 与 `file_provenance` 记录每个文件的来源路径，供重查。

## 待验证（P1，需 Docker）

**P1-A（2026-10-28，OrbStack + amd64 镜像经 Rosetta）已实测完成项——见 `docs/SWE_SKILLS_P1_ENV_REPORT.md`：**

1. ~~拉取镜像并记录 digest 与平台~~ ✅ digest `sha256:51d4…b974`、platform `linux/amd64` 已回填 manifest。
2. ~~dev 身份预检~~ ✅ dev=uid 1001 非 root；发现镜像 `NOPASSWD:ALL` → setup 增加 `revoke_dev_sudo` + `sudo -n true` 行为核验；`docker exec` 须显式 `--user root`（镜像 `User=dev` 会被继承）；UID 终止边界排除 init(PID1)/僵尸。
3. ~~容器内 clone + 固定 commit 核验~~ ✅ fetch+checkout+`rev-parse HEAD` 全过。
4. ~~判分区分度~~ ✅ 未改 scaffold→`fail`（14 全 fail）；注入已知正确实现→14/14 PASS（正确参考实现存 `experiments/exp_002_swe_pilot/preflight/fixtures/batch1_calculator_correct.py`）。
5. `pytest -c /dev/null` 隔离 ✅ 正常；**pytest-cov 镜像未预装**，容器内 pip 有网可装——batch10 仍 `pending`。
6. ~~连续两次初始化起点一致~~ ✅ run_003/run_004。

**P1-B（下一会话）待办：**

7. **首次正式 run 前必须冻结实际收集到的 pytest nodeids 与数量并核对判分结果**——batch1 已核对（14=14）；其余批次未核。parametrize 任务 manifest count 不可信，未完成冻结核对前不能开始模型试跑。
8. batch9 是否排除/修复后纳入，待决定。
9. batch10 pytest-cov：决定容器内联网安装 vs 固化派生镜像。
