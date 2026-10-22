"""演化框架各阶段使用的 OpenAI Chat Completions 接口封装。

SDK 从 OPENAI_API_KEY 环境变量读取 API key。
不重试、不回退，也不屏蔽错误：调用失败会继续向上抛出。
离线测试时，可注入一个提供
`client.chat.completions.create(...)` 接口的 fake `client`。
"""

from openai import OpenAI

from . import config

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(max_retries=0)
    return _client


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


def chat_json(messages, *, model=None, client=None, temperature=None):
    """调用 Chat Completion，预期返回 JSON 对象；解析后返回。"""
    import json

    content = chat(
        messages, model=model, client=client, json_mode=True, temperature=temperature
    )
    return json.loads(content)
