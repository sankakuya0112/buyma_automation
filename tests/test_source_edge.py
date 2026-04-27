"""app.core.source_edge のユニットテスト (Phase 2c+ Milestone 1)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.source_edge import SourceEdgeStats, evaluate_source_edge


class TestSourceEdgeStatsProperties(unittest.TestCase):
    def test_edge_jpy_with_two_sources(self):
        edge = SourceEdgeStats(
            canonical_key="GUCCI_MARMONT_BAG",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=64818,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=71200,
            n_sources=2,
        )
        self.assertEqual(edge.edge_jpy, 6382)

    def test_edge_jpy_when_no_second(self):
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=50000,
            n_sources=1,
        )
        self.assertEqual(edge.edge_jpy, 0)

    def test_edge_pct(self):
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=100000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=110000,
            n_sources=2,
        )
        self.assertAlmostEqual(edge.edge_pct, 10.0)

    def test_edge_jpy_clamped_when_second_cheaper_than_cheapest(self):
        # データ異常: 2 番目の方が安い場合は 0 にクランプ
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=50000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=40000,
            n_sources=2,
        )
        self.assertEqual(edge.edge_jpy, 0)

    def test_to_dict_includes_derived(self):
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=100000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=120000,
            n_sources=2,
        )
        d = edge.to_dict()
        self.assertEqual(d["edge_jpy"], 20000)
        self.assertAlmostEqual(d["edge_pct"], 20.0)


class TestEvaluateSourceEdge(unittest.TestCase):
    def test_none_returns_exclusive(self):
        action, reason = evaluate_source_edge(None, final_price_jpy=100000)
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "exclusive_source")

    def test_single_source_returns_exclusive(self):
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=50000,
            n_sources=1,
        )
        action, reason = evaluate_source_edge(edge, final_price_jpy=100000)
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "exclusive_source")

    def test_high_edge_returns_pass(self):
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=50000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=70000,  # +20000
            n_sources=2,
        )
        action, reason = evaluate_source_edge(
            edge, final_price_jpy=100000, current_source="baseblu",
        )
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "high_source_edge")

    def test_low_edge_returns_warn(self):
        # edge=3000, threshold=max(10000, 100000×5%=5000)=10000 → warn
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=50000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=53000,
            n_sources=2,
        )
        action, reason = evaluate_source_edge(
            edge, final_price_jpy=100000, current_source="baseblu",
        )
        self.assertEqual(action, "warn")
        self.assertEqual(reason, "low_source_edge")

    def test_not_cheapest_source_returns_skip(self):
        # current_source が cheapest と異なる
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="italist",
            cheapest_landed_cost_jpy=50000,
            second_cheapest_source="baseblu",
            second_cheapest_landed_cost_jpy=70000,
            n_sources=2,
        )
        action, reason = evaluate_source_edge(
            edge, final_price_jpy=100000, current_source="baseblu",
        )
        self.assertEqual(action, "skip")
        self.assertEqual(reason, "not_cheapest_source")

    def test_threshold_uses_max_of_absolute_and_ratio(self):
        # final 高額: ratio (5%) 側がしばり
        # final=400000 → threshold=max(10000, 20000)=20000
        edge_above = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=200000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=225000,  # +25000
            n_sources=2,
        )
        a1, r1 = evaluate_source_edge(
            edge_above, final_price_jpy=400000, current_source="baseblu",
        )
        self.assertEqual(a1, "pass")
        self.assertEqual(r1, "high_source_edge")

        edge_below = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="baseblu",
            cheapest_landed_cost_jpy=200000,
            second_cheapest_source="italist",
            second_cheapest_landed_cost_jpy=215000,  # +15000 < 20000 (5%)
            n_sources=2,
        )
        a2, r2 = evaluate_source_edge(
            edge_below, final_price_jpy=400000, current_source="baseblu",
        )
        self.assertEqual(a2, "warn")
        self.assertEqual(r2, "low_source_edge")

    def test_current_source_unset_skips_not_cheapest_check(self):
        # current_source 未指定 → not_cheapest_source 判定をスキップ、edge ベース判定のみ
        edge = SourceEdgeStats(
            canonical_key="X",
            cheapest_source="italist",
            cheapest_landed_cost_jpy=50000,
            second_cheapest_source="baseblu",
            second_cheapest_landed_cost_jpy=70000,
            n_sources=2,
        )
        action, reason = evaluate_source_edge(edge, final_price_jpy=100000)
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "high_source_edge")


if __name__ == "__main__":
    unittest.main()
