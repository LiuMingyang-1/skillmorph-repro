# 设备切换交接 — 2026-10-27

当前分支：`main`，已包含路径、超时及 JSON 输出修复。

## 最新状态（2026-10-27，第五次更新 — 二次加固 A–G）

上轮「8 点全部解决」的说法不实；本轮按明确缺陷清单逐条修复并加行为测试。**仍然全部离线、mock 化验证，没有跑过真实 Docker/容器/模型。**

- **A 轨迹导出入口**：正式 `trajectory.json` 统一为唯一实现 `export_formal_trajectory`（`run.py --export-only` 与 `evaluate.py` 判分后共用），`run.py` 运行期仍只写 `trajectory_draft.json` 诊断草稿。证据门 `verify_export_evidence` 要求：status=evaluated、state.evaluation 与 evaluation.json 两个副本一致（不一致即拒）、execution.json 存在且容器/run/task/HEAD 与登记一致、setup.ok、`agent_termination.terminated=true`、`dev_process_verify.clean=true`、有效判分与 timeout 理由一致——缺任一必需证据保守拒绝；不重评分、不覆盖已有正式轨迹；task 正文经 `check_task_file` 按 manifest 哈希核验后填入。
- **B 严格导入**：`import_trajectory` 默认 strict——坏行/非 dict/缺或重复 tool_use id/未知或重复 tool_result/未配对观察/`..`/`~` 路径逃逸全部 `TrajectoryImportError`，不产出正式轨迹；`allow_partial=True` 仅用于诊断草稿（partial 显式标记、观察留空不伪造）。观察不再 `[:500]` 截断；step 保留 `tool_use_id/name/input/result` 原文；源文件 sha256 记 `trajectory_import.source_sha256`。`files_read` 仅 `Read` 成功且路径解析在注入 skills 根下（Glob/Grep 检索不算已读，任意含 "skills/" 的字符串不算）。
- **C 终止边界换协议**：弃 pid 文件 + 命令正则（reparent/regex 硬伤），改为固定 dev UID——setup 预检 dev 存在/非 root/无 sudo/`command -v pgrep pkill`/`-U` 语义探测（fail closed）；结束由 root 身份 `pkill -TERM→KILL -U dev`（0|1 合法，其它退出冒错，不用 `true` 吞错）+ `pgrep -U dev` 逐值语义（0 存活→0、1 无存活→1、其它非零带 stderr 退出）；START 失败也尝试终止；`_poll_agent_exit` 的 docker 断连/命令错误立即 invalid 不混 task_timeout；合法 timeout（exit 文件缺席+进程全灭）记 `fail(task_timeout)`，无 timeout 无 exit 文件记 `runner_error`；终止/核验失败保守 invalid。新增执行结束时 root 复核 dev UID 无存活进程的 `dev_process_verify` 证据。`_stop_agent` kill 非 ok 一律 terminated=False。
- **D 判分 staging**：staging 目录 root 建后 `chown -R dev:dev` 并 `su dev -c 'test -w'` 验证可写（junit.xml 才写得进）；pytest 以 dev 身份 `-c /dev/null`、`PYTEST_ADDOPTS=`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、清 PYTHONPATH 隔离（batch10 pytest-cov 检查因此会 skip→fail，该任务仍 pending）。`_collect_diff` 全改 dev 身份跑 git（root 对 dev repo 触发 dubious ownership）；弃 `add --intent-to-add`/`reset`（会抹 agent staged 证据）改 `git diff HEAD` + untracked 文件**全量内容**收集；任一命令失败 `diff.ok=false` => invalid。判分 staging 前先 root 复核 dev UID 无存活进程。
- **E JUnit/verdict**：`parse_junit_xml` 逐 case 状态分类并与 suite 四属性逐项核对（重复 case、多状态 case、计数不符、负数/非整数计数、非有限时间全部拒绝）；`_verdict` 只认 exit 0/1（2/3/4/5 与 137 等其它退出 + 任何 XML => `invalid`）；errors => `invalid`（不混环境）；exit0 且 XML 有 skip 明确 `fail`（非矛盾）；pytest 超时/OSError 恒 `invalid`（staging_error 优先于 XML）。
- **F 身份/隔离**：env/plan 按登记为准（`_resolve_env_record`，CLI 只补空缺、冲突拒绝）；digest 必须 `sha256:`+64hex、platform `os/arch[/variant]`（`validate_env_record`，非法值即便登记过也拒绝）；真实执行要 digest+platform 双固定；登记时 digest 未知（plan 浮动 tag）的，run 补齐后用同一 run_id 重建受控 plan，否则拒绝；新 run 目录在任何 mutation 前 `acquire_run_dir` 原子占用（exist_ok=False）+ `run.lock`（O_EXCL，pending run 拒二次启动）并立刻落盘完整 config+running；容器名 `swesk-<task>-<run_NNN>-<run_id12>` 跨输出根唯一；`--cleanup` 只清本 run 容器、保留 artifacts、非 `swesk-*` 名拒绝；`evaluate --container` 与登记不同拒绝；skills 空树/逃逸 symlink 经 `check_skills_dir` 拒绝；判分前 `_verify_execution_evidence` 加严：execution.json 必须存在、terminated/dpv 必须显式 true、diff 完整且 HEAD 与登记一致。
- **G**：判分前 `_verify_execution_evidence` 核验 status=executed + setup.ok + `agent_termination.terminated=true` + `dev_process_verify.clean` + 容器名/HEAD 与登记一致——不再只看 `state.status` 标签。新增 `adapter_tests/test_e2e_flow.py` 9 条 mock-Docker 全流程用例（pending→run→eval→export、export-only 不重跑 pytest、合法 timeout=fail、poll infra=invalid、顽固残余进程=invalid、无效日志+有效判分仍拒导出、cleanup 只清本容器）。

