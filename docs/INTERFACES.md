# 模块间接口约定

首版范围：已有轨迹 + skill → abstraction → attribution → revision，单轮（loop 1，无历史）。所有阶段间数据用普通 dict/list，可JSON 序列化；落盘为 JSON 文件，目录结构见 REPRO_PLAN。以下签名是约定目标，各模块实现时保持一致。

## 共用设施

```python
# skillmorph/llm.py
def chat(messages, *, model=None, client=None, json_mode=False, temperature=None) -> str
def chat_json(messages, *, model=None, client=None, temperature=None) -> dict
```

- `client` 可注入 OpenAI 兼容 fake（带 `chat.completions.create`），离线测试不联网。
- 无重试、无兜底；SDK `max_retries=0`。异常直接向上抛，各模块不要吞。
- `chat_json` 以 `response_format={"type":"json_object"}` 请求并 `json.loads` 返回；prompt 必须说明期望的 JSON 结构。
- 模型/温度/max_tokens 默认值在 `skillmorph/config.py`；`TOP_N_SUSPICIOUS`、`ERROR_WINDOW`（论文 h）、`CLUSTER_DISTANCE` 也在那里。
- 串联入口见末尾「实验入口（pipeline）」一节；`pipeline.run_experiment` 同样接受 `client` 注入。

## 阶段 0：输入（execution 暂缺，由实验数据提供）

原始轨迹 `raw_trajectory`（每个 run 一个 JSON）：

```json
{
  "task_id": "task_001",
  "run_id": "run_1",
  "task": "任务自然语言描述",
  "outcome": "fail",
  "steps": [
    {"action": "read_file(path='a.py')", "observation": "...", "skills_used": ["mcp-builder"], "files_read": ["SKILL.md"]}
  ]
}
```

- `outcome`: `"success"` / `"fail"`（判分结果，执行阶段或外部数据给出）。
- `skills_used`、`files_read`：该步 consult 的 skill 名和 skill 文件路径，供 edit-site 定位缩小搜索范围；没有就空列表。
- 一个 task 的多次 run 用 `run_id` 区分（`task_001/run_1` 形式拼全局 id）。

## 阶段 1：abstraction

输入：task 的原始 run 列表 → 输出：抽象轨迹 + 统一动作表。

```python
# skillmorph/abstraction/...
def abstract_run(raw: dict, *, prompt_dir, client=None) -> dict          # 单条轨迹 → 抽象轨迹
def cluster_actions(abstracted_runs: list[dict], client=None) -> dict    # 同义动作合并 → action_id 映射（就地写回）
```

抽象轨迹（保留 `task_id/run_id/outcome`）：

```json
{
  "task_id": "task_001", "run_id": "run_1", "outcome": "fail",
  "transitions": [
    {"k": 1, "state_before": "仓库已克隆，未安装依赖", "action": "pip install -e .", "state_after": "依赖安装完成", "skills_used": ["mcp-builder"], "files_read": ["SKILL.md"]}
  ]
}
```

- `transitions[k]` 对应论文 (µ_{k-1}, a_k, µ_k)；`state_*` 是 LLM 归纳的短句。
- `cluster_actions` 对全部 run 的 `action` 文本做嵌入 + 层次聚类（scipy `linkage` + `fcluster`，阈值 `CLUSTER_DISTANCE`），输出 `{action_text: "act_001"}` 映射；把 `transitions[*].action` 替换/补充为 `action_id`，同时保留原文本 `action_text`。同一个 `action_id` 跨任务、跨 run 可比。

Prompt：`prompts/abstract.txt` —— 返回 `{"transitions": [{state_before, action, state_after}]}`。

## 阶段 2：attribution

输入：带 `action_id` 的抽象 run 列表（多任务合并）→ 输出：可疑动作排名。

