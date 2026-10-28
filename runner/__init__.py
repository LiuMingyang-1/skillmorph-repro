"""数据集/方法可替换的单轮实验编排器。

``runner.interfaces`` 定义 DatasetAdapter 与 Method 两个接口；
``runner.pipeline`` 编排一轮：原 Skill 执行/判分/轨迹 → 方法修订 →
新 Skill 在重置环境执行/判分 → 保存对比。新增数据集只实现
DatasetAdapter，新增方法只实现 Method，不改编排主逻辑。
"""
