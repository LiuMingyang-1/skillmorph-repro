"""加载修订阶段的 prompt 模板。"""

from pathlib import Path
from string import Template


def load_prompt(prompt_dir, name):
    """从实验的 prompts 目录读取 prompt 文件。

    返回 string.Template；调用方负责填入占位符。缺少占位符时会抛出 KeyError，
    以便及时发现模板不一致。
    """
    return Template(Path(prompt_dir, name).read_text())
