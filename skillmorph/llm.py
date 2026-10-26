"""演化框架各阶段使用的 OpenAI Chat Completions 接口封装。

聊天和嵌入分别使用根目录 .env 中的 LLM_* 和 EMBEDDING_* 配置。
不重试、不回退，也不屏蔽错误：调用失败会继续向上抛出。
离线测试时，可注入一个提供
`client.chat.completions.create(...)` 接口的 fake `client`。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from openai import OpenAI

from . import config

_client = None
_embedding_client = None


def get_client():
    global _client
    if _client is None:
        if not config.LLM_API_KEY:
            raise ValueError("请在根目录 .env 中填写 LLM_API_KEY")
        _client = OpenAI(
            base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
            max_retries=0, timeout=30.0,
        )
    return _client


def get_embedding_client():
    global _embedding_client
    if _embedding_client is None:
        if not config.EMBEDDING_API_KEY:
            raise ValueError("请在根目录 .env 中填写 EMBEDDING_API_KEY")
        _embedding_client = OpenAI(
            base_url=config.EMBEDDING_BASE_URL,
            api_key=config.EMBEDDING_API_KEY,
            max_retries=0,
            timeout=30.0,
        )
    return _embedding_client


def chat(messages, *, model=None, client=None, json_mode=False, temperature=None):
    """执行一次 Chat Completion。`messages` 是 OpenAI 格式的消息列表。

    返回字符串形式的 assistant 消息内容。
    """
    client = client or get_client()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=model or config.MODEL,
        messages=messages,
        temperature=config.TEMPERATURE if temperature is None else temperature,
        max_tokens=config.MAX_TOKENS,
        **kwargs,
    )
    return response.choices[0].message.content


# 保存 chat_json 解析失败的原始模型回复的目录。
# 默认 None 表示使用 ``tempfile.gettempdir()/skillmorph-bad-json``（每次调用时
# 重新解析，避免跨平台缓存错误路径）；也可用环境变量
# SKILLEMORPH_RAW_DIR 覆盖；设置 ``set_raw_dir()`` 可将回复随产物保存在轮次目录下。
# 文件只写模型回复，不额外写入请求或客户端配置；模型回显的内容会原样保留。
# POSIX 上尽量限制为属主可读，Windows 沿用目录 ACL。
_raw_dir = None


def set_raw_dir(path) -> None:
    """设置保存失败模型回复的目录；None 恢复临时目录默认行为。"""
    global _raw_dir
    _raw_dir = Path(path) if path is not None else None


def _raw_dir_default() -> Path:
    return Path(os.environ.get("SKILLEMORPH_RAW_DIR") or
                Path(tempfile.gettempdir()) / "skillmorph-bad-json")


def _save_raw_response(content) -> Path | None:
    """尽力将模型原文写入 raw_dir 下的唯一文件；失败时返回 None，不抛出。"""
    if content is None:
        return None
    directory = _raw_dir if _raw_dir is not None else _raw_dir_default()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            dir=str(directory), prefix="response-", suffix=".txt"
        )
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        try:
            os.chmod(name, 0o600)  # POSIX 上限制为属主；Windows 上为无操作。
        except OSError:
            pass
        return Path(name)
    except OSError as exc:
        print(f"skillmorph: could not save raw model response: {exc}",
              file=sys.stderr)
        return None


def chat_json(messages, *, model=None, client=None, temperature=None):
    """Parse the complete response strictly; preserve raw output and error location."""
    content = chat(
        messages, model=model, client=client, json_mode=True, temperature=temperature
    )
    if content is None:
        raise ValueError(
            "chat_json got empty assistant content (None); nothing was parsed"
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        saved = _save_raw_response(content)
        detail = (
            f"chat_json failed to parse model response as JSON: {exc.msg}"
            + (f"; raw response saved to {saved}" if saved else "")
        )
        raise json.JSONDecodeError(detail, content, exc.pos) from exc
