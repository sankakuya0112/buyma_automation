"""app.core.decision_gate (事前コミット判定基準) のユニットテスト。

判定マトリクス全経路 + Poisson 検定の境界を検証する。
"""

from __future__ import annotations

import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.decision_gate import (
    ACCESS_PER_WEEK_LOW,
    MIN_PUBLISHED,
    P0_MODEL_REJECT,
    evaluate_gate,
)
from app.core.first_sale import SprintCandidate

AS_OF = datetime(2026, 8, 1, 12, 0, 0)


def _published(p=0.10, days_ago=30.0, n=1):
    items = []
    for i in range(n):
        items.append(
            SprintCandidate(
                row_index=i + 1, title=f"item{i}", vendor="v",
                final_price_jpy=100000, expected_profit_jpy=20000,
                sale_probability=p, opportunity_score=2000,
                item_id=str(1000 + i),
                published_at=(AS_OF - timedelta(days=days_ago)).isoformat(),
            )
        )
    return items


class TestVerdictMatrix(unittest.TestCase):
    def test_sale_observed_wins_over_everything(self):
        v = evaluate_gate(_published(n=3), AS_OF, observed_sales=1)
        self.assertEqual(v.code, "SCALE_UP")
        # 較正係数 (実測/予測) が根拠に含まれる
        self.assertTrue(any("較正" in r for r in v.rationale))

    def test_collecting_when_too_few_published(self):
        v = evaluate_gate(_published(n=MIN_PUBLISHED - 1), AS_OF)
        self.assertEqual(v.code, "COLLECTING")

    def test_collecting_when_too_recent(self):
        v = evaluate_gate(_published(n=10, days_ago=2.0), AS_OF)
        self.assertEqual(v.code, "COLLECTING")

    def test_exposure_problem_when_access_low(self):
        low = [ACCESS_PER_WEEK_LOW - 3.0] * 10
        v = evaluate_gate(
            _published(n=10, days_ago=30), AS_OF,
            weekly_access=low, total_access=100, total_wish=0,
        )
        self.assertEqual(v.code, "EXPOSURE_PROBLEM")

    def test_conversion_problem_when_model_rejected_with_wish(self):
        # λ = 0.12 × (60/30) × 10 = 2.4 → exp(-2.4) ≈ 0.091 < 0.10
        items = _published(p=0.12, days_ago=60, n=10)
        v = evaluate_gate(
            items, AS_OF,
            weekly_access=[50.0] * 10, total_access=1000, total_wish=30,
        )
        self.assertEqual(v.code, "CONVERSION_PROBLEM")
        # wish 率 3% ≥ 2% → 「関心はあるのに買われない」経路
        self.assertTrue(any("価格" in a for a in v.actions))

    def test_conversion_problem_without_wish_targets_quality(self):
        items = _published(p=0.12, days_ago=60, n=10)
        v = evaluate_gate(
            items, AS_OF,
            weekly_access=[50.0] * 10, total_access=1000, total_wish=0,
        )
        self.assertEqual(v.code, "CONVERSION_PROBLEM")
        self.assertTrue(any("画像" in a for a in v.actions))

    def test_on_track_when_model_not_yet_falsified(self):
        # λ = 0.10 × (14/30) × 6 = 0.28 → exp(-0.28) ≈ 0.76 ≥ 0.10
        items = _published(p=0.10, days_ago=14, n=6)
        v = evaluate_gate(
            items, AS_OF,
            weekly_access=[20.0] * 6, total_access=200, total_wish=1,
        )
        self.assertEqual(v.code, "ON_TRACK_WAITING")
        self.assertIsNotNone(v.metrics["days_until_decisive"])

    def test_on_track_without_funnel_mentions_missing_data(self):
        items = _published(p=0.10, days_ago=14, n=6)
        v = evaluate_gate(items, AS_OF, weekly_access=None)
        self.assertEqual(v.code, "ON_TRACK_WAITING")
        self.assertTrue(any("funnel" in r for r in v.rationale))


class TestMetricsMath(unittest.TestCase):
    def test_p0_matches_poisson(self):
        items = _published(p=0.12, days_ago=60, n=10)
        v = evaluate_gate(items, AS_OF, weekly_access=[50.0] * 10,
                          total_access=1000, total_wish=30)
        lam = 0.12 * 2.0 * 10
        self.assertAlmostEqual(v.metrics["lambda"], round(lam, 3), places=3)
        self.assertAlmostEqual(
            v.metrics["p0_no_sales"], round(math.exp(-lam), 3), places=3
        )
        self.assertLess(v.metrics["p0_no_sales"], P0_MODEL_REJECT)

    def test_rule_of_three_upper_bound(self):
        # 10 商品 × 60 日 = 20 商品・月 → 上限 3/20 = 0.15
        items = _published(p=0.12, days_ago=60, n=10)
        v = evaluate_gate(items, AS_OF, weekly_access=[50.0] * 10,
                          total_access=1000, total_wish=30)
        self.assertAlmostEqual(v.metrics["rule_of_three_upper"], 0.15, places=3)

    def test_empty_published_is_collecting_with_lambda_zero(self):
        v = evaluate_gate([], AS_OF)
        self.assertEqual(v.code, "COLLECTING")
        self.assertEqual(v.metrics["lambda"], 0.0)
        self.assertEqual(v.metrics["p0_no_sales"], 1.0)


if __name__ == "__main__":
    unittest.main()
