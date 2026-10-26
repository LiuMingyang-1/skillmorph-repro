"""离线检查聊天和嵌入分别使用各自的供应商配置，以及 chat_json 的解析行为。"""

import json
from types import SimpleNamespace

import pytest

from skillmorph import config, llm
from skillmorph.abstraction import cluster_actions


class _FakeChatClient:
    """按顺序返回预设 content 的最小 fake 客户端。"""

    def __init__(self, *contents):
        self._contents = list(contents)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, model, messages, **kwargs):
        content = self._contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


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
         "api_key": settings["LLM_API_KEY"], "max_retries": 0, "timeout": 30.0},
        {"base_url": settings["EMBEDDING_BASE_URL"],
         "api_key": settings["EMBEDDING_API_KEY"], "max_retries": 0, "timeout": 30.0},
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


MESSAGES = [{"role": "user", "content": "reply with JSON"}]


@pytest.fixture(autouse=True)
def _reset_raw_dir():
    yield
    llm.set_raw_dir(None)


def test_chat_json_parses_plain_object():
    client = _FakeChatClient('{"a": 1}')
    assert llm.chat_json(MESSAGES, client=client) == {"a": 1}


def test_chat_json_invalid_escape_raises_and_saves_raw(tmp_path):
    bad = '{\n"change": "C:\\temp\\x"}'  # \t 合法，\x 非法
    client = _FakeChatClient(bad)
    llm.set_raw_dir(tmp_path)
    with pytest.raises(json.JSONDecodeError) as err:
        llm.chat_json(MESSAGES, client=client)
    with pytest.raises(json.JSONDecodeError) as original:
        json.loads(bad)
    assert err.value.pos == original.value.pos
    assert err.value.lineno == original.value.lineno
    assert err.value.colno == original.value.colno
    assert err.value.doc == bad
    assert "Invalid" in str(err.value)
    assert "saved to" in str(err.value)
    dumps = list(tmp_path.glob("response-*.txt"))
    assert len(dumps) == 1
    assert dumps[0].read_bytes() == bad.encode("utf-8")


def test_chat_json_invalid_escape_unrecoverable_without_raw_dir(tmp_path,
                                                               monkeypatch):
    # 即使落盘失败，也必须继续抛出原始解析错误。
    client = _FakeChatClient('{"a": "unterminated')
    monkeypatch.setenv("SKILLEMORPH_RAW_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(llm, "_save_raw_response", lambda content: None)
    with pytest.raises(json.JSONDecodeError, match="failed to parse"):
        llm.chat_json(MESSAGES, client=client)


def test_chat_json_none_content_raises():
    client = _FakeChatClient(None)
    with pytest.raises(ValueError, match="empty assistant content"):
        llm.chat_json(MESSAGES, client=client)


@pytest.mark.parametrize("body", [
    'Here you go:\n```json\n{"locations": []}\n```',
    '{"first": true}\n{"second": true}',
    '{"a": "}{ not a brace"}\nignored {"tail": true}',
])
def test_chat_json_rejects_wrappers_and_multiple_objects(body, tmp_path):
    llm.set_raw_dir(tmp_path)
    with pytest.raises(json.JSONDecodeError):
        llm.chat_json(MESSAGES, client=_FakeChatClient(body))
    dumps = list(tmp_path.glob("response-*.txt"))
    assert len(dumps) == 1
    assert dumps[0].read_bytes() == body.encode("utf-8")
