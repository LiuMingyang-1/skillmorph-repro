# SkillMorph 复现项目

这是一个精简、与数据集无关的 SkillMorph 首轮流程复现：输入已记录的智能体轨迹及其使用过的 skills，定位可疑动作、修订相关 skill 内容，并保留所有产物以供审计。

**首版范围——仅一轮。**流程包括轨迹抽象 → 统一动作 → 逐次判断错误 → 覆盖统计与可疑动作排序 → 编辑位置定位 → 提出修改建议 → 评估并应用修改。当前不包含任务执行阶段（轨迹作为输入提供）、修订后的重新评测或多轮历史。

## 运行

```bash
# 填写根目录 .env：LLM_* 用于聊天，EMBEDDING_* 用于嵌入
# 首次克隆仓库时：cp .env.example .env
uv run python -m skillmorph experiments/exp_001
```

唯一的位置参数是实验目录。程序会打印 JSON 摘要，每次运行自动写入新的 `experiments/exp_001/runs/run_NNN/`，不覆盖已有结果。每次独立读取实验根目录的初始输入，不沿用上一次修订后的 Skill。历史失败试跑保存在 `archive/round_001/`。

## 实验目录结构

```text
experiments/<exp>/
  prompts/            各阶段使用的提示词模板（见下文）
  skills/             初始 skill 目录：<skill>/SKILL.md 及相关文件
  data/trajectories.json   输入轨迹（一个 JSON 运行记录列表）
  runs/run_NNN/
    prompts/          本轮实际使用的提示词副本
    skills_before/    输入 skill 树的副本
    trajectories/     实际使用的输入运行记录，每个文件一条
    analysis/         abstracted_runs.json、action_map.json、
                      coverage.json、ranking.json、summary.json
    revision/         edit_sites.json、proposals.json、
                      evaluation.json、skills.diff
    skills_after/     修订后的 skill 树（如果没有应用修改，则为干净副本）
    raw/              JSON 解析失败时留存的模型原始回复
```

## 输入轨迹格式

每个对象代表一次运行：

```json
{"task_id": "task_001", "run_id": "run_1",
 "task": "自然语言任务描述", "outcome": "success | fail",
 "steps": [{"action": "...", "observation": "...",
            "skills_used": ["skill-name"],
            "files_read": ["skill-name/SKILL.md"]}]}
```

- `outcome` 是提供轨迹数据的一方给出的运行结果。
- `skills_used` / `files_read` 记录该步骤查阅过的 skill 或相关文件；这些信息会作为定位线索。它们可以省略，默认值为空。
- 同一任务的多次运行通过 `run_id` 区分；覆盖统计使用 `task_id/run_id` 作为运行标识。

`experiments/exp_001` 附带一个小型**合成示例**（已明确标注为合成数据），用于演示 SQLite `:memory:` 连接问题：skill 要求每次操作都新建连接，因此不同连接之间的查询会失败。

## 提示词

实验的 `prompts/` 目录中有五个模板，分别由以下阶段使用：

| 文件 | 阶段 | 返回内容 |
|---|---|---|
| `abstract.txt` | 轨迹 → 状态迁移 | `{"transitions": [...]}` |
| `judge_error.txt` | 逐次判断是否引入错误 | `{"introduces_error": bool, "reason": "..."}` |
| `localize.txt` | 定位编辑位置（`$mode` 为 artifacts 或 lines） | `{"locations": [...], "rationale": "..."}` |
| `propose.txt` | 提出修订建议 | `{"edits": [...], "rationale": "..."}` |
| `evaluate_select.txt` | 选择并合并修改 | `{"selected": [...], "rejected": [...], "files": [...]}` |

`localize.txt`、`propose.txt` 和 `evaluate_select.txt` 使用 `string.Template` 格式（`$placeholders`）；`abstract.txt` 是系统提示词；`judge_error.txt` 使用 `{context}`、`{k}` 和 `{action}` 占位符。

## 配置

程序自动加载仓库根目录 `.env`，两组配置可使用不同的 OpenAI 兼容供应商：

| 用途 | Base URL | API key | 模型 |
|---|---|---|---|
| 聊天 | `LLM_BASE_URL` | `LLM_API_KEY` | `LLM_MODEL` |
| 嵌入 | `EMBEDDING_BASE_URL` | `EMBEDDING_API_KEY` | `EMBEDDING_MODEL` |

模板中的地址为 `https://api.openai.com/v1`，模型分别为 `gpt-4o` 和 `text-embedding-3-small`。按你的供应商修改地址和模型，并填写两组 key；使用同一家供应商时也需分别填写。已设置的环境变量优先于 `.env`。`.env` 已被 Git 忽略，`.env.example` 是可提交的空白模板。

其余参数仍集中在 `skillmorph/config.py`：`TEMPERATURE`、`MAX_TOKENS`、`ERROR_WINDOW`（h）、`TOP_N_SUSPICIOUS`、`CLUSTER_DISTANCE`，以及为后续循环保留的 `RUNS_PER_TASK`。两类客户端超时均为 120 秒，SDK 对超时及其他可重试错误重试一次；之后错误直接抛出，无应用层重试或回退。

## 离线测试与真实运行

```bash
.venv/bin/python -m pytest -q   # 或 uv run pytest；无需联网或 API 密钥
```

测试通过带有脚本化回复的模拟 OpenAI 客户端（聊天与嵌入接口）运行整条流程，并检查磁盘产物、评估器是否收到动作证据、应用后的 skill diff，以及输入是否保持不变。测试中的分数、选择和修订内容都是测试夹具预先设定的回复，因此测试验证的是**流程接线**，不是模型实际会做出什么判断。

2026-10-27 已完成一次真实 API 全流程试跑（约 73 秒，exit 0），此前离线测试 52 项通过。结果见 `experiments/exp_001/runs/run_001/REPORT.md` 和 `revision/skills.diff`。聊天与嵌入调用均成功，修订将错误的新建连接规则改为复用连接。当前聚类仍过宽，错误判断存在波动，尚未用修订后的 Skill 重新执行任务；合成样例跑通不代表任务成功率提升。
