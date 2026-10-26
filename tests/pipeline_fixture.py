"""流水线离线测试共用的夹具：fake 客户端和示例数据。

夹具场景：两个任务都执行了“再打开一个内存 sqlite 连接”这一动作。该动作出现在
两次失败运行中，也出现在一次成功运行中；预设判断将其标记为引入错误，因此它是
可疑动作。其他动作则在不同运行中同时出现正常和异常情况。这里的所有 LLM 回复
均为脚本预设，用来验证调用链路，不代表真实模型会作出相同判断。
"""

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

PROMPTS = Path(__file__).resolve().parent.parent / "experiments/exp_001/prompts"

SKILL_MD = "# sqlite-memory\n\nUse sqlite :memory: databases for tests.\n"
DB_MD = (
    "# Connections\n\n"
    "Line about imports.\n"
    "Line about queries.\n"
    "Open a new connection per operation.\n"   # 对应有问题的规则（第 4 行）。
)
NEW_DB_MD = (
    "# Connections\n\n"
    "Line about imports.\n"
    "Line about queries.\n"
    "Share ONE in-memory connection for imports and queries; each\n"
    "':memory:' database is private to its connection.\n"
)


def _embedded_json(text):
    """提取替换后 prompt 中嵌入的 JSON 数据。"""
    for marker in ('{"proposals"', '{"action_id"'):
        i = text.find(marker)
        if i >= 0:
            return json.JSONDecoder().raw_decode(text[i:])[0]
    raise AssertionError("no embedded JSON payload in prompt")


class FakePipelineClient:
    """根据 prompt 标记路由每次 chat 调用；按顺序提供预设的抽象结果，
    其他数据均从请求内容中生成。
    """

    def __init__(self, abstractions):
        self._abstract = list(abstractions)
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._chat)
        )
        self.embeddings = SimpleNamespace(create=self._embed)

    @staticmethod
    def _reply(payload):
        msg = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    def _chat(self, model, messages, **kwargs):
        text = "\n".join(m["content"] for m in messages)
        self.requests.append(text)
        if "abstract one agent execution" in text:
            return self._reply(self._abstract.pop(0))
        if "Judge the action at step" in text:
            action = re.search(
                r'Judge the action at step \d+: "(.*)"', text
            ).group(1)
            # 预设的判断结果：只有打开第二个 :memory: 连接这一动作被
            # 标记为引入错误；查询该连接只是暴露了它生成的空
            # 数据库。
            err = action in (
                "open second in-memory connection",
                "open a second in-memory connection",
            )
            return self._reply({"introduces_error": err, "reason": "fake"})
        if "Mode: artifacts" in text:
            payload = _embedded_json(text)
            # 只有第二次连接相关的动作可疑：测试将问题归因于 Skill 中
            # 有缺陷的“每次操作都新建连接”规则。
            locs = (
                [{"skill": "sqlite-memory",
                  "artifact": "reference/connections.md"}]
                if "second" in payload["action_text"]
                else []
            )
            return self._reply({"locations": locs, "rationale": "fake"})
        if "Mode: lines" in text:
            return self._reply({
                "locations": [{"skill": "sqlite-memory",
                               "artifact": "reference/connections.md",
                               "lines": [4, 4]}],
                "rationale": "per-operation connection rule splits the DB",
            })
        if "writing a revision proposal" in text:
            return self._reply({
                "edits": [{"skill": "sqlite-memory",
                           "artifact": "reference/connections.md",
                           "lines": [4, 4],
                           "change": "share one in-memory connection"}],
                "rationale": "fake",
            })
        if "evaluating revision proposals" in text:
            ctx = _embedded_json(text)
            return self._reply({
                "selected": [p["action_id"] for p in ctx["proposals"]],
                "rejected": [],
                "files": [{"skill": "sqlite-memory",
                           "artifact": "reference/connections.md",
                           "content": NEW_DB_MD}],
            })
        raise AssertionError(f"unexpected LLM call: {text[:120]}")

    def _embed(self, model, input):
        # 一对同义文本共用一个固定向量轴（余弦距离为 0，因此归入同一
        # 聚类）；其他文本使用彼此正交的向量轴（距离为 1）。
        data = []
        for i, text in enumerate(input):
            vec = [0.0] * (len(input) + 1)
            vec[-1 if text in ("open second in-memory connection",
                               "open a second in-memory connection")
               else i] = 1.0
            data.append(SimpleNamespace(embedding=vec))
        return SimpleNamespace(data=data)


