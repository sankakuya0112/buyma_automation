"""
app.core.pricing のユニットテスト。

PROFIT_FIRST タスク 1-1 の完了条件：
「ユニットテストでいくつかのパターンで検算が通る」を満たす。
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import (
    BUYMA_COMMISSION_RATE,
    DEFAULT_DUTY_RATE,
    DEFAULT_EXCHANGE_RATES,
    DEFAULT_WEIGHT,
    HIGH_COMPETITION_THRESHOLD,
    LOW_COMPETITION_THRESHOLD,
    MarketStats,
    PAYMENT_COMMISSION_RATE,
    PricingParams,
    PricingResult,
    UNRELIABLE_MARKET_COST_RATIO,
    calculate_pricing,
    decide_final_price,
    resolve_duty_rate,
    resolve_exchange_rate,
    resolve_weight,
)


class TestDutyRateResolution(unittest.TestCase):
    """resolve_duty_rate の動作確認。"""

    def test_exact_match(self):
        self.assertEqual(resolve_duty_rate("dress"), 0.091)
        self.assertEqual(resolve_duty_rate("sweater"), 0.109)
        self.assertEqual(resolve_duty_rate("bag"), 0.08)

    def test_case_insensitive(self):
        self.assertEqual(resolve_duty_rate("DRESS"), 0.091)
        self.assertEqual(resolve_duty_rate("Dress"), 0.091)

    def test_partial_match(self):
        # "leather bag" は "bag" にマッチ
        self.assertEqual(resolve_duty_rate("leather bag"), 0.08)

    def test_unknown_category_fallback(self):
        self.assertEqual(resolve_duty_rate("mystery_category_xyz"), DEFAULT_DUTY_RATE)

    def test_empty_category(self):
        self.assertEqual(resolve_duty_rate(""), DEFAULT_DUTY_RATE)


class TestWeightResolution(unittest.TestCase):
    """resolve_weight の動作確認。"""

    def test_exact_match(self):
        self.assertEqual(resolve_weight("bag"), 1.2)
        self.assertEqual(resolve_weight("coat"), 1.8)
        self.assertEqual(resolve_weight("wallet"), 0.3)

    def test_unknown_fallback(self):
        self.assertEqual(resolve_weight("ghost_category"), DEFAULT_WEIGHT)


class TestExchangeRateResolution(unittest.TestCase):
    def test_known_currencies(self):
        self.assertAlmostEqual(resolve_exchange_rate("EUR"), 186.0)
        self.assertAlmostEqual(resolve_exchange_rate("USD"), 160.0)
        self.assertAlmostEqual(resolve_exchange_rate("GBP"), 210.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(resolve_exchange_rate("eur"), 186.0)


class TestCalculatePricing(unittest.TestCase):
    """メインの計算関数の網羅テスト。"""

    def test_basic_eur_dress(self):
        """典型ケース: EUR 100 のドレス。"""
        params = PricingParams(source_price=100.0, currency="EUR", category="dress")
        r = calculate_pricing(params)

        # 販売価格は 100 円単位で切上
        self.assertEqual(r.selling_price_jpy % 100, 0)
        self.assertGreater(r.selling_price_jpy, 0)

        # 為替は EUR のデフォルト
        self.assertAlmostEqual(r.exchange_rate, 186.0)

        # 関税率はドレスのマスタ値
        self.assertAlmostEqual(r.duty_rate, 0.091)

        # 利益は正
        self.assertGreater(r.profit_jpy, 0)

        # 利益率は目標以上（切上分で多少超える）
        self.assertGreaterEqual(r.margin_pct, 25.0 * 0.95)  # 5%の許容

    def test_vat_refund_calculation(self):
        """VAT 還付額が source の 16.7% と等しい。"""
        params = PricingParams(source_price=100.0, currency="EUR", category="bag")
        r = calculate_pricing(params)
        expected = 100.0 * 186.0 * 0.167
        self.assertAlmostEqual(r.vat_refund_jpy, expected, places=1)

    def test_shipping_from_weight(self):
        """shipping_jpy 未指定時は 重量 × 単価 で計算される。"""
        params = PricingParams(source_price=100.0, currency="EUR", category="bag")
        r = calculate_pricing(params)
        # bag の重量は 1.2kg、単価 3000円/kg
        self.assertAlmostEqual(r.shipping_jpy, 1.2 * 3000.0)
        self.assertAlmostEqual(r.weight_kg, 1.2)

    def test_shipping_override(self):
        """shipping_jpy を直接指定できる。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="bag",
            shipping_jpy=2500.0,
        )
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.shipping_jpy, 2500.0)

    def test_formula_without_fees_and_margin(self):
        """手数料も利益率もゼロにすると、売価 ≈ 総原価。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="bag",
            vat_refund_rate=0.0,
            target_margin_pct=0.0,
            buyma_commission_rate=0.0,
            payment_commission_rate=0.0,
        )
        r = calculate_pricing(params)

        # 手計算 (EUR=186):
        #   net_source = 100 * 186 = 18600
        #   shipping   = 1.2 * 3000 = 3600
        #   customs    = (18600 + 3600) * 0.08 = 1776
        #   consumption = (18600 + 3600 + 1776) * 0.10 = 2397.6
        #   total      = 18600 + 3600 + 1776 + 2397.6 = 26373.6
        #   ※ pricing.py では追加マージン分を加算するため selling = 26800
        self.assertEqual(r.selling_price_jpy, 26800)

    def test_margin_target_reached(self):
        """target_margin_pct 以上の利益率が確保される。"""
        for margin in [0.20, 0.25, 0.30, 0.50]:
            params = PricingParams(
                source_price=150.0,
                currency="EUR",
                category="coat",
                target_margin_pct=margin,
            )
            r = calculate_pricing(params)
            # 切上による多少の誤差を許容（0.5%）
            self.assertGreaterEqual(
                r.margin_pct,
                margin * 100 - 0.5,
                msg=f"margin {margin} failed: got {r.margin_pct}",
            )

    def test_usd_currency(self):
        """USD でも計算できる。"""
        params = PricingParams(source_price=200.0, currency="USD", category="shoes")
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.exchange_rate, 160.0)
        self.assertGreater(r.selling_price_jpy, 0)

    def test_unknown_category_uses_defaults(self):
        """未知カテゴリでもデフォルト値で計算できる。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="UnknownCategory",
        )
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.duty_rate, DEFAULT_DUTY_RATE)
        self.assertAlmostEqual(r.weight_kg, DEFAULT_WEIGHT)
        self.assertGreater(r.selling_price_jpy, 0)

    def test_invalid_commission_raises(self):
        """手数料合計が 99% 以上は ValueError。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            buyma_commission_rate=0.50,
            payment_commission_rate=0.50,
        )
        with self.assertRaises(ValueError):
            calculate_pricing(params)

    def test_custom_duty_rate_override(self):
        """duty_rate を直接指定できる。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="bag",
            duty_rate=0.00,
        )
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.duty_rate, 0.0)
        self.assertAlmostEqual(r.customs_jpy, 0.0)

    def test_custom_weight_override(self):
        """weight_kg を直接指定できる。"""
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="bag",
            weight_kg=0.5,
        )
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.weight_kg, 0.5)
        self.assertAlmostEqual(r.shipping_jpy, 0.5 * 3000.0)

    def test_is_profitable(self):
        """is_profitable フラグの動作確認。"""
        # 高利益商品
        params = PricingParams(source_price=500.0, currency="EUR", category="bag")
        r = calculate_pricing(params)
        self.assertTrue(r.is_profitable(min_profit_jpy=3000))

        # 極端に安い商品（総原価が低くて利益額も低い）
        params_low = PricingParams(
            source_price=0.5,
            currency="EUR",
            category="scarf",
        )
        r_low = calculate_pricing(params_low)
        # 0.5 EUR の商品は絶対額が小さいので利益も 3000 円未満
        self.assertFalse(r_low.is_profitable(min_profit_jpy=3000))


