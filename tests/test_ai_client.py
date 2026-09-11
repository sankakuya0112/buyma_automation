"""app.ai.client のテスト: オフライン退避・キャッシュ・台帳・予算・エラー処理 (SDK はフェイク)。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from app.ai import client as client_mod  # noqa: E402
from app.ai.client import AIClient, DiskCache, UsageLedger, parse_json_lenient, rough_token_count  # noqa: E402
from _ai_fakes import AuthenticationError, BadRequestError, FakeResponse, FakeSDK  # noqa: E402

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}


def _tmp_ledger() -> UsageLedger:
    return UsageLedger(Path(tempfile.mkdtemp()) / "usage.jsonl")


def _client(sdk=None, **kw) -> AIClient:
    kw.setdefault("cache", DiskCache(":memory:"))
    kw.setdefault("ledger", _tmp_ledger())
    kw.setdefault("quiet", True)
    if sdk is not None:
        kw.setdefault("api_key", "test-key")
        return AIClient(sdk_client=sdk, **kw)
    return AIClient(**kw)


class ParseTest(unittest.TestCase):
    def test_plain_and_fenced_and_wrapped(self):
        self.assertEqual(parse_json_lenient('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json_lenient('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json_lenient('結果: {"a": [1, 2]} 以上'), {"a": [1, 2]})
        self.assertIsNone(parse_json_lenient("no json here"))
        self.assertIsNone(parse_json_lenient(""))

    def test_rough_token_count(self):
        self.assertEqual(rough_token_count(""), 0)
        self.assertGreater(rough_token_count("日本語のテキスト"), rough_token_count("abcd"))


class CacheLedgerTest(unittest.TestCase):
    def test_disk_cache_roundtrip(self):
        c = DiskCache(":memory:")
        self.assertIsNone(c.get("k"))
        c.set("k", "t", "m", {"x": 1})
        self.assertEqual(c.get("k"), {"x": 1})
        self.assertEqual(c.count(), 1)
        self.assertEqual(c.count("t"), 1)
        self.assertEqual(c.clear("t"), 1)
        self.assertEqual(c.count(), 0)

    def test_ledger_spent_and_summary_respect_days(self):
        ledger = _tmp_ledger()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        ledger.record({"task": "judge", "model": "m", "cost_usd": 1.0, "cost_jpy": 160.0, "ts": old_ts})
        ledger.record({"task": "judge", "model": "m", "cost_usd": 0.5, "cost_jpy": 80.0, "input_tokens": 10})
        ledger.record({"task": "category", "model": "m", "cached": True, "cost_usd": 0.0, "cost_jpy": 0.0})
        self.assertAlmostEqual(ledger.spent_jpy(7), 80.0)
        self.assertAlmostEqual(ledger.spent_jpy(60), 240.0)
        s = ledger.summarize(7)
        self.assertEqual(s["calls"], 2)
        self.assertEqual(s["cached_calls"], 1)
        self.assertIn("judge", s["by_task"])
        self.assertEqual(s["by_task"]["judge"]["input_tokens"], 10)


class OfflineTest(unittest.TestCase):
    def test_no_api_key_means_unavailable_and_none(self):
        c = _client(api_key="")
        self.assertFalse(c.available)
        self.assertIn("ANTHROPIC_API_KEY", c.why_unavailable())
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertIsNone(c.complete_text("weekly_review", "s", "u"))

    def test_ai_disabled_env(self):
        with patch.dict(os.environ, {"AI_DISABLED": "1", "ANTHROPIC_API_KEY": "x"}):
            c = _client()
        self.assertFalse(c.available)
        self.assertEqual(c.why_unavailable(), "AI_DISABLED=1")

    def test_explicit_enabled_false(self):
        c = _client(FakeSDK([FakeResponse({"a": 1})]), enabled=False)
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))


class OnlineFakeSDKTest(unittest.TestCase):
    def test_json_roundtrip_records_ledger_and_caches(self):
        sdk = FakeSDK([FakeResponse({"a": 7})])
        c = _client(sdk)
        self.assertTrue(c.available)
        self.assertEqual(c.complete_json("category", "sys", "usr", SCHEMA), {"a": 7})
        # 2 回目は SDK を呼ばずキャッシュから
        self.assertEqual(c.complete_json("category", "sys", "usr", SCHEMA), {"a": 7})
        self.assertEqual(len(sdk.messages.calls), 1)
        entries = c.ledger.entries()
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[0]["cached"])
        self.assertGreater(entries[0]["cost_usd"], 0)
        self.assertTrue(entries[1]["cached"])
        self.assertEqual(c.session_summary()["calls"], 1)
        self.assertEqual(c.session_summary()["cache_hits"], 1)

    def test_request_shape_for_cheap_tier(self):
        sdk = FakeSDK([FakeResponse({"a": 1})])
        c = _client(sdk)
        c.complete_json("category", "sys", "usr", SCHEMA)
        kw = sdk.messages.calls[0]
        self.assertEqual(kw["model"], "claude-haiku-4-5")
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("effort", kw["output_config"])            # Haiku は effort 非対応
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(kw["messages"][0]["content"], "usr")

    def test_request_shape_for_standard_tier_has_effort(self):
        sdk = FakeSDK([FakeResponse({"a": 1}, model="claude-sonnet-5")])
        c = _client(sdk)
        c.complete_json("judge", "sys", "usr", SCHEMA)
        kw = sdk.messages.calls[0]
        self.assertEqual(kw["model"], "claude-sonnet-5")
        self.assertEqual(kw["output_config"]["effort"], "medium")

    def test_fable_uses_beta_with_server_side_fallback(self):
        sdk = FakeSDK(beta_responses=[FakeResponse("メモ本文", model="claude-fable-5-1", as_text=True)])
        c = _client(sdk)
        self.assertEqual(c.complete_text("weekly_review", "sys", "usr"), "メモ本文")
        self.assertEqual(len(sdk.messages.calls), 0)
        kw = sdk.beta.messages.calls[0]
        self.assertEqual(kw["model"], "claude-fable-5-1")
        self.assertEqual(kw["betas"], [client_mod.FABLE_FALLBACK_BETA])
        self.assertEqual(kw["fallbacks"], "default")
        self.assertNotIn("thinking", kw)                            # Fable は thinking 常時 ON (指定不可)
        self.assertEqual(kw["output_config"]["effort"], "high")
        self.assertNotIn("format", kw["output_config"])

    def test_cost_uses_served_model_when_fallback_happened(self):
        sdk = FakeSDK(beta_responses=[FakeResponse("x", model="claude-opus-4-8", as_text=True)])
        c = _client(sdk)
        c.complete_text("weekly_review", "s", "u")
        e = c.ledger.entries()[0]
        self.assertEqual(e["model"], "claude-opus-4-8")
        self.assertEqual(e["requested_model"], "claude-fable-5-1")

    def test_budget_exceeded_returns_none(self):
        ledger = _tmp_ledger()
        ledger.record({"task": "judge", "model": "m", "cost_usd": 10.0, "cost_jpy": 1600.0})
        sdk = FakeSDK([FakeResponse({"a": 1})])
        c = _client(sdk, ledger=ledger, weekly_budget_jpy=500)
        self.assertFalse(c.available)
        self.assertIn("予算", c.why_unavailable())
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertEqual(len(sdk.messages.calls), 0)

    def test_refusal_returns_none_but_is_recorded(self):
        sdk = FakeSDK([FakeResponse({"a": 1}, stop_reason="refusal")])
        c = _client(sdk)
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertEqual(c.ledger.entries()[0]["stop_reason"], "refusal")
        self.assertEqual(c.cache.count(), 0)

    def test_invalid_json_returns_none_not_cached(self):
        sdk = FakeSDK([FakeResponse("not json", as_text=True)])
        c = _client(sdk)
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertEqual(c.cache.count(), 0)

    def test_structured_output_unsupported_falls_back_to_json_instruction(self):
        sdk = FakeSDK([BadRequestError("output_config.format is not supported"), FakeResponse({"a": 3})])
        c = _client(sdk)
        self.assertEqual(c.complete_json("category", "s", "u", SCHEMA), {"a": 3})
        first, second = sdk.messages.calls
        self.assertIn("format", first["output_config"])
        self.assertNotIn("output_config", second)
        self.assertIn("JSON", second["messages"][0]["content"])

    def test_auth_error_disables_client(self):
        sdk = FakeSDK([AuthenticationError("bad key")])
        c = _client(sdk)
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertFalse(c.enabled)
        self.assertIn("認証", c.why_unavailable())

    def test_generic_error_returns_none(self):
        sdk = FakeSDK([RuntimeError("boom")])
        c = _client(sdk)
        self.assertIsNone(c.complete_json("category", "s", "u", SCHEMA))
        self.assertTrue(c.enabled)

    def test_cache_key_depends_on_model_and_inputs(self):
        k1 = AIClient._cache_key("t", "m1", "s", "u", SCHEMA)
        k2 = AIClient._cache_key("t", "m2", "s", "u", SCHEMA)
        k3 = AIClient._cache_key("t", "m1", "s", "u2", SCHEMA)
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertEqual(k1, AIClient._cache_key("t", "m1", "s", "u", json.loads(json.dumps(SCHEMA))))


if __name__ == "__main__":
    unittest.main()
