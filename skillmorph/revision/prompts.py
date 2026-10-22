"""Prompt template loading for the revision stage."""

from pathlib import Path
from string import Template


def load_prompt(prompt_dir, name):
    """Read a prompt file from the experiment's prompts directory.

    Returns a string.Template; callers fill its placeholders. A missing
    placeholder raises KeyError so template drift surfaces immediately.
    """
    return Template(Path(prompt_dir, name).read_text())