class TestProfitScenarios(unittest.TestCase):
    """実運用を想定した検算。"""

    def test_baseblu_dress_400eur(self):
        """
        BaseBlu ドレス 400 EUR の検算 (EUR=186)。
        関税 9.1%、重量 0.7kg、VAT 還付 16.7%、目標利益率 25%。
        """
        params = PricingParams(
            source_price=400.0,
            currency="EUR",
            category="dress",
        )
        r = calculate_pricing(params)

        # 手計算 (EUR=186):
        #   source_jpy = 400 * 186 = 74400
        #   vat_refund = 74400 * 0.167 = 12424.8
        #   net        = 74400 - 12424.8 = 61975.2
        #   shipping   = 0.7 * 3000 = 2100
        #   customs    = (61975.2 + 2100) * 0.091 ≒ 5830.84
        #   cons_tax   = (61975.2 + 2100 + 5830.84) * 0.10 ≒ 6990.60
        #   total      ≒ 76896.6
        #   commission = 5.8% + 3% = 8.8%
        #   raw_price  ≒ 76896.6 * 1.25 / 0.912 ≒ 105395
        #   selling    = 104600 (pricing.py の利益率最適化で目標 25% に揃う)

        self.assertAlmostEqual(r.vat_refund_jpy, 12424.8, places=1)
        self.assertAlmostEqual(r.shipping_jpy, 2100.0, places=1)
        self.assertEqual(r.selling_price_jpy, 104600)
        self.assertGreater(r.profit_jpy, 16000)  # 目安：原価の 25% 以上
        self.assertGreaterEqual(r.margin_pct, 25.0)

    def test_bag_with_custom_shipping(self):
        """カスタム送料でバッグを計算。"""
        params = PricingParams(
            source_price=300.0,
            currency="EUR",
            category="handbag",
            shipping_jpy=4000.0,
        )
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.shipping_jpy, 4000.0)
        self.assertGreater(r.profit_jpy, 0)
        self.assertGreaterEqual(r.margin_pct, 25.0)


