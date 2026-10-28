# Runner Pipeline 交付记录（2026-10-28，验收更新版）

目标：单轮、可替换数据集/方法的实验编排器，跑通「原 Skill 执行/判分/
轨迹 → 方法修订 → 新 Skill 重置执行/判分 → 对比」。非效果验证、无
多轮历史、无插件框架。验收结论见
`docs/RUNNER_PIPELINE_ACCEPTANCE.md`：**能跑通**。

## 架构

- `runner/interfaces.py`：`DatasetAdapter`（list_tasks / prepare_run /
  execute / export_trajectory / cleanup）与 `Method`（revise）。
  Runner 只依赖这两个协议，无 SWE 专属分支；新数据集只实现
  adapter，新方法只实现 method。cleanup 即每 run 的资源释放——
  after 的「重置」是新 run_dir 重新 prepare，不单设 reset。
- `runner/pipeline.py`：编排 `runs_before/`（prepare→execute→
  export→cleanup 每 task×rep）→ `method.revise` → `runs_after/`
  （prepare→execute→cleanup）。数据集明确报告 `outcome="invalid"`
  的 run 不喂方法，列入 `summary.json:invalid_runs`；导出与执行
  的未知异常（含 export 证据门拒绝）cleanup 后原样抛出。
- `runner/methods.py`：内置 `copy`/`noop` method（原样拷贝 Skill
  树，采集/通道验证用）。
- `datasets/swe_skills_bench/adapter.py`：薄壳复用 `setup.py`/
  `run.py`/`evaluate.py` 的登记-执行-判分-导出协议（函数调用，非
  subprocess）。`prepare_run` 做 setup.py 登记语义；`execute` 跑
  run.py+evaluate.py，判分后按 `trajectory_container_path` 把容器内
  agent JSONL `docker cp` 到 `run_dir/agent.jsonl`；
  `export_trajectory` 走 `export_formal_trajectory` 真证据门；
  `cleanup` 只删本 run 容器。
- `skillmorph/method.py`：`SkillMorphMethod` 实现 `Method`，内部调
  `skillmorph` abstraction/attribution/revision（`_revision` 复用，
  算法未重写）。`get_method(cfg)` 是 runner 工厂入口；
  `with_client` 注入 fake；`env`（默认）走 .env LLM_*。执行模型
  （agent-cmd）与分析/修订模型（client）完全分开。

## 入口与配置

```bash
uv run python -m runner <config.json>   # 顶层摘要 JSON 打印到 stdout
```

配置字段：`dataset{name|module,tasks|task_families,runs_per_task}`、
`method{name:"skillmorph"|"copy"|"noop"|<.py路径>,prompt_dir?,
client?("env")}`、`skill{dir}`、
`executor{agent_cmd(必填),agent_timeout_sec?,eval_timeout_sec?,
agent_config_json?,trajectory_jsonl?,trajectory_container_path?}`、
`output{dir}`、`skip_after`(export 采集用)。路径相对配置文件目录
解析。

产物 `<output>/<name>/`：`config.json`、快照 `prompts/`、
`skills_before/`（**before 与 method 的唯一输入快照**）、
`trajectories/`、`runs_before|after/run_NNN/`（各 run 含
config/run_state/execution/evaluation/runner_record/agent.jsonl/
trajectory）、`method/{analysis,revision,skills_after}`、
`comparison.json`、`summary.json`。

## 换数据集/方法

- 数据集：实现 `DatasetAdapter` 五个方法并暴露
  `get_adapter(cfg)`；放 `.py` 后配置 `dataset.module=<path>`，
  或加入 `DATASET_MODULES` 映射。
- 方法：实现 `Method.revise` 并暴露 `get_method(cfg)`；配置
  `method.module=<path>` 或 `method.name` 查 `METHOD_MODULES`。
  编排器两边都零改动（测试覆盖第二数据集/第二方法）。

## 验证

- 离线：`tests/test_runner_pipeline.py`——调用顺序、after 用
  `method/skills_after`、invalid 不喂方法、异常原样抛出+cleanup
  仍执行（execute 与 export 同语义）、skills_before 快照不可变、
  `dataset.module`/`method.module` 接入、SkillMorphMethod 完整
  修订链路（with_client 注入 fake，真改文件）、
  原 `python -m skillmorph` CLI 兼容。根 `tests/` 67 passed；
  `adapter_tests/` 101 passed。
- 真实 Docker：`config_swe_logpull.json` 跑通全链路（deterministic
  actor + `trajectory_container_path` 自动提取容器内 JSONL →
  证据门导出 → copy method → after 新容器重跑）——容器已清。
  **这是通道验证，不是模型效果**：actor 是确定性 base64 写入、
  JSONL 手工合成、fake client 脚本预设，均标 synthetic。

## 限制 / 显式缺口

- **真实模型 agent 接线未做**：`agent_cmd` 是容器内 dev 的 `sh -c`
  命令，需要容器内可用的 agent CLI（如 `claude`）+ 认证。镜像未
  预装 agent CLI，凭据注入方式未定——一次真实模型试跑需要运行前
  决定 CLI/认证，属配置缺口而非软件闭环缺口。
- `trajectory_container_path` 提供自动 `docker cp`；`trajectory_
  jsonl`（宿主路径/dict）仍是显式覆盖选项。
- **SkillMorphMethod client**：生产只支持 `"env"`（.env，默认）；
  测试/离线编排用代码注入 `with_client(<fake client>)` 或
  monkeypatch `build_method`——`tests/pipeline_fixture` 脚本化
  回复均标 synthetic。`runs_per_task` 全局整数，无任务级差异。
- 多轮、内部状态、效果统计、并发、断点续跑均不做（按范围要求）。

## 审阅入口

`uv run python -m runner experiments/exp_003_runner_e2e/
config_swe_logpull.json`（需 Docker 已拉镜像）。审阅者重点：
`runner/pipeline.py` 编排顺序与 invalid/异常语义、`_load_entry`
工厂解析、`adapter.py` 的 `docker cp` 提取与 run/evaluate 协议
一致性、`skillmorph/method.py` 未重写算法。
