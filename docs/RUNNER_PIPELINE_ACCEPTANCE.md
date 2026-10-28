# Runner Pipeline 验收记录（2026-10-28，SWE-2-high）

判定：**初步 Pipeline 能跑通**（可换数据集/方法的单轮编排闭环，真实
Docker 通道验证通过；非模型效果验证）。

## 本轮修复（对应父会话初审问题）

1. **方法可换**：`runner/pipeline.py:build_method` 与数据集同样的
   `name`/`.py` 路径工厂解析（`METHOD_MODULES` + `get_method(cfg)`）。
   `copy`/`noop` 移到 `runner/methods.py`；`skillmorph` 由
   `skillmorph/method.py:get_method` 构造。新方法给一个含
   `get_method(cfg)` 的 .py 即可，编排器零改动。
2. **异常语义**：`_phase_runs` 不再 catch-all。数据集明确以
   `outcome="invalid"` 报告的失败记 invalid 继续；`export_trajectory`
   抛错（缺真实日志/证据门拒绝）与执行异常同等处理——cleanup
   （finally）后原样上抛中断实验，不当普通失败降级喂方法。
   cleanup 失败同样上抛——资源泄漏不静默。
3. **输入快照**：`out/skills_before/` 是 before 执行与
   `method.revise` 的唯一输入；源 skill 目录在实验期间被改不影响
   本次产物。prompt_dir 快照同理（`out/prompts/`）。
4. **容器内日志提取**：`executor.trajectory_container_path` 声明
   agent 在容器内写的 JSONL 路径；execute 判分后、cleanup 前
   `docker cp` 到 `run_dir/agent.jsonl`（原始日志随产物保留）。
   `export_trajectory` 默认按此顺序取：显式 `trajectory_jsonl` →
   run_dir 下 `agent.jsonl`。不读取任何凭据。
5. **SkillMorphMethod 组合验证**：测试经 `SkillMorphMethod.with_client`
   /monkeypatch 注入 `tests/pipeline_fixture.FakePipelineClient`
   脚本化分析/修订模型（synthetic，明确标注）；执行 agent 与客户端
   完全分离。生产代码不支持 `client="fixture"`。
6. **接口清理**：删掉冗余 `reset`（cleanup 即每 run 的资源释放，
   after 的「重置」语义 = 新 run_dir 重新 prepare）；`Method.revise`
   契约补充 `skills_after` 必填；`build_method` 删掉未用的
   `params` 透传。

## 证据

- 离线：`uv run python -m pytest tests/` → **67 passed**；
  `datasets/swe_skills_bench: uv run python -m pytest adapter_tests/`
  → **101 passed**。覆盖：调用顺序、after 用 `skills_after`、
  invalid 剔除、execute/export 未知异常 raise + cleanup 仍执行、
  cleanup 失败上抛、skills_before 快照不可变、`dataset.module` 与
  `method.module` 第二实现不改 runner、SkillMorphMethod 完整
  abstraction→attribution→revision（with_client 注入 fake，
  真改文件）、Runner+SkillMorphMethod 端到端、原 CLI 兼容、
  输出目录拒绝覆盖。
- 真实 Docker（deterministic actor + 容器内合成日志）：
  `experiments/exp_003_runner_e2e/out_logpull/`。`agent_cmd` 在
  容器内写正确实现 + 写 `/tmp/agent_trajectory.jsonl`；
  `trajectory_container_path` 触发 `docker cp` →
  `runs_before/run_001/agent.jsonl` → 严格证据门导出正式
  `trajectory.json`（2 steps）→ `copy` method → `runs_after/` 独立
  新容器重跑 `success`。`comparison.json` before/after 均 success。
  `docker ps -a` 无 swesk 容器残留（容器已清，run_dir 产物保留）。

## 真实 vs synthetic 边界

- **真实**：Docker 环境构建/注入/终止核验/判分（pytest+JUnit）、
  `docker cp` 日志提取、轨迹证据门、编排顺序与异常语义。
- **synthetic（显式标注，不作真实轨迹证据）**：
  `agent_cmd` 是确定性 shell 写文件（非模型 agent）；
  `synth_trajs/*.jsonl` 是手工构造的 Claude-JSONL 形状日志；
  离线测试注入的 fake client 全部 LLM 回复是 `pipeline_fixture.py` 预设。
  以上只证明通道连通，不证明模型效果。

## 剩余限制

- 真实模型 agent：需容器内可用的 agent CLI（如 `claude`）+ 认证 +
  其 JSONL 落盘路径——配置项已就绪（`agent_cmd` +
  `trajectory_container_path`），但 CLI 安装/凭据注入方式未定，
  是运行前配置而非本次软件闭环的缺口。
- `runs_per_task` 全局整数（数据集不做任务级差异）；多轮/并发/
  断点续跑/效果统计按范围不做。
