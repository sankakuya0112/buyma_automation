"""AI テスト共通のフェイク SDK (anthropic 非依存)。"""

from __future__ import annotations

import json
from types import SimpleNamespace


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50, cache_creation=0, cache_read=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation
        self.cache_read_input_tokens = cache_read


class FakeResponse:
    def __init__(self, payload, *, stop_reason="end_turn", model="claude-haiku-4-5", usage=None, as_text=False):
        text = payload if (as_text or isinstance(payload, str)) else json.dumps(payload, ensure_ascii=False)
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop_reason
        self.stop_details = SimpleNamespace(category="cyber") if stop_reason == "refusal" else None
        self.model = model
        self.usage = usage or FakeUsage()


class FakeMessages:
    """create(**kwargs) を記録し、キューから応答を返す (関数なら呼ぶ)。"""

    def __init__(self, responses=None):
        self.calls: list[dict] = []
        self.responses = list(responses or [])

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeMessages: no more responses queued")
        r = self.responses.pop(0)
        if callable(r):
            r = r(kwargs)
        if isinstance(r, Exception):
            raise r
        return r


class FakeSDK:
    def __init__(self, responses=None, beta_responses=None):
        self.messages = FakeMessages(responses)
        self.beta = SimpleNamespace(messages=FakeMessages(beta_responses))


class BadRequestError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


class ScriptedClient:
    """AIClient の代替: task ごとに固定の応答を返す (タスク層のテスト用)。"""

    def __init__(self, responses: dict | None = None, available: bool = True):
        self.responses = responses or {}
        self.available = available
        self.calls: list[tuple[str, str, str, dict | None]] = []

    def complete_json(self, task, system, user, schema):
        self.calls.append((task, system, user, schema))
        r = self.responses.get(task)
        return r(user) if callable(r) else r

    def complete_text(self, task, system, user):
        self.calls.append((task, system, user, None))
        r = self.responses.get(task)
        return r(user) if callable(r) else r