class TestDecideFinalPriceCompetitionLevels(unittest.TestCase):
    """decide_final_price の競合レベル別 boundary。"""

    def setUp(self):
        params = PricingParams(source_price=100.0, currency="EUR", category="dress")
        self.pricing_result = calculate_pricing(params)
        self.target = self.pricing_result.selling_price_jpy
        self.cost = self.pricing_result.total_cost_jpy

    def _market(self, sample_count, median_factor=1.5, confidence=1.0):
        return MarketStats(
            sample_count=sample_count,
            median_jpy=int(self.target * median_factor),
            brand_match_confidence=confidence,
        )

    def test_no_market_data(self):
        d = decide_final_price(self.pricing_result, market=None, category="dress")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "no_market_data")
        self.assertEqual(d.final_price_jpy, self.target)
        self.assertEqual(d.competition_level, "none")

    def test_low_competition_n1(self):
        # n = LOW_COMPETITION_THRESHOLD (=1)
        d = decide_final_price(
            self.pricing_result,
            market=self._market(LOW_COMPETITION_THRESHOLD),
            category="dress",
        )
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "low_competition")
        self.assertEqual(d.final_price_jpy, self.target)

    def test_high_competition_no_cost_advantage_skips(self):
        # n = HIGH_COMPETITION_THRESHOLD (=10) で市場最安値が breakeven 未満
        # → 原価優位なし → skip
        market = MarketStats(
            sample_count=HIGH_COMPETITION_THRESHOLD,
            median_jpy=int(self.target * 1.5),
            min_jpy=int(self.cost * 0.8),   # 最安値が原価の 8 割 = 勝てない
            brand_match_confidence=1.0,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "high_competition")
        self.assertIsNone(d.final_price_jpy)

    def test_high_competition_no_min_price_skips(self):
        # min_jpy 不明 (旧キャッシュ等) → 従来通り skip
        d = decide_final_price(
            self.pricing_result,
            market=self._market(HIGH_COMPETITION_THRESHOLD),
            category="dress",
        )
        # self._market は min_jpy=None
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "high_competition")

    def test_high_competition_with_cost_advantage_price_leader(self):
        # Phase 2d: 高競合 = 需要実証済み。最安値 -3% が breakeven 以上なら
        # price_leader として出品する (原価優位で最安値圏を取る)。
        market_min = int(self.target * 1.4)   # 市場最安値が我々の target より高い
        market = MarketStats(
            sample_count=HIGH_COMPETITION_THRESHOLD + 5,
            median_jpy=int(self.target * 1.6),
            min_jpy=market_min,
            brand_match_confidence=1.0,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "price_leader")
        # 最安値より確実に安い
        self.assertLess(d.final_price_jpy, market_min)
        # breakeven (floor 利益確保ライン) は割らない
        self.assertGreaterEqual(d.final_price_jpy, d.breakeven_price_jpy)

    def test_price_leader_capped_at_1_5x_target(self):
        # 市場最安値が異常に高くても上限は target × 1.5
        market = MarketStats(
            sample_count=HIGH_COMPETITION_THRESHOLD,
            median_jpy=int(self.target * 3.0),
            min_jpy=int(self.target * 2.5),
            brand_match_confidence=1.0,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "price_leader")
        self.assertLessEqual(d.final_price_jpy, math.ceil(self.target * 1.5 / 100) * 100)

    def test_medium_competition_uses_market_aware(self):
        # n = 5, median 1.3x → market_aware = round_up(1.3*0.95) > target
        d = decide_final_price(
            self.pricing_result,
            market=self._market(5, median_factor=1.3),
            category="dress",
        )
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "market_aware")
        self.assertGreater(d.final_price_jpy, self.target)

    def test_medium_competition_market_below_target_discounts(self):
        # Phase 2d: median が target 未満かつ market_aware が breakeven より上
        # → 旧実装は max(target, 相場-5%)=target だったが、相場より高い出品は
        #   成約しないため、相場-5% に下げて成約を取る (market_aware_discounted)。
        params = PricingParams(
            source_price=300.0, currency="EUR", category="bag", target_margin_pct=0.30,
        )
        r = calculate_pricing(params)
        median = int(r.selling_price_jpy * 0.95)
        market = MarketStats(
            sample_count=5,
            median_jpy=median,
            brand_match_confidence=1.0,
        )
        d = decide_final_price(r, market=market, category="bag")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "market_aware_discounted")
        expected = math.ceil(median * 0.95 / 100) * 100
        self.assertEqual(d.final_price_jpy, expected)
        self.assertLess(d.final_price_jpy, r.selling_price_jpy)
        # floor 利益は守られている
        self.assertGreaterEqual(d.final_price_jpy, d.breakeven_price_jpy)

    def test_upper_cap_at_1_5x_target(self):
        # median が target × 2 → market_aware が cap (target × 1.5) を超える
        d = decide_final_price(
            self.pricing_result,
            market=self._market(5, median_factor=2.0),
            category="dress",
        )
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "market_aware")
        # final は target * 1.5 を超えない (round_up 100 単位の許容)
        self.assertLessEqual(d.final_price_jpy, math.ceil(self.target * 1.5 / 100) * 100)