测试：adapter_tests **115 passed**、根 tests **52 passed**。

**仍未做到的（直说）：**
- `pkill -U dev`/`pgrep -U dev` 语义依赖容器内 procps——busybox 镜像下命令行为未验，P1 首次实机必须确认（若缺 procps，kill/check 脚本需换成 `ps`-based 等价物；setup 计划已含 `command -v pgrep pkill`+`-U` 语义探测，fail closed）。pgrep/pkill 退出码语义（0 存活/1 无存活/其它非零冒错、kill 0|1 合法）今天已用纯 shell PATH stub **真实 sh 调用**验证（pgrep/pkill exit 0/1/2/127），不是 FakeExec 预设。
- 判分区分度（已知对/错实现）、dev 身份预检在真实镜像内是否成立、`pytest -c /dev/null` 对原版测试的兼容性——全部未验。
- `test_e2e_flow.py` 的替身在 Python 内模拟 dev 进程集合与文件，未模拟 reparent/僵尸/pipefail 等真实内核语义。
- manifest `test_count` 为静态标注，parametrize 引起的收集数差异未做动态核对——README 已写明**首次正式 run 前必须冻结实际 nodeids 与数量并核对判分结果，未完成不能开始模型试跑**；`config.required_tests`/`evaluation.required_tests_check` 已实现静态 test_* 函数预检与 JUnit 收集名比对记录（有参数化的任务 `verifiable=False`）。判分以实际 JUnit 为准，manifest 值仅供参考。

## 前次状态（2026-10-27，第四次更新 — 适配层修复）

- SWE-Skills-Bench **离线适配代码已交付**，产物在 `datasets/swe_skills_bench/`：`setup.py`/`run.py`/`evaluate.py`/`common.py` + `adapter_tests/`。
  - dry-run 已验证零副作用（无 clone/删除/容器/模型）；`--agent-cmd` 必须显式给出，默认不启动模型。镜像 digest/platform 仍为 `null`，未假填。
  - 判分以 JUnit XML 为准 + exit code 交叉核对；三态 `success`/`fail`/`invalid`；skip、0 测试、collection/单测 error 均不成功；环境/判分器异常→`invalid` 不进统计；任务超时固定记 `fail(task_timeout)`。
  - 测试只在判分阶段注入 `/tmp/benchmark_tests/` 并 `-o addopts=`、清 PYTHONPATH，不进入 agent 工作区、不受项目 pytest 配置污染。
- **P0 评审修正已记录事实**：
  - 评测协议收紧（适配差异已记）：不再说"环境失败算任务失败 / skip 仍算通过"。batch10 `pip install pytest-cov` 联网副作用标 `pending`；离线无法可靠运行前不当普通任务。
  - 8 批次≠8 个独立任务：batch3/4/5/7/8 为近重复 StringCalculator，manifest 已加 `family`/`task_families`；演化/留出必须按 family 切，不随机按 batch，不冻结正式 split、不按测试结果选留出。可用任务面有限（~4 family）。
  - batch9 起点核对（pinned commit `a1a2d04`）：`calculator.py` 存在但 `evaluate()` 是返回 0 的 stub，"扩展现有 evaluate()" 假设只部分成立 → 标 `unsuitable_starting_point`，不宣称 8 个全部自洽。fix 类不再断言"不可修复"，收敛为起点不匹配。
  - 许可：SKILL.md 无单独许可、权利未独立核验，不因 CTA 根 MIT 认定；`file_provenance` 给 18 个文件的上游路径映射；hash 覆盖实际 18 文件。
- **离线验证**：adapter_tests 30 passed；根 tests/ 52 passed（`pyproject.toml` 加 `testpaths=tests`+`norecursedirs=datasets`，默认 pytest 不再收集数据集验收测试，属最小明确改动）。
- **未做**：Docker/真实模型未验（`pending_verification`）；未跑原版验收测试；未建 experiments 目录条目（无真实内容不放伪轨迹）；未触碰 P3 多轮/内部状态。
- `a912de9` 上完成一次真实 API 全流程试跑，约 73 秒，exit 0；两类 API 均成功。
- 试跑前离线测试 52 passed；本次未出现 JSON 解析失败。
- 结果：`experiments/exp_001/runs/run_001/REPORT.md`；日志：`logs/run_20261027_141402.log`。
- 已输出 Skill 修订和 diff，初始 Skill 未改动。聚类过宽、错误判定不稳定仍待检查；未做修改后任务重跑，不代表效果提升。
- 下一步：Docker 就绪后按 `datasets/swe_skills_bench/README.md`「待验证 P1」清单——先 pin digest、克隆固定 commit、用已知对/错实现验证判分区分度，再接 run.py 真跑。同时可离线复查动作表示与聚类边界，不预先认定阈值是唯一根因。