def _steps(*actions):
    steps = [
        {"action": "read sqlite-memory skill",
         "skills_used": ["sqlite-memory"],
         "files_read": ["sqlite-memory/SKILL.md"]}
    ]
    steps += [
        {"action": a, "observation": obs,
         "skills_used": [], "files_read": []}
        for a, obs in actions
    ]
    return steps


def _tr(source_steps, action, before, after):
    return {
        "state_before": before, "action": action,
        "state_after": after, "source_steps": source_steps,
    }


RUNS = [
    {"task_id": "t1", "run_id": "r1", "task": "doc store", "outcome": "fail",
     "steps": _steps(
         ("conn A: create documents, insert rows", "ok"),
         ("conn B = connect(':memory:')", "ok"),
         ("conn B: select from documents", "no such table: documents"))},
    {"task_id": "t1", "run_id": "r2", "task": "doc store", "outcome": "success",
     "steps": _steps(
         ("conn A: create documents, insert rows", "ok"),
         ("conn A: select from documents", "rows returned"))},
    {"task_id": "t2", "run_id": "r1", "task": "session store", "outcome": "fail",
     "steps": _steps(
         ("conn A: create users", "ok"),
         ("conn B = connect(':memory:'); insert via conn B", "ok"),
         ("conn A: select from users", "no such table: users"))},
    {"task_id": "t2", "run_id": "r2", "task": "session store",
     "outcome": "success",
     "steps": _steps(
         ("conn A: create users", "ok"),
         ("conn B = connect(':memory:') for scratch", "ok"),
         ("conn B: select from users", "no such table: users"),
         ("conn A: select from users", "rows returned"))},
]

# 抽象阶段的回复按运行顺序排列；每个原始步骤恰好覆盖一次。
ABSTRACTIONS = [
    {"transitions": [
        _tr([0, 1], "create table documents via connection A",
            "skill consulted", "documents created in conn A"),
        _tr([2], "open second in-memory connection",
            "documents in conn A", "conn B opened"),
        _tr([3], "query documents via the second connection",
            "conn B opened", "no such table: documents"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table documents via connection A",
            "skill consulted", "documents created in conn A"),
        _tr([2], "query documents via the first connection",
            "documents in conn A", "rows returned"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table users via connection A",
            "skill consulted", "users created in conn A"),
        _tr([2], "open a second in-memory connection",
            "users in conn A", "conn B opened"),
        _tr([3], "query users via the first connection",
            "conn B opened", "no such table: users"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table users via connection A",
            "skill consulted", "users created in conn A"),
        _tr([2], "open a second in-memory connection",
            "users in conn A", "conn B opened"),
        _tr([3], "query users via the second connection",
            "conn B opened", "no such table: users"),
        _tr([4], "query users via the first connection",
            "conn B empty", "rows returned"),
    ]},
]

# 全部成功且无需修改的测试输入。
RUNS_ALL_SUCCESS = [
    {"task_id": "t1", "run_id": "r1", "task": "doc store",
     "outcome": "success",
     "steps": _steps(("conn A: create documents", "ok"),
                     ("conn A: select", "rows"))},
    {"task_id": "t1", "run_id": "r2", "task": "doc store",
     "outcome": "success",
     "steps": _steps(("conn A: create documents", "ok"),
                     ("conn A: select", "rows"))},
]
ABSTRACTIONS_ALL_SUCCESS = [
    {"transitions": [
        _tr([0, 1], "create table documents via connection A", "s", "t"),
        _tr([2], "query documents via the first connection", "t", "u"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table documents via connection A", "s", "t"),
        _tr([2], "query documents via the first connection", "t", "u"),
    ]},
]


def make_experiment(tmp_path, runs):
    """创建最简实验目录：包含数据、复制的 prompt 和一个 Skill。"""
    exp = tmp_path / "exp"
    (exp / "data").mkdir(parents=True)
    (exp / "data" / "trajectories.json").write_text(json.dumps(runs))
    shutil.copytree(PROMPTS, exp / "prompts")
    ref = exp / "skills" / "sqlite-memory" / "reference"
    ref.mkdir(parents=True)
    (exp / "skills" / "sqlite-memory" / "SKILL.md").write_text(SKILL_MD)
    (ref / "connections.md").write_text(DB_MD)
    return exp


def tree_snapshot(root):
    """返回 root 下所有文件的 {relative_path: content}。"""
    root = Path(root)
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in root.rglob("*") if p.is_file()
    }
