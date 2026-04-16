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
    DEFAULT_DUTY_RATE,
    DEFAULT_EXCHANGE_RATES,
    DEFAULT_WEIGHT,
    PricingParams,
    PricingResult,
    calculate_pricing,
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
        self.assertAlmostEqual(resolve_exchange_rate("EUR"), 163.0)
        self.assertAlmostEqual(resolve_exchange_rate("USD"), 150.0)
        self.assertAlmostEqual(resolve_exchange_rate("GBP"), 190.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(resolve_exchange_rate("eur"), 163.0)


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
        self.assertAlmostEqual(r.exchange_rate, 163.0)

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
        expected = 100.0 * 163.0 * 0.167
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

        # 手計算:
        #   net_source = 100 * 163 = 16300
        #   shipping   = 1.2 * 3000 = 3600
        #   customs    = (16300 + 3600) * 0.08 = 1592
        #   consumption = (16300 + 3600 + 1592) * 0.10 = 2149.2
        #   total      = 16300 + 3600 + 1592 + 2149.2 = 23641.2
        #   selling    = ceil(23641.2 / 100) * 100 = 23700
        self.assertEqual(r.selling_price_jpy, 23700)

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
        self.assertAlmostEqual(r.exchange_rate, 150.0)
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
        BaseBlu ドレス 400 EUR の検算。
        為替 163、関税 9.1%、重量 0.7kg、VAT 還付 16.7%、目標利益率 25%。
        """
        params = PricingParams(
            source_price=400.0,
            currency="EUR",
            category="dress",
        )
        r = calculate_pricing(params)

        # 手計算:
        #   source_jpy = 400 * 163 = 65200
        #   vat_refund = 65200 * 0.167 = 10888.4
        #   net        = 65200 - 10888.4 = 54311.6
        #   shipping   = 0.7 * 3000 = 2100
        #   customs    = (54311.6 + 2100) * 0.091 = 5133.46
        #   cons_tax   = (54311.6 + 2100 + 5133.46) * 0.10 = 6154.51
        #   total      = 54311.6 + 2100 + 5133.46 + 6154.51 = 67699.56
        #   commission = 5.8% + 3% = 8.8%
        #   raw_price  = 67699.56 * 1.25 / (1 - 0.088) = 84624.45 / 0.912 = 92789.97
        #   selling    = ceil(92789.97 / 100) * 100 = 92800

        self.assertAlmostEqual(r.vat_refund_jpy, 10888.4, places=1)
        self.assertAlmostEqual(r.shipping_jpy, 2100.0, places=1)
        self.assertEqual(r.selling_price_jpy, 92800)
        self.assertGreater(r.profit_jpy, 14000)  # 目安：原価の 25% 以上
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


if __name__ == "__main__":
    unittest.main()