```python
def mark_errors(run: dict, *, prompt_dir, client=None) -> dict             # 成功 run 内逐 occurrence 判错，写 transitions[*].introduces_error
def coverage(abstracted_runs: list[dict]) -> dict                          # 每 task 每 action 的 N-/N+/F 计数
def rank(coverage_by_task: dict, *, top_n=TOP_N_SUSPICIOUS,
         abstracted_runs=None) -> list[dict]
```

- `mark_errors`：只对 `outcome=="success"` 的 run 调用（其他 outcome 抛 ValueError）。对每个 transition k，取前后 `ERROR_WINDOW` 步窗口问 LLM「该动作是否引入了错误状态（未解决错误或校验失败），而非仅暴露已有错误」。是 → `introduces_error=true`，并记 `error_reason`。失败 run 全部动作直接算失败覆盖，不调 LLM。
- `coverage`：论文 §4.2 逐 occurrence 判定后，每 run 对同一 action 的成功/失败覆盖**分别去重**——同一成功 run 内 a 同时含判错与未判错 occurrence 时，该 run 对 a 同时贡献 N-=1 和 N+=1（论文 "each run contributes at most once to each coverage count"）。返回 `{task_id: {"actions": {action_id: {"n_fail","n_succ","fail_runs","succ_runs"}}, "f": int, "fail_runs": [...]}}`，run 用 `task_id/run_id` 全局标识。`F_t` = 该 task 中至少对一个 action 提供失败覆盖的 run 数（失败 run + 含判错 occurrence 的成功 run）。
- `rank`：候选 = 任一 task N->0 的 action；分数按论文 Eq.9：`s(a) = N-(a) / sqrt(F * (N-(a)+N+(a)))`，`N±` 为跨任务聚合，`F = Σ_t F_t`。首轮无历史（Eq.5-7 加权未实现），无 `prev` 参数；`abstracted_runs` 仅用于回填 `action_text`，缺省为空串。
- 输出每项：`{"action_id","action_text","score","n_fail","n_succ","fail_runs":["task_001/run_1"],"succ_runs":[...],"tasks":["task_001"]}`，按 score 降序取 `top_n` 作为 `A*`。`fail_runs`/`succ_runs` 供 edit-site 定位查执行上下文，必须保留。

Prompt：`experiments/exp_001/prompts/judge_error.txt` —— 返回 `{"introduces_error": true|false, "reason": "..."}`。

## 阶段 3：revision

输入：`A*`（含证据）、skill 目录、抽象轨迹 → 输出：修订后的 skill 文件 + 证据记录。skill 根目录统一为 `skill_dir/<skill>/<artifact>`，artifact 路径可嵌套；输入树永不修改，结果写入调用方给的 `output_dir`。所有读 prompt 的函数带 keyword-only `prompt_dir`（实验 prompts 目录）。模块为 `skillmorph/revision/`，三个函数经 `skillmorph.revision` 导出。

```python
def localize(action: dict, skill_dir, runs, client=None, *, prompt_dir) -> dict          # → edit_site
def propose(edit_site: dict, client=None, *, prompt_dir) -> dict                          # → proposal
def evaluate_and_patch(proposals, skill_dir, client=None, *, prompt_dir, output_dir) -> dict  # → 应用结果
```

- `localize` 是分两步的 LLM 收窄（overview + 轨迹记录的 consulted files 选 artifacts → 编号全文选行区间），不是 agent 循环。无兜底：空选择直接返回 `locations=[]`（不发第二次调用），所选文件不存在则抛错。轨迹的 `skills_used`/`files_read` 只作 prompt 证据。
- `propose` 自带全部上下文：`localize` 返回的 `edit_site` 已内嵌每个 location 的完整 `content`、rationale、evidence 和 occurrence 上下文，调用方传入即可，无需再读 skill 树。
- `evaluate_and_patch`：`proposals` 每项应附证据——`{**proposal, "edit_site": site}`，或自行带 `evidence`/`occurrences` 字段，否则 LLM 只有裸 action_id 可评。空 proposals 不发请求，干净复制输入树。`selected` 为空时不应用任何 `files`；有选中时 `files` 只应是选中建议的合并结果。

