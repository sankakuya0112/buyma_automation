"""app.core.opportunity (期待値スコア) のユニットテスト (Phase 2d)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.opportunity import (
    BASE_SALE_PROBABILITY,
    MAX_PROBABILITY,
    MIN_PROBABILITY,
    DemandSignals,
    count_sizes,
    estimate_sale_probability,
    opportunity_score,
    price_edge_ratio,
)


class SellthroughTest(unittest.TestCase):
    def test_no_size_info_is_zero(self):
        self.assertEqual(DemandSignals().sellthrough, 0.0)

    def test_partial_sellthrough(self):
        # 5 サイズ中 2 サイズ残 → 消化率 0.6
        s = DemandSignals(source_total_sizes=5, source_available_sizes=2)
        self.assertAlmostEqual(s.sellthrough, 0.6)

    def test_all_available_is_zero(self):
        s = DemandSignals(source_total_sizes=3, source_available_sizes=3)
        self.assertEqual(s.sellthrough, 0.0)

    def test_clamped_when_available_exceeds_total(self):
        # HTML フォールバック抽出などでデータが矛盾しても 0-1 にクランプ
        s = DemandSignals(source_total_sizes=2, source_available_sizes=5)
        self.assertEqual(s.sellthrough, 0.0)


class SaleProbabilityTest(unittest.TestCase):
    def test_high_competition_base_exceeds_none(self):
        """高競合 = 需要実証済みなので基礎確率が競合ゼロより高い。"""
        p_high = estimate_sale_probability("high")
        p_none = estimate_sale_probability("none")
        self.assertGreater(p_high, p_none)

    def test_positive_edge_increases_probability(self):
        p0 = estimate_sale_probability("medium", price_edge_ratio=0.0)
        p1 = estimate_sale_probability("medium", price_edge_ratio=0.10)
        self.assertGreater(p1, p0)

    def test_negative_edge_decreases_probability(self):
        """相場より高い価格では確率が下がる。"""
        p0 = estimate_sale_probability("medium", price_edge_ratio=0.0)
        p1 = estimate_sale_probability("medium", price_edge_ratio=-0.10)
        self.assertLess(p1, p0)

    def test_sellthrough_boosts_probability(self):
        s = DemandSignals(source_total_sizes=4, source_available_sizes=1)
        p0 = estimate_sale_probability("low")
        p1 = estimate_sale_probability("low", signals=s)
        self.assertGreater(p1, p0)

    def test_wish_count_boosts_probability(self):
        s = DemandSignals(market_wish_total=50)
        p0 = estimate_sale_probability("medium")
        p1 = estimate_sale_probability("medium", signals=s)
        self.assertGreater(p1, p0)

    def test_probability_clamped(self):
        # 全シグナル最大でも上限を超えない
        s = DemandSignals(
            source_total_sizes=10, source_available_sizes=0,
            market_wish_total=10000,
        )
        p = estimate_sale_probability("high", price_edge_ratio=0.5, signals=s)
        self.assertLessEqual(p, MAX_PROBABILITY)
        # 大幅マイナス edge でも下限を割らない
        p2 = estimate_sale_probability("none", price_edge_ratio=-0.5)
        self.assertGreaterEqual(p2, MIN_PROBABILITY)

    def test_unknown_level_uses_fallback(self):
        p = estimate_sale_probability("nonsense_level")
        self.assertAlmostEqual(p, BASE_SALE_PROBABILITY["unknown"])


class OpportunityScoreTest(unittest.TestCase):
    def test_score_is_profit_times_probability(self):
        self.assertEqual(opportunity_score(40000, 0.10), 4000)

    def test_zero_or_negative_profit_is_zero(self):
        self.assertEqual(opportunity_score(0, 0.5), 0)
        self.assertEqual(opportunity_score(-5000, 0.5), 0)

    def test_proven_demand_with_edge_beats_unproven_big_margin(self):
        """設計意図の検証: 「需要実証 + 価格優位の中利益」が
        「需要未検証の大利益」より優先される。"""
        # 競合ゼロ・¥150k 利益 (BRUNELLO CUCINELLI バッグ的な商品)
        p_unproven = estimate_sale_probability("none", price_edge_ratio=0.0)
        ev_unproven = opportunity_score(150000, p_unproven)
        # 高競合・最安値圏・¥40k 利益 (定番人気商品を価格優位で出すケース)
        s = DemandSignals(source_total_sizes=5, source_available_sizes=2)
        p_proven = estimate_sale_probability("high", price_edge_ratio=0.15, signals=s)
        ev_proven = opportunity_score(40000, p_proven)
        self.assertGreater(ev_proven, ev_unproven)


class PriceEdgeRatioTest(unittest.TestCase):
    def test_normal_edge(self):
        # 相場 ¥100,000 / 売価 ¥90,000 → edge 10%
        self.assertAlmostEqual(price_edge_ratio(100000, 90000), 0.10)

    def test_negative_edge(self):
        self.assertAlmostEqual(price_edge_ratio(100000, 110000), -0.10)

    def test_missing_data_returns_zero(self):
        self.assertEqual(price_edge_ratio(None, 90000), 0.0)
        self.assertEqual(price_edge_ratio(100000, None), 0.0)
        self.assertEqual(price_edge_ratio("", ""), 0.0)


class CountSizesTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(count_sizes("36, 38, 40"), 3)

    def test_empty(self):
        self.assertEqual(count_sizes(""), 0)
        self.assertEqual(count_sizes(None), 0)

    def test_single(self):
        self.assertEqual(count_sizes("UNI"), 1)


if __name__ == "__main__":
    unittest.main()
