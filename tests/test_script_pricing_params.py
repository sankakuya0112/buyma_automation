"""update_listed_prices / generate_buyma_csv が仕入先レイヤ経由で原価を組むことのテスト。

2026-09-23: 2 スクリプトは PricingParams を直接作っていたため、カード海外手数料・
国内送料・通関立替手数料・固定国際送料が原価から抜け、売価が安く出ていた。
BaseSource.get_pricing_params() 経由に揃えたので、それらが total_cost_jpy に入ることを確認する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core.pricing import (  # noqa: E402
    BANK_TRANSFER_FEE_JPY,
    PricingParams,
    calculate_pricing,
    resolve_exchange_rate,
)
import generate_buyma_csv  # noqa: E402
import update_listed_prices  # noqa: E402


def _assert_baseblu_costs(tc: unittest.TestCase, result, sale_price_eur: float) -> None:
    """baseblu (EUR/DDU/€50 送料) の原価項目がすべて入っていること。"""
    rate = resolve_exchange_rate("EUR")
    tc.assertAlmostEqual(result.purchase_fx_fee_jpy, sale_price_eur * rate * 0.022, places=1)
    tc.assertEqual(result.domestic_shipping_jpy, 1000.0)
    tc.assertGreaterEqual(result.customs_handling_jpy, 2200.0)
    tc.assertAlmostEqual(result.shipping_jpy, 50.0 * rate, places=1)
    expected_total = (
        result.source_price_jpy - result.vat_refund_jpy
        + result.shipping_jpy + result.customs_jpy + result.consumption_tax_jpy
        + result.customs_handling_jpy + result.purchase_fx_fee_jpy
        + result.domestic_shipping_jpy + BANK_TRANSFER_FEE_JPY
    )
    tc.assertAlmostEqual(result.total_cost_jpy, expected_total, delta=1.0)


class UpdateListedPricesParamsTest(unittest.TestCase):
    LATEST = {"price_eur": 200.0, "product_type": "Bags", "title": "Leather Tote Bag"}

    def test_baseblu_costs_included(self):
        params = update_listed_prices.build_pricing_params(self.LATEST)
        self.assertEqual(params.currency, "EUR")
        self.assertEqual(params.landed_cost_basis, "DDU")
        self.assertEqual(params.title, "Leather Tote Bag")
        _assert_baseblu_costs(self, calculate_pricing(params), 200.0)

    def test_cost_higher_than_old_direct_construction(self):
        old = calculate_pricing(PricingParams(
            source_price=200.0, currency="EUR", category="Bags",
        ))
        new = calculate_pricing(update_listed_prices.build_pricing_params(self.LATEST))
        added = (
            new.purchase_fx_fee_jpy + new.domestic_shipping_jpy + new.customs_handling_jpy
        )
        self.assertGreater(added, 0)
        self.assertGreater(new.total_cost_jpy, old.total_cost_jpy + added - 1)
        self.assertGreaterEqual(new.selling_price_jpy, old.selling_price_jpy)

    def test_title_reaches_shoe_duty(self):
        base = {"price_eur": 150.0, "product_type": "Sneakers"}
        canvas = calculate_pricing(update_listed_prices.build_pricing_params(
            {**base, "title": "Canvas Low Sneakers"}))
        leather = calculate_pricing(update_listed_prices.build_pricing_params(
            {**base, "title": "Leather Low Sneakers"}))
        self.assertLess(canvas.customs_jpy, leather.customs_jpy)

    def test_missing_title_and_type_do_not_crash(self):
        params = update_listed_prices.build_pricing_params(
            {"price_eur": 100.0, "product_type": None, "title": None})
        self.assertEqual(params.title, "")
        self.assertEqual(params.category, "")


class UpdateListedPricesDecisionTest(unittest.TestCase):
    """価格追従の判定 (2026-09-24: 相場もカテゴリも渡さず decide_final_price(result) だけだった)。"""

    RECORD = {"vendor": "GUCCI", "title": "Leather Tote Bag"}
    LATEST = {"price_eur": 200.0, "product_type": "Bags", "title": "Leather Tote Bag"}

    def test_category_floor_reaches_decision(self):
        _, bags = update_listed_prices.decide_for_record(self.RECORD, self.LATEST, {})
        _, shoes = update_listed_prices.decide_for_record(
            self.RECORD, {**self.LATEST, "product_type": "FOOTWEAR", "title": "Canvas Sneakers"}, {})
        self.assertEqual(bags.floor_profit_jpy, 8000)      # BAGS: max(¥8,000, 6%)
        self.assertEqual(shoes.floor_profit_jpy, 10000)    # FOOTWEAR: max(¥10,000, 8%)
        self.assertEqual(bags.reason, "no_market_data")

    def test_market_data_changes_the_price(self):
        market = {"GUCCI|leather tote bag": {"sample_count": 12, "median_jpy": 95000, "min_jpy": 90000,
                                              "max_jpy": 120000, "brand_match_confidence": 1.0}}
        result, decision = update_listed_prices.decide_for_record(self.RECORD, self.LATEST, market)
        self.assertEqual(decision.reason, "price_leader")           # 競合 12 件 → 最安値の 3% 下
        self.assertEqual(decision.final_price_jpy, 87300)
        self.assertNotEqual(decision.final_price_jpy, result.selling_price_jpy)
        self.assertEqual(decision.market_sample_count, 12)
        self.assertEqual(decision.market_median_jpy, 95000)

    def test_cheap_market_yields_skip_not_loss(self):
        market = {"GUCCI|leather tote bag": {"sample_count": 12, "median_jpy": 50000, "min_jpy": 40000,
                                              "max_jpy": 60000, "brand_match_confidence": 1.0}}
        _, decision = update_listed_prices.decide_for_record(self.RECORD, self.LATEST, market)
        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "high_competition")

    def test_resolve_market_path(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        existing = tmp / "2026-09-24_market_prices.json"
        existing.write_text("{}", encoding="utf-8")
        self.assertEqual(update_listed_prices.resolve_market_path(str(existing)), str(existing))
        self.assertIsNone(update_listed_prices.resolve_market_path(""))
        self.assertIsNone(update_listed_prices.resolve_market_path(str(tmp / "missing.json")))
        auto = update_listed_prices.resolve_market_path(None)
        self.assertTrue(auto is None or auto.endswith("_market_prices.json"))


class GenerateBuymaCsvParamsTest(unittest.TestCase):
    def _build(self, row=None, **kw):
        args = dict(
            source_price=200.0, product_type="Bags", title="Leather Tote Bag",
            currency=None, target_margin=0.25, exchange_rate=None,
        )
        args.update(kw)
        return generate_buyma_csv.build_pricing_params(row or {}, **args)

    def test_row_without_source_falls_back_to_baseblu(self):
        params = self._build({"source_name": ""})
        self.assertEqual(params.currency, "EUR")
        self.assertEqual(params.landed_cost_basis, "DDU")
        self.assertEqual(params.title, "Leather Tote Bag")
        _assert_baseblu_costs(self, calculate_pricing(params), 200.0)

    def test_source_name_selects_supplier(self):
        params = self._build({"source_name": "italist"})
        self.assertEqual(params.currency, "USD")
        self.assertEqual(params.landed_cost_basis, "DDP")
        self.assertEqual(params.vat_refund_rate, 0.0)

    def test_target_margin_override(self):
        params = self._build(target_margin=0.30)
        self.assertEqual(params.target_margin_pct, 0.30)

    def test_currency_override_only_when_given(self):
        self.assertEqual(self._build(currency="USD").currency, "USD")
        self.assertEqual(self._build(currency=None).currency, "EUR")

    def test_exchange_rate_override_rescales_shipping(self):
        params = self._build(exchange_rate=200.0)
        self.assertEqual(params.exchange_rate, 200.0)
        self.assertAlmostEqual(params.shipping_jpy, 50.0 * 200.0)
        result = calculate_pricing(params)
        self.assertEqual(result.exchange_rate, 200.0)
        self.assertEqual(result.domestic_shipping_jpy, 1000.0)
        self.assertGreaterEqual(result.customs_handling_jpy, 2200.0)

    def test_no_exchange_rate_keeps_default_rate(self):
        params = self._build()
        self.assertIsNone(params.exchange_rate)


if __name__ == "__main__":
    unittest.main()
