# 设备切换交接 — 2026-10-27

当前分支：`main`，已包含路径、超时及 JSON 输出修复。

## 最新状态（2026-10-27）

- `a912de9` 上完成一次真实 API 全流程试跑，约 73 秒，exit 0；两类 API 均成功。
- 试跑前离线测试 52 passed；本次未出现 JSON 解析失败。
- 结果：`experiments/exp_001/runs/run_001/REPORT.md`；日志：`logs/run_20261027_141402.log`。
- 已输出 Skill 修订和 diff，初始 Skill 未改动。聚类过宽、错误判定不稳定仍待检查；未做修改后任务重跑，不代表效果提升。
- 下一步建议先离线检查动作表示与聚类边界，不预先认定阈值是唯一根因。

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
