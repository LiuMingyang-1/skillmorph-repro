"""离线检查聊天和嵌入分别使用各自的供应商配置。"""

from types import SimpleNamespace

import pytest

from skillmorph import config, llm
from skillmorph.abstraction import cluster_actions


def test_chat_and_embeddings_use_separate_providers(monkeypatch):
    clients, requests = [], []

    def make_client(**kwargs):
        clients.append(kwargs)

        def chat(**request):
            requests.append(request)
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content="ok"))
            ])

        def embed(**request):
            requests.append(request)
            return SimpleNamespace(data=[
                SimpleNamespace(embedding=[1.0, 0.0]),
                SimpleNamespace(embedding=[0.0, 1.0]),
            ])

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=chat)),
            embeddings=SimpleNamespace(create=embed),
        )

    monkeypatch.setattr(llm, "OpenAI", make_client)
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "_embedding_client", None)
    settings = {
        "LLM_BASE_URL": "https://chat.example/v1",
        "LLM_API_KEY": "test-chat-key",
        "MODEL": "test-chat-model",
        "EMBEDDING_BASE_URL": "https://embedding.example/v1",
        "EMBEDDING_API_KEY": "test-embedding-key",
        "EMBEDDING_MODEL": "test-embedding-model",
    }
    for name, value in settings.items():
        monkeypatch.setattr(config, name, value)

    assert llm.chat([{"role": "user", "content": "hello"}]) == "ok"
    cluster_actions([{"transitions": [{"action": "a"}, {"action": "b"}]}])

    assert clients == [
        {"base_url": settings["LLM_BASE_URL"],
         "api_key": settings["LLM_API_KEY"], "max_retries": 0},
        {"base_url": settings["EMBEDDING_BASE_URL"],
         "api_key": settings["EMBEDDING_API_KEY"], "max_retries": 0},
    ]
    assert requests[0]["model"] == "test-chat-model"
    assert requests[1]["model"] == "test-embedding-model"
    assert requests[1]["input"] == ["a", "b"]


@pytest.mark.parametrize("getter,cache,key", [
    (llm.get_client, "_client", "LLM_API_KEY"),
    (llm.get_embedding_client, "_embedding_client", "EMBEDDING_API_KEY"),
])
def test_missing_key_raises(monkeypatch, getter, cache, key):
    monkeypatch.setattr(llm, cache, None)
    monkeypatch.setattr(config, key, "")
    with pytest.raises(ValueError, match=key):
        getter()
