# SWE-Skills-Bench 公开成绩与 batch1 难度判断

**检索日期：2026-10-28**  
**范围：**只查公开论文、作者仓库、HF 数据页与公开结果文件；没有启动模型实验或产生模型费用。  
**本地对象：**`GeniusHTX/SWE-Skills-Bench` revision `a111a9d9e53722c7aafd951830b459b08439f2da`，经本地 manifest 记录为与 CTA batch1 内容一致；CTA 是第三方 Counterfactual Trace Auditing 复现框架，不是基准官方发布版。

## 结论摘要

- 公开证据**不支持**“SmartCouponCalculator 裸跑已经接近满分”。官方当前公开结果表含精确的 `tdd-workflow / batch1` 行：No Skill 在四个 agent/model 配置中都为 **21.4%（3/14 项测试）**。这是测试通过比例，不应误读为 14 道独立任务。
- 公开的 Skill 条件结果从 **0.0% 到 78.6%**：Codex + Kimi-K2.6 为 0.0%，Claude Code + Kimi-K2.6 为 78.6%，Claude Code + Haiku 4.5 为 64.3%，Codex + GPT-5.4-mini 为 21.4%。这种跨度表明模型/框架/运行波动值得控制；它不是你们本地固定协议的实测结果。
- 同一 batch1 的验收测试测的是**最终功能正确性**，没有检查“先写测试、观察红灯、再实现、绿灯、重构”的 TDD 顺序。因此它不能直接作为 TDD 遵循度指标。
- batch1 可保留作工程 smoke / 执行链路验证；是否适合正式研究，取决于你们目标。如果研究的是 TDD Skill 的流程遵循，现有判分目标不匹配；如果研究 SkillMorph 闭环对最终功能成功的影响，至少先用固定 Actor 做 paired pilot，并补充轨迹流程标注。

## 基准身份与版本关系

| 材料 | 版本与范围 | 与本地包的关系 |
|---|---|---|
| SWE-Skills-Bench 原始论文 v1 | arXiv `2603.15401v1`，2026-03-16；49 项 skill，约 565 个任务实例 | 这是 HF 49 条数据集和 SkillMorph 引用的 benchmark 代际。论文 §3–4 与原始任务定义相关。 |
| HF 数据集 | `GeniusHTX/SWE-Skills-Bench`，49 rows；本地冻结 revision `a111a9d9e53722c7aafd951830b459b08439f2da` | 官方作者数据页列出 `tdd-workflow`、Smart Coupon Calculator、目标仓库和 Python 镜像；本地 manifest 记录该 revision 的任务/测试/Skill 与 CTA 抽取内容校验一致。 |
| CTA | `explicitcontextualunderstanding/cta`，本地固定 commit `8822baed…` | 第三方 trace-auditing 研究复现代码及抽取来源，不等同官方基准。其适配判分可能与官方有所不同。 |
| SWE-Skills-Bench 作者仓库当前主线 | `ControllableModel/SWE-Skills-Bench`，README 描述 98 skills × 10 requirements × 4 agent/model 配置 | 2026-10-28 可见的扩展/更新版；原始 CSV 可读到 batch 级记录。其 `tasks/batch1/tdd-workflow.md` 与 `tests/batch1/test_tdd_workflow.py` 对应 Smart Coupon Calculator，公开 CSV 有精确 batch1 行。 |
| SkillMorph | arXiv `2610.11858v1`，标题 *Trajectory-Guided Fault Localization for Agent Skill Evolution*，2026-10-08 | 使用 SWE-Skills-Bench 的 49 skills × 每 skill 10 批任务，三轮演化；报告留出集整体结果。它不是基准原始论文，也没有给出 SmartCouponCalculator 单题成绩。 |

截至检索日，原始论文已出现 v2（2026-10-27），改为 98 skills、四个 agent–model 配置和 3,920 组配对评估。**v1 与 v2 的总体数值不可混为同一实验**：样本范围、配置、设计和统计口径不同。下方明确标出版本与来源。

## 可核查的公开成绩

### 精确 batch1 结果：当前官方公开 CSV

作者仓库 README 说明结果 CSV 每行是一个 `(skill, requirement)`，分数为平均测试通过率；配置为 Claude Code 或 Codex CLI，加指定模型；每个单元在新隔离容器中运行。报告结果使用 Enroot 而非 Docker，且通过 infra-clean gate。仓库公开 batch1 的原任务与测试文件，可用于核对本任务身份。