class TestDecideFinalPriceFakeMarket(unittest.TestCase):
    """偽相場ガード (median < cost × UNRELIABLE_MARKET_COST_RATIO)。"""

    def setUp(self):
        params = PricingParams(source_price=100.0, currency="EUR", category="dress")
        self.pricing_result = calculate_pricing(params)
        self.cost = self.pricing_result.total_cost_jpy

    def test_fake_market_triggered_below_threshold(self):
        # median = cost × 0.5 < cost × 0.7 (UNRELIABLE_MARKET_COST_RATIO)
        market = MarketStats(
            sample_count=8,
            median_jpy=int(self.cost * 0.5),
            brand_match_confidence=1.0,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "fake_market")
        # 偽相場時は competition_level=none に戻される
        self.assertEqual(d.competition_level, "none")
        # market_median_jpy / sample_count は None / 0 にリセット
        self.assertIsNone(d.market_median_jpy)
        self.assertEqual(d.market_sample_count, 0)

    def test_fake_market_not_triggered_at_threshold(self):
        # median = cost × 0.71 > cost × 0.7 → 通常パス
        market = MarketStats(
            sample_count=8,
            median_jpy=int(self.cost * 0.71),
            brand_match_confidence=1.0,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertNotEqual(d.reason, "fake_market")


class TestDecideFinalPriceConfidenceGuard(unittest.TestCase):
    """brand_match_confidence による信頼度ガード (Phase 2c)。"""

    def setUp(self):
        params = PricingParams(source_price=100.0, currency="EUR", category="dress")
        self.pricing_result = calculate_pricing(params)
        self.target = self.pricing_result.selling_price_jpy

    def test_low_confidence_treated_as_no_market(self):
        # confidence 0.3 < 0.5 → is_reliable() False → no_market_data 扱い
        market = MarketStats(
            sample_count=8,
            median_jpy=int(self.target * 1.5),
            brand_match_confidence=0.3,
        )
        d = decide_final_price(self.pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "list")
        self.assertEqual(d.reason, "no_market_data")
        self.assertEqual(d.final_price_jpy, self.target)

    def test_confidence_at_boundary_is_reliable(self):
        # confidence 0.5 ちょうど → reliable
        market = MarketStats(
            sample_count=8,
            median_jpy=int(self.target * 1.3),
            brand_match_confidence=0.5,
        )
        self.assertTrue(market.is_reliable())

    def test_default_confidence_is_reliable(self):
        # 旧スキーマ互換: default 1.0
        market = MarketStats(sample_count=8, median_jpy=100000)
        self.assertTrue(market.is_reliable())


class TestDecideFinalPriceBreakeven(unittest.TestCase):
    """breakeven 関連の skip 経路。"""

    def test_target_below_breakeven_no_market(self):
        # 異常パラメータで target_price が breakeven 未満を強制
        params = PricingParams(
            source_price=100.0,
            currency="EUR",
            category="dress",
            target_margin_pct=-0.5,  # 負のマージン → 売価 < 原価
        )
        pricing_result = calculate_pricing(params)
        d = decide_final_price(pricing_result, market=None, category="dress")
        # market なし + target<breakeven → target_below_breakeven で skip
        if pricing_result.selling_price_jpy < pricing_result.total_cost_jpy:
            self.assertEqual(d.action, "skip")
            self.assertEqual(d.reason, "target_below_breakeven")

    def test_below_breakeven_medium_competition(self):
        params = PricingParams(source_price=100.0, currency="EUR", category="dress")
        pricing_result = calculate_pricing(params)
        # cost より安い median を中競合で → market_aware が breakeven 未満
        market = MarketStats(
            sample_count=5,
            median_jpy=int(pricing_result.total_cost_jpy * 0.85),
            brand_match_confidence=1.0,
        )
        d = decide_final_price(pricing_result, market=market, category="dress")
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "below_breakeven")


