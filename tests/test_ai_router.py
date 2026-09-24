"""app.ai.router のテスト: 階層 → モデル解決、環境変数上書き、コスト見積。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.ai import router  # noqa: E402


class PolicyTest(unittest.TestCase):
    def test_default_tiers_follow_cost_ladder(self):
        self.assertEqual(router.policy_for("listing_copy").tier, router.TIER_CHEAP)
        self.assertEqual(router.policy_for("category").tier, router.TIER_CHEAP)
        self.assertEqual(router.policy_for("judge").tier, router.TIER_STANDARD)
        self.assertEqual(router.policy_for("diagnose").tier, router.TIER_STANDARD)
        self.assertEqual(router.policy_for("weekly_review").tier, router.TIER_PREMIUM)

    def test_unknown_task_raises(self):
        with self.assertRaises(KeyError):
            router.policy_for("nope")

    def test_bulk_tasks_batch_multiple_items(self):
        self.assertGreater(router.policy_for("listing_copy").items_per_call, 1)
        self.assertGreater(router.policy_for("category").items_per_call, 1)
        self.assertEqual(router.policy_for("weekly_review").items_per_call, 1)

    def test_cheap_tier_has_no_effort(self):
        self.assertIsNone(router.policy_for("listing_copy").effort)

    def test_task_tier_env_override(self):
        with patch.dict(os.environ, {"AI_TASK_JUDGE_TIER": "cheap"}):
            self.assertEqual(router.policy_for("judge").tier, router.TIER_CHEAP)
        with patch.dict(os.environ, {"AI_TASK_JUDGE_TIER": "bogus"}):
            self.assertEqual(router.policy_for("judge").tier, router.TIER_STANDARD)


class ModelResolutionTest(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("AI_MODEL_CHEAP", "AI_MODEL_STANDARD", "AI_MODEL_PREMIUM"):
                os.environ.pop(k, None)
            self.assertEqual(router.resolve_model("cheap"), "claude-haiku-4-5")
            self.assertEqual(router.resolve_model("standard"), "claude-sonnet-5")
            self.assertEqual(router.resolve_model("premium"), "claude-fable-5-1")

    def test_env_override(self):
        with patch.dict(os.environ, {"AI_MODEL_PREMIUM": "claude-opus-5"}):
            self.assertEqual(router.resolve_model("premium"), "claude-opus-5")

    def test_unknown_tier_raises(self):
        with self.assertRaises(KeyError):
            router.resolve_model("ultra")

    def test_capability_helpers(self):
        self.assertFalse(router.supports_effort("claude-haiku-4-5"))
        self.assertTrue(router.supports_effort("claude-sonnet-5"))
        self.assertTrue(router.is_fable("claude-fable-5-1"))
        self.assertFalse(router.is_fable("claude-opus-5"))


class CostTest(unittest.TestCase):
    def test_estimate_cost_haiku(self):
        usd = router.estimate_cost_usd("claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0)
        self.assertAlmostEqual(usd, 1.0)
        usd = router.estimate_cost_usd("claude-haiku-4-5", output_tokens=1_000_000)
        self.assertAlmostEqual(usd, 5.0)

    def test_cache_read_is_cheaper_than_input(self):
        full = router.estimate_cost_usd("claude-sonnet-5", input_tokens=10_000)
        cached = router.estimate_cost_usd("claude-sonnet-5", cache_read_input_tokens=10_000)
        self.assertLess(cached, full)

    def test_unknown_model_uses_conservative_price(self):
        usd = router.estimate_cost_usd("claude-future-9", input_tokens=1_000_000)
        self.assertGreaterEqual(usd, 5.0)

    def test_usd_to_jpy_env(self):
        with patch.dict(os.environ, {"USD_TO_JPY": "150"}):
            self.assertAlmostEqual(router.usd_to_jpy(2.0), 300.0)

    def test_describe_policies_lists_every_task(self):
        rows = router.describe_policies()
        self.assertEqual({r["task"] for r in rows}, set(router.TASK_POLICIES))
        for r in rows:
            self.assertIn(r["tier"], router.TIERS)
            self.assertTrue(r["model"])


if __name__ == "__main__":
    unittest.main()
