"""OpenAI chat-completion boundary for the framework stages.

API key is read by the SDK from the OPENAI_API_KEY environment variable.
No retries, fallbacks, or error swallowing: call failures propagate.
For offline tests, inject a fake `client` exposing
`client.chat.completions.create(...)`.
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
    """Single chat completion. `messages` is the OpenAI messages list.

    Returns the assistant message content as a string.
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
    """Chat completion expected to return a JSON object; parsed and returned."""
    import json

    content = chat(
        messages, model=model, client=client, json_mode=True, temperature=temperature
    )
    return json.loads(content)
