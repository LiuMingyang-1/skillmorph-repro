# exp_001 真实 API 试跑报告 — run_001

日期：2026-10-27（本地）；commit：a912de9（main）。
命令：`.venv/bin/python -u -m skillmorph experiments/exp_001`（仓库根目录，使用现有 `.venv` 与根 `.env`）。

## 结论

**完整跑通**，exit 0，无异常、无 JSON 解析失败（`raw/` 为空）。此前 propose 阶段的
`Invalid \escape` 未复现；本轮所有模型回复均通过严格 JSON 解析；日志未记录逐请求次数，无法判断是否发生 SDK 传输重试。
耗时约 73 秒（14:14:02 → 14:15:15 本地时间），到达并完成全部阶段：
abstract(4) → cluster(14 transitions) → mark_errors → coverage/rank →
localize(×2) → propose(×2) → evaluate_and_patch → skills_after + skills.diff。

## 配置与健康（不打印密钥）

- `.env` 六变量齐全：LLM_BASE_URL/LLM_API_KEY/LLM_MODEL、EMBEDDING_BASE_URL/EMBEDDING_API_KEY/EMBEDDING_MODEL。
- 本轮 chat 与 embedding 两类调用均成功返回，**未观察到认证或连接问题**（仅此一次证据）。
- 费用/usage：流水线未记录 token 用量，**未知**。

## 离线测试

`.venv/bin/python -m pytest -q`：**52 passed**（约 1.06s）。

## 流水线输出审查

### 聚类（action_map.json）——仍然过宽

14 条 transition 只聚成 2 个动作：

- `act_001`：所有"读 skill/读 reference"动作（4 次出现）。
- `act_002`：**建表+插入、新开 connB、connA/connB 查询全部合并**（10 次出现），
  与归档 round_001 同样的过宽问题：语义不同的"新开 :memory: 连接"（真正致错动作）
  与"在同一连接上查询"（正确动作）被并为一组。embedding 余弦距离阈值
  CLUSTER_DISTANCE=0.5 下出现该结果；尚未隔离动作表示、embedding 与阈值各自的影响。

### 错误判定（abstracted_runs.json）

- task_002/run_2（success）第 2 步"open connB + SELECT"被判 `introduces_error=false`，
  理由"错误只是暴露了环境中已有的隔离数据库"。按提示词字面值可辩护（错误由更早的
  connB 打开动作引入/由 skill 引入），但此步确实产生了 OperationalError；
  上一轮（归档）曾判为 true。**判定存在不稳定性**，值得注意。
- 其余判定合理。

### 排名（ranking.json）

act_001 与 act_002 得分相同（0.707，n_fail=2/n_succ=2），并列入选。
"读 skill"（act_001）在失败与成功运行中均出现，覆盖无区分度；当前公式仍给予
非零得分并将其入选。不能将这一现象直接归因于过宽聚类。

### 定位与提案（edit_sites.json / proposals.json）

两条 edit_site 均定位到 `reference/connections.md` 第 3–13 行（"每步开新连接"
规则）及 SKILL.md 相关行，定位准确、理由正确（:memory: 每连接独立、关闭即销毁）。
两份提案方向一致：改单连接复用规则 + 更新 SKILL.md 指引。

### 评估与补丁（evaluation.json / skills.diff / skills_after）

- selected = [act_001, act_002]，rejected = []，两提案被合并为一份补丁。
- `skills.diff` 非空，已应用到 `skills_after/`（输入 `skills/` 未改动，已校验
  skills_before 与 skills/ 内容一致）。
- 修订质量：connections.md 被完全改写为"单连接 + 关闭即销毁"规则，**正确针对
  :memory: 每连接独立的缺陷**；SKILL.md 同步更新。
- 小瑕疵：SKILL.md 新增两条"reuse a single connection" bullets 语义重复
  （两条提案各自贡献一条），无矛盾、无无关修改，但有冗余。
- 补丁行尾规范：diff 为 LF、上下文 hunk 完整，符合 Git apply 预期。

## 产物与日志

- 运行目录：`experiments/exp_001/runs/run_001/`
  - `analysis/`：abstracted_runs / action_map / coverage / ranking / summary
  - `revision/`：edit_sites / proposals / evaluation / skills.diff
  - `skills_after/`、`skills_before/`、`trajectories/`、`prompts/`、`raw/`（空）
- 脱敏运行日志：`logs/run_20261027_141402.log`（阶段进度 + 摘要 JSON + exit 码）。
- 汇总 JSON 同时打印在 stdout 并写入 `analysis/summary.json`。

## 未解决问题 / 注意事项

1. **聚类过宽**（已知问题，未修复）：建表/开新连接/查询合一，当前"读 skill"
   与全部 db 动作并列可疑。后续需检查动作表示、embedding 距离及阈值，不能预先认定缩小阈值即可解决。
2. **错误判定不稳定**：同一 connB 查询步在不同运行中结论不同（本次 false，
   归档 true）。对"引入 vs 暴露"的边界判定在两次运行间不一致。
3. 无任务重跑/多轮演化/真实执行验证——修订效果未经任务成功率验证（本版范围外）。
4. 费用与 token 用量不可知；如需记账需在 llm 封装层记录 usage。
5. 本次仅为 2 任务 4 条合成轨迹，不代表修订在真实任务上的效果提升。

## 工作区状态

未提交、未推送；`README_zh.md`（用户未跟踪文件）与初始 `skills/` 原样保留；
新增未跟踪内容仅 `experiments/exp_001/runs/` 与 `logs/`。
