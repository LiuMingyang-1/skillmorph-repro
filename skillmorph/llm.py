"""演化框架各阶段使用的 OpenAI Chat Completions 接口封装。

聊天和嵌入分别使用根目录 .env 中的 LLM_* 和 EMBEDDING_* 配置。
不重试、不回退，也不屏蔽错误：调用失败会继续向上抛出。
离线测试时，可注入一个提供
`client.chat.completions.create(...)` 接口的 fake `client`。
"""

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
            base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, max_retries=0
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


def chat_json(messages, *, model=None, client=None, temperature=None):
    """调用 Chat Completion，预期返回 JSON 对象；解析后返回。"""
    import json

    content = chat(
        messages, model=model, client=client, json_mode=True, temperature=temperature
    )
    return json.loads(content)