### 明日接手步骤（Docker 就绪后）

1. `docker pull zhangyiiiiii/swe-skills-bench-python`，把 digest/platform 回填 `manifest.json`（登记时会自动带入；CLI `--image-digest/--image-platform` 只能补登记缺失值，冲突拒绝）。确认镜像内 procps（`pkill`/`pgrep`）可用且 dev 身份成立。
2. `python setup.py --task-id tdd-workflow-batch1 --skills-dir $PWD/skills --output-dir <runs>`（去掉 --dry-run）建 run_NNN（status=pending）。
3. `python run.py --run-dir <runs>/run_001 --agent-cmd '<显式命令>'`。先无模型做基线判分。
4. `python evaluate.py --run-dir <runs>/run_001` 判分；先用已知对/错实现验证区分度再上模型。
5. 判分后导出正式轨迹：`python run.py --run-dir <runs>/run_001 --export-only --trajectory-jsonl <file>`（或判分同命令里 `evaluate.py --trajectory-jsonl`）；`python run.py --run-dir <runs>/run_001 --cleanup` 只清本 run 容器。

以下保留 2026-10-26 的排查与验证记录，其中“尚未复验”均指当时状态。

## 已完成

- 聊天和 embedding 客户端超时统一为 120 秒；SDK 内置一次重试
  （覆盖超时及其他可重试错误），无应用层重试或兜底。
- 定位提示词明确 skill/artifact 分开，artifact 不重复 Skill 名前缀。
- 协议相对路径统一 POSIX `/`，本地文件操作使用 pathlib。
- 原 macOS 离线测试 39 项通过；本次已在 Windows 执行完整测试，结果见下节。

## 真实试跑

一次真实试跑约 68.92 秒后退出；完成抽象、聚类、覆盖统计、排名，越过原先路径重复错误，进入 propose 后报错：

```text
JSONDecodeError: Invalid \escape: line 1 column 1049 (char 1048)
```

原始模型回复没有保存，具体非法转义未知。现已加强输出约束并补充诊断留存，
尚未重新验证真实模型输出。
未产生完成的提案、评估、Skill 修订或 diff。部分产物及脱敏日志按原样归档在
`experiments/exp_001/archive/round_001/`（历史快照，不再参与运行）。
本次运行的提示词快照早于后续跨平台与 JSON 转义补充，按原样保留。

## JSON 输出约束与诊断

- `llm.chat_json` 严格解析完整回复；拒绝围栏、额外文本与多个 JSON 对象，
  不静默修补非法转义、不重试。保留原始错误原因、行列和字符位置。
- 仍失败时把原始回复保存到本次运行目录 `runs/run_NNN/raw/response-*.txt`
  （`llm.set_raw_dir`；未设置时用 `$SKILLEMORPH_RAW_DIR` 或
  系统临时目录下的 `skillmorph-bad-json/`），UTF-8 原样保存、不转换换行符，
  并抛出附带文件路径的 JSONDecodeError。raw 目录只对本次运行生效，
  运行结束或异常退出后恢复调用前的值。
- 所有 JSON 生成提示词追加严格转义要求（`\\`、`\"`，禁止裸 `\s`/`\p` 等）。
- 流水线在 stderr 输出阶段进度（abstract/localize/propose），便于定位
  失败阶段；stdout 仍为最终摘要 JSON。
- Windows 完整离线验证：52 passed。补丁 diff 的 LF 修复已通过检查，
  无末尾换行文件的 Git apply 用例也全部通过。
  已验证非法 propose 回复只调用一次、UTF-8 原文留存在本轮 raw/、错误位置保留。
  未再次调用真实 API，尚不能确认供应商会遵循加强后的转义要求。

动作聚类也可能过宽，把建表、开新连接、查询等合为一组，应人工审查 action_map 和 abstracted_runs。实验仅为 2 任务、4 条合成轨迹，不代表效果提升。

## 换设备继续

1. 获取并切换 `main`，`uv sync` 安装锁定依赖。
2. `.env` 不随 Git 同步，需在新设备安全配置两类 API，参考 `.env.example`；不要提交凭据。
3. `uv run python -m pytest -q`；本次 Windows 已完整通过 52 项，包含补丁 LF 与无末尾换行应用验证。
4. 若真实输出再次出现非法 JSON，检查 `runs/run_NNN/raw/` 中的失败原文；不要静默修补或自动重试。
5. 每次运行自动写入新的 `runs/run_NNN/`（下一个可用编号），不覆盖已有运行；
   历史试跑已归档到 `archive/round_001/`。后续付费运行需用户明确指示。

任务执行和判分、修改后重跑对比、多轮历史及计数加权仍未实现。
