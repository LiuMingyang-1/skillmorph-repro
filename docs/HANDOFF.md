# 设备切换交接 — 2026-10-26

分支：`fix/portable-paths-api-timeouts`。当前未完整跑通实验。

## 已完成

- 聊天和 embedding 客户端超时统一为 30 秒，仍不重试。
- 定位提示词明确 skill/artifact 分开，artifact 不重复 Skill 名前缀。
- 协议相对路径统一 POSIX `/`，本地文件操作使用 pathlib。
- 39 项离线测试通过；包含 Windows 风格纯路径测试，但未在 Windows 实机验证。

## 真实试跑

一次真实试跑约 68.92 秒后退出；完成抽象、聚类、覆盖统计、排名，越过原先路径重复错误，进入 propose 后报错：

```text
JSONDecodeError: Invalid \escape: line 1 column 1049 (char 1048)
```

原始模型回复没有保存，具体非法转义未知，尚未修复。未产生完成的提案、评估、Skill 修订或 diff。部分产物及脱敏日志保存在 `experiments/exp_001/rounds/round_001/`。本次运行的提示词快照早于后续跨平台补充，按原样保留。

动作聚类也可能过宽，把建表、开新连接、查询等合为一组，应人工审查 action_map 和 abstracted_runs。实验仅为 2 任务、4 条合成轨迹，不代表效果提升。

## 换设备继续

1. 获取并切换此分支，`uv sync` 安装锁定依赖。
2. `.env` 不随 Git 同步，需在新设备安全配置两类 API，参考 `.env.example`；不要提交凭据。
3. `uv run python -m pytest -q`；Windows 仍需实际文件读写验证。
4. 先诊断非法 JSON，建议补充失败响应的安全留存，避免证据丢失；不要静默修补或自动重试。
5. `round_001` 已存在，CLI 会拒绝覆盖。再次运行前先归档或复制为独立实验目录，保留已有证据。后续付费运行需用户明确指示。

任务执行和判分、修改后重跑对比、多轮历史及计数加权仍未实现。
