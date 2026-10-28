# SWE-Skills-Bench 可用性调查

检查日期：2026-10-27。仅下载与静态检查，未运行智能体或容器。

## 结论

可作为接入候选，但 Hugging Face 的 JSONL 不能单独视为完整运行环境。
第三方 CTA 仓库提供了补齐版本、任务批次与辅助文件的线索；尚未确认其与 SkillMorph 原实验完全一致。

## 已核实

- 官方数据：https://huggingface.co/datasets/GeniusHTX/SWE-Skills-Bench
- 数据页标注 MIT；下载的 JSONL 有 49 条记录，均有 task_prompt、skill_document、test_code、docker_image。
- 48 条 repo_commit 为空，1 条有 commit；48 条有 repo_url。全部 test_code 可经 Python AST 解析，这不等于能够执行。
- 7 条测试引用 `_dependency_utils`，HF 文件列表未提供该辅助模块。
- 示例测试存在较弱的判分：python-resilience 多项检查只检索源码关键词/数字；mcp-builder 部分检查扫描整个项目，不限定新增模块。需进一步审查，不能把测试全过直接等同于完整功能正确。
- 原官方 GitHub 地址本次访问返回 404：https://github.com/GeniusHTX/SWE-Skills-Bench

## 第三方补齐线索

仓库：https://github.com/explicitcontextualunderstanding/cta

检查时树对应提交：`8822baed308a74b5921e2a5be50394c1a4a8fc96`。

- `config/benchmark_config.yaml`：49 个 Skill 配置，48 个填写 40 位固定 commit。PyTorch 项未填写，注释称代码已在镜像内。
- `tests/batch1/_dependency_utils.py` 存在。
- `tasks/batch1` 有 49 个文件；batch2–10 各 50 个文件（文件数不等于有效任务数，尚未逐项对应）。
- `tests/batch1`–`batch10` 均有文件；不能据此直接认定是论文的 490 个任务。
- 抽查 tdd-workflow 的 batch1 测试与 HF test_code，去除外层空白后文本完全一致；尚未全量对齐。
- 该仓库是另一项研究的实现，不能当作官方镜像或未经修改的原始发布版。复用前需核对许可、任务/测试一致性、依赖和评测规则。

## 尚未完成的运行验证

- 当前机器未找到 docker 命令。
- Docker Hub 查询受 DNS/访问失败影响，镜像是否公开、可拉取及其平台架构仍未知；不能认定镜像不存在。
- 尚未运行基线判分或任何付费模型调用。

## 接入前最小验证

1. 固定第三方资料提交，逐项对齐任务、Skill、测试和 repo commit，确认再利用的许可。
2. 在 Docker 可用的环境验证一个任务的镜像、项目检出和测试收集，并记录镜像 digest。
3. 检查未修改项目的基线，再用已知正确和错误实现检查判分区分能力；不向执行智能体暴露隐藏验收测试。
4. 确认同一 Skill 有足够不同任务，才能划分演化集和留出集；HF 的 49 条记录本身不足以证明这一点。
5. 完成以上检查再接入本项目 execution/evaluation；正式实验保持各方法任务起点与预算一致。