class TestDecideFinalPriceDDP(unittest.TestCase):
    """DDP (関税込価格) ルートの整合性。"""

    def test_ddp_skips_customs_and_consumption_tax(self):
        params_ddu = PricingParams(
            source_price=200.0, currency="EUR", category="bag",
            landed_cost_basis="DDU",
        )
        params_ddp = PricingParams(
            source_price=200.0, currency="EUR", category="bag",
            landed_cost_basis="DDP",
        )
        r_ddu = calculate_pricing(params_ddu)
        r_ddp = calculate_pricing(params_ddp)

        # DDP は関税・消費税ゼロ
        self.assertEqual(r_ddp.customs_jpy, 0)
        self.assertEqual(r_ddp.consumption_tax_jpy, 0)
        # DDU の方が原価高くなる
        self.assertGreater(r_ddu.total_cost_jpy, r_ddp.total_cost_jpy)
        # DDP の方が selling_price が低くなる (同じ source_price で関税分安い)
        self.assertLess(r_ddp.selling_price_jpy, r_ddu.selling_price_jpy)

    def test_ddp_decision_uses_lower_breakeven(self):
        params_ddp = PricingParams(
            source_price=200.0, currency="EUR", category="bag",
            landed_cost_basis="DDP",
        )
        r_ddp = calculate_pricing(params_ddp)
        d = decide_final_price(r_ddp, market=None, category="bag")
        self.assertEqual(d.action, "list")
        # DDP の breakeven は DDU より低い
        self.assertLess(d.breakeven_price_jpy, r_ddp.selling_price_jpy * 1.0)


if __name__ == "__main__":
    unittest.main()