| Agent / model（仓库写法） | No Skill | With Skill | Δ pp | 范围与口径 |
|---|---:|---:|---:|---|
| Codex / GPT-5.4-mini | 21.4% | 21.4% | 0.0 | `tdd-workflow`, batch1；14 个验收测试的通过比例 |
| Codex / Kimi-K2.6 | 21.4% | 0.0% | −21.4 | 同上 |
| Claude Code / Kimi-K2.6 | 21.4% | 78.6% | +57.2 | 同上 |
| Claude Code / Haiku 4.5 | 21.4% | 64.3% | +42.9 | 同上 |

**解读边界：**CSV 明确列出 `none_pass_rate` / `one_pass_rate`，README 定义为 batch 内测试通过率；四个数字分别对应 3/14、3/14；0/14；11/14；9/14。此处的 `one` 是显式注入原 Skill，不是 SkillMorph 优化版。README 的 sweep 定义每个 agent/model × skill × requirement × mode 为一个 cell，论文 v2 也写明每个 requirement 在每个配置下各跑一次；基础设施失败会重跑到有效，因此这是**单次有效评分**，不是多次采样均值。seed 和 API 端点具体 snapshot 未报告。当前结果表不能直接等同于本地冻结协议的运行结果。

对应原始证据：

- [官方 README：实验设计、结果表、模型配置、运行环境与结果文件说明](https://github.com/ControllableModel/SWE-Skills-Bench#readme)（“Benchmark design”“Results”“Containers”）
- [官方合并原始 CSV](https://raw.githubusercontent.com/ControllableModel/SWE-Skills-Bench/main/results/final_results/ALL_combined_cells.csv)：batch1 行附近可见四种配置下的 `tdd-workflow` 数据（Codex GPT-5.4-mini、Codex Kimi-K2.6、Claude Kimi-K2.6、Claude Haiku 4.5）。
- [官方 batch1 任务原文](https://raw.githubusercontent.com/ControllableModel/SWE-Skills-Bench/main/tasks/batch1/tdd-workflow.md)；[官方 batch1 测试代码](https://raw.githubusercontent.com/ControllableModel/SWE-Skills-Bench/main/tests/batch1/test_tdd_workflow.py)。测试文件定义了 14 个 `test_*`，与本地冻结包所称 14 项吻合。

### 原始论文 v1 的 Skill 级结果（不是单题 / batch1）

原论文 §4.1–4.3、Table 2 使用 **Claude Code + Claude Haiku 4.5**，在 CPU-only Ubuntu 24.04 Docker 中，将 Skill 文件放入项目根目录并让 agent 自行发现；与 no-skill 条件配对。v1 的单次评估范围为每个 skill 全部任务实例。Table 2 的 `tdd-workflow` 行报告 **14 个实例、With Skill 28.6%、Without Skill 21.4%、Δ +7.1 个百分点**；这是该 Skill 的汇总，不是明确标为 `batch1` 的行。原论文给出该 Skill 平均 token 148K vs 83K（+78.6%），但这不是成功率。

原论文 v1 总体是 **565 个任务实例**，平均 pass rate 从 **89.8%（without）到 91.0%（with），+1.2 pp**；39/49 个 Skill 的 Δ 为零，7 个有明显增益，3 个出现负增益。此平均值不用于推断 batch1 成绩。

来源：[原论文 v1 §3.4、§4.1–4.3 / Table 2](https://arxiv.org/html/2603.15401v1#S4)；精确 `tdd-workflow` 表行见 [Table 2 的 HTML 行](https://arxiv.org/html/2603.15401v1)。论文 §4.1 未报告随机重复次数或 seed；按公开文本能核实的只是所用 agent/model、任务规模、Docker 环境与 with/without 条件。

### 原论文 v2 总体成绩（不能当 v1 或 batch1 成绩）

v2 §4.1、Table 2 报告四种 agent/model 配置各 980 个配对样本、合计 3,920 对；主要指标为每个 requirement 的 pass ratio 平均值。模型是 GPT-5.4-mini、Kimi-K2.6（分别由 Codex / Claude Code 执行）和 Claude Haiku 4.5（Claude Code）。结果如下：

| Agent / model | Without Skill | With Skill | Δ pp | 规模 |
|---|---:|---:|---:|---|
| Codex / GPT-5.4-mini | 75.98% | 76.74% | +0.76 | 980 对 |
| Codex / Kimi-K2.6 | 77.60% | 77.32% | −0.29 | 980 对 |
| Claude Code / Kimi-K2.6 | 78.53% | 79.18% | +0.64 | 980 对 |
| Claude Code / Haiku 4.5 | 74.24% | 74.50% | +0.26 | 980 对 |
| 汇总 | 76.59% | 76.93% | +0.34 | 3,920 对 |

来源：[原论文 v2 §4.1–4.2 / Table 2](https://arxiv.org/html/2603.15401#S4)。v2 对 `tdd-workflow` 的 skill-level 表项在当前论文 HTML 中没有展示（Table 3 仅列显著项）；不据总平均推算其单项分数。官方主线 CSV 才提供上节的 batch1 行。

## SkillMorph：使用了基准，但结果是跨任务留出汇总

SkillMorph §5.1 说明：SWE-Skills-Bench 包含 49 个独立 Skill，每个 Skill 对应 10 个 task batch；奇数/偶数 ID 分为 A/B，各 5 个任务；分别做 A→B 与 B→A。任务执行使用 **Claude Code + DeepSeek-V4-Flash-0731**；每轮每个演化任务执行 3 次，SWE-Skills-Bench 做 3 轮；最终在留出任务上各执行 3 次。成功定义为限时内完成且所有测试/验证通过。公开信息未给出逐题模型分数、每个 Skill 的优化前后 pass rate、batch1 成绩，也未给 No Skill 基线。

| 方法（初始 Skill / 演化后） | Pass@3 | Trial accuracy | Pass³ | 评估范围 |
|---|---:|---:|---:|---|
| Base Skills（原始 Skill） | 82.45% | 75.44% | 67.96% | 两方向合并的 SWE 留出任务 |
| SkillOpt | 88.98% | 84.90% | 80.41% | 同上 |
| EvoSkill | 85.71% | 80.41% | 74.49% | 同上 |
| SkillAdaptor | 86.73% | 82.04% | 77.14% | 同上 |
| CAP-Evolve | 92.24% | 89.39% | 84.90% | 同上 |
| SkillMorph（优化后） | 95.51% | 92.24% | 88.37% | 490 个留出任务 × 每任务 3 次，1470 次试验 |

Pass@3 表示三次运行至少一次成功的任务比例；Pass³ 表示三次全成功的任务比例；Trial accuracy 是全部单次运行的成功比例。Base Skills 不是 No Skill。论文报告 SkillMorph 相对 Base Skills 的 Pass@3 绝对增加 13.06 pp，Trial accuracy 增加 16.80 pp，Pass³ 增加 20.41 pp；论文摘要正文给的是相对提升百分比，勿与百分点混淆。数据是跨 49 skills 的留出汇总，不说明 batch1 裸跑难度，也不能外推到本地模型/预算。

来源：[SkillMorph §5.1–5.3 / Table 1](https://arxiv.org/html/2610.11858#S5)；模型、重复、任务切分在 §5.1，指标定义在 §5.1 Metrics，整体成绩在 Table 1 和 §5.2。

## 14 项验收测试测了什么

本地 [`tdd-workflow-batch1.md`](../datasets/swe_skills_bench/tasks/tdd-workflow-batch1.md) 是一个单一的 SmartCouponCalculator 实现任务，要求实现累计门槛折扣、类别折扣、VIP/SVIP、最优叠加及边界情形。其 14 项测试在固定接口下检查：文件与语法、类可导入、$100/$200 阈值、类别折扣、VIP/SVIP、组合折扣、零价、空购物车和无效 tier。

**判定：测试主要测功能和最终状态，不测 TDD 流程。**测试没有检查新增测试文件、测试先于实现、先红后绿、重构、覆盖率或 agent 运行测试的轨迹。测试文件名/Skill 名含 `tdd` 并不能证明测量了 TDD 遵循。成功判分为 14 项测试结果，只能说明最终验收行为。

可能的天花板因素（推断，不是实验结论）：任务在小型 Python scaffold 中实现一个单类；阈值和折扣规则明确，依赖轻，所需代码量看起来有限。因此强模型可能较容易完成功能实现。相反，组合测试只允许 140–190 的宽范围，负值处理和“最优叠加”规则存在描述空间，且需要识别固定 API；这些也可能引入不确定性。不能仅凭“任务看起来简单”断言高分。

实测证据与上述推断相反于“现有测试已接近满分”的前提：在官方公开 batch1 CSV 的四个配置中 No Skill 均为 21.4%；但这些公开分数来自另一版公开 harness/镜像与运行设置。你们自己的 Docker 判分校验只证明已知正确实现 14/14、原始 scaffold 14 项失败，证明测试能区分这两个夹具；它没有给任何真实模型 baseline。

## 证据缺口与建议

- **未公开或无法从论文核实：**SkillMorph 的单独 batch1 / SmartCouponCalculator 分数、No Skill 成绩、`tdd-workflow` Skill 级优化前后成绩；当前作者 CSV 也没有 SkillMorph 修订后条件。
- **版本及运行差异：**公开 CSV 虽有同名 batch1 和相符测试，但不是本地固定的 CTA commit / 镜像 digest / 本地适配判分协议。不同执行 harness、CLI 版本、timeout、模型端点 snapshot、随机种子可能改变分数。公开 README 未说明各 cell 重复次数和 seed；不要把单元分数当方差估计。
- **官方资料可追溯性：**HF 固定 revision 是 49 条数据包；当前作者仓库 README/CSV 则写 98 skills 和新的四配置 sweep。报告实验时需把数据 commit、任务/测试哈希和运行器版本写清楚，不能只称“用了 SWE-Skills-Bench”。
- **建议定位：**保留 batch1 作接口、环境、注入和判分的工程 smoke。暂不把它单独当作 TDD 过程能力研究任务；它没有过程判据。若研究终点是功能成功，可将其作为一个定量 pilot 单元，但正式结论需多个预先确定的任务/family，不能把近重复 StringCalculator 批次当独立题数。
- **最小预实验（不改模型强度、不挑结果）：**冻结一个明确的 Actor/model snapshot、CLI/agent 版本、prompt、工具权限、时间/调用/token 预算、镜像 digest、任务/skill 哈希和 14 个 nodeid；同一任务与配置做 No Skill vs 原始 `tdd-workflow` 的成对运行，臂次顺序交错，固定并记录配对 seeds，保存完整轨迹、token/时间和测试结果。先做至少 5 对作为方差/地板天花板诊断；若准备对“改善”作研究结论，扩大重复并对预先定义的多个独立 task families 做完整配对实验，不以一次 pilot 的偶然胜负下结论。
- **TDD 目标要加过程测量：**在功能验收之外，对轨迹预定义且盲评：测试是否先于实现、是否观察到预期失败、实现后是否复跑至通过、是否在保持通过时重构。保留现有 14 项最终功能成功率作为独立终点，避免用过程遵循替代功能正确。

## 主要来源

1. Han et al., [SWE-Skills-Bench v1，arXiv:2603.15401v1](https://arxiv.org/html/2603.15401v1)：§3.4、§4.1–4.3、Table 2（原始 49-skill 版本）。
2. Han et al., [SWE-Skills-Bench v2，arXiv:2603.15401](https://arxiv.org/html/2603.15401)：2026-10-27 版本；§3、§4.1–4.2、Table 2（98 skills、四配置）。
3. Ge et al., [Trajectory-Guided Fault Localization for Agent Skill Evolution / SkillMorph，arXiv:2610.11858v1](https://arxiv.org/html/2610.11858)：§5.1–5.3、Table 1。
4. [HF GeniusHTX 数据集卡](https://huggingface.co/datasets/GeniusHTX/SWE-Skills-Bench)；本地 manifest 固定 revision `a111a9d9e53722c7aafd951830b459b08439f2da`。
5. [CTA 第三方仓库](https://github.com/explicitcontextualunderstanding/cta)；本地 manifest 固定 commit `8822baed308a74b5921e2a5be50394c1a4a8fc96`。
6. [当前官方仓库 README 与公开结果 CSV](https://github.com/ControllableModel/SWE-Skills-Bench#readme)；[CSV 原件](https://raw.githubusercontent.com/ControllableModel/SWE-Skills-Bench/main/results/final_results/ALL_combined_cells.csv)。
