# 设备切换交接 — 2026-10-26

分支：`fix/portable-paths-api-timeouts`。当前未完整跑通实验。

## 已完成

- 聊天和 embedding 客户端超时统一为 30 秒，仍不重试。
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
未产生完成的提案、评估、Skill 修订或 diff。部分产物及脱敏日志保存在
`experiments/exp_001/rounds/round_001/`。本次运行的提示词快照早于后续
跨平台与 JSON 转义补充，按原样保留。

## JSON 输出约束与诊断

- `llm.chat_json` 严格解析完整回复；拒绝围栏、额外文本与多个 JSON 对象，
  不静默修补非法转义、不重试。保留原始错误原因、行列和字符位置。
- 仍失败时把原始回复保存到 `rounds/round_001/raw/response-*.txt`
  （`llm.set_raw_dir`；未设置时用 `$SKILLEMORPH_RAW_DIR` 或
  系统临时目录下的 `skillmorph-bad-json/`），UTF-8 原样保存、不转换换行符，
  并抛出附带文件路径的 JSONDecodeError。
- 所有 JSON 生成提示词追加严格转义要求（`\\`、`\"`，禁止裸 `\s`/`\p` 等）。
- 流水线在 stderr 输出阶段进度（abstract/localize/propose），便于定位
  失败阶段；stdout 仍为最终摘要 JSON。
- Windows 完整离线验证：43 passed、4 failed；失败均为修复前已有的
  `test_diff_without_trailing_newline_git_applies` 参数用例。
  已验证非法 propose 回复只调用一次、UTF-8 原文留存在本轮 raw/、错误位置保留。
  未再次调用真实 API，尚不能确认供应商会遵循加强后的转义要求。

动作聚类也可能过宽，把建表、开新连接、查询等合为一组，应人工审查 action_map 和 abstracted_runs。实验仅为 2 任务、4 条合成轨迹，不代表效果提升。

## 换设备继续

1. 获取并切换此分支，`uv sync` 安装锁定依赖。
2. `.env` 不随 Git 同步，需在新设备安全配置两类 API，参考 `.env.example`；不要提交凭据。
3. `uv run python -m pytest -q`；Windows 有 4 项既有无末尾换行补丁应用测试失败，待单独修复。
4. 若真实输出再次出现非法 JSON，检查 `raw/` 中的失败原文；不要静默修补或自动重试。
5. `round_001` 已存在，CLI 会拒绝覆盖。再次运行前先归档或复制为独立实验目录，保留已有证据。后续付费运行需用户明确指示。

任务执行和判分、修改后重跑对比、多轮历史及计数加权仍未实现。