edit_site：

```json
{
  "action_id": "act_003",
  "locations": [{"skill": "mcp-builder", "artifact": "reference/node_mcp_server.md", "lines": [40, 55], "content": "..."}],
  "rationale": "Building and Running 未规定 in-memory 连接共享…",
  "evidence": {"score": 0.61, "n_fail": 2, "n_succ": 0, "fail_runs": ["task_001/run_1"], "succ_runs": [], "tasks": ["task_001"]},
  "occurrences": [{"run": "task_001/run_1", "outcome": "fail", "step": 3, "state_before": "...", "action": "...", "state_after": "...", "skills_used": [], "files_read": [], "introduces_error": null, "error_reason": null, "prev_action": "...", "next_action": "..."}]
}
```

- 一个 edit site 可跨多个 skill/artifact 的多个 `lines` 区间（论文允许协同修订）。
- `occurrences[*].introduces_error`/`error_reason` 透传 `mark_errors` 的逐 occurrence 判断；失败 run 未经判断则为 null，不代表该步无错。

proposal：

```json
{
  "action_id": "act_003",
  "edits": [{"skill": "mcp-builder", "artifact": "reference/node_mcp_server.md", "change": "新增规则：imports 与 queries 共用同一 in-memory 连接", "lines": [40, 55]}],
  "rationale": "..."
}
```

应用结果（`files` 为完整文件内容，代码写入 `output_dir` 并用 difflib 生成 diff，不解析 patch 文本）：

```json
{
  "selected": ["act_003"],
  "rejected": [{"action_id": "act_007", "reason": "与现有内容重复"}],
  "diff": "统一 diff 文本",
  "skills_after": "output_dir 路径"
}
```

Prompts（返回结构必须在 prompt 中写明并与上面一致）：

- `prompts/localize.txt` → 按 `$mode` 分两段：artifacts 模式 `{"locations":[{skill,artifact}], "rationale":"..."}`；lines 模式 `{"locations":[{skill,artifact,lines:[start,end]}], "rationale":"..."}`
- `prompts/propose.txt` → `{"edits":[...], "rationale":"..."}`
- `prompts/evaluate_select.txt` → `{"selected":[...], "rejected":[{action_id,reason}], "files":[{skill,artifact,content}]}`（三步 CoT：按证据/重复冲突/成功-run 风险评估 → 选高价值 proposal → 合并为完整文件内容；selected 为空时 files 必须为空）

## 首轮简化与不可省略项

- 首轮无历史：跳过 Eq.5-7 加权、revision history 输入，其余照论文。
- 不可省略：成功 run 的逐 occurrence 判错；成功/失败覆盖按 run 分别去重；Ochiai 形式打分；edit site 带 line 区间和 rationale；proposal 评估筛选后再合并成 patch；保留 fail/succ run 列表作为证据。

## 实验入口（pipeline）

```python
# skillmorph/pipeline.py
def run_experiment(experiment_dir, *, client=None) -> dict   # 单轮全流程 → summary dict
```

- 输入：`experiments/<exp>/` 下 `data/trajectories.json`（一个 JSON 列表）、`prompts/`、`skills/`。
- 写入 `rounds/round_001/`：`prompts`、`skills_before`、`trajectories`、`analysis`（`abstracted_runs.json`、`action_map.json`、`coverage.json`、`ranking.json`、`summary.json`）、`revision`（`edit_sites.json`、`proposals.json`、`evaluation.json`、`skills.diff`）、`skills_after`。
- 已有 round 目录时 `mkdir(exist_ok=False)` 直接报错，不覆盖、不续跑。空 `locations` 的 edit site 不产生 proposal；`selected` 为空时 `skills_after` 是输入原样拷贝。
- CLI：`uv run python -m skillmorph <experiment_dir>`。
