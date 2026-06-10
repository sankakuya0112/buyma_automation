"""app.core.sources のユニットテスト (Phase 2c)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import PricingParams
from app.core.sources import (
    BaseSource,
    BasebluSource,
    ItalistSource,
    REGISTERED_SOURCES,
    get_source,
)


class TestBasebluSourceMetadata(unittest.TestCase):
    """BasebluSource のクラス変数が期待通り。"""

    def test_name_is_baseblu(self):
        s = BasebluSource()
        self.assertEqual(s.name, "baseblu")

    def test_currency_is_eur(self):
        self.assertEqual(BasebluSource().currency, "EUR")

    def test_country_is_italy(self):
        self.assertEqual(BasebluSource().country, "IT")

    def test_landed_cost_basis_ddu(self):
        self.assertEqual(BasebluSource().landed_cost_basis, "DDU")

    def test_metadata_dict_has_three_keys(self):
        meta = BasebluSource().metadata_dict()
        self.assertEqual(
            set(meta.keys()),
            {"source_name", "currency", "landed_cost_basis"},
        )
        self.assertEqual(meta["source_name"], "baseblu")
        self.assertEqual(meta["currency"], "EUR")
        self.assertEqual(meta["landed_cost_basis"], "DDU")


class TestBasebluSourceGetPricingParams(unittest.TestCase):
    """get_pricing_params が source のメタを反映する。"""

    def test_returns_pricing_params_instance(self):
        params = BasebluSource().get_pricing_params(sale_price=100.0, category="dress")
        self.assertIsInstance(params, PricingParams)

    def test_currency_propagates_to_params(self):
        params = BasebluSource().get_pricing_params(sale_price=100.0, category="dress")
        self.assertEqual(params.currency, "EUR")

    def test_landed_cost_basis_propagates(self):
        params = BasebluSource().get_pricing_params(sale_price=100.0, category="dress")
        self.assertEqual(params.landed_cost_basis, "DDU")

    def test_source_price_passes_through(self):
        params = BasebluSource().get_pricing_params(sale_price=250.0, category="bag")
        self.assertAlmostEqual(params.source_price, 250.0)

    def test_category_passes_through(self):
        params = BasebluSource().get_pricing_params(sale_price=100.0, category="shoes")
        self.assertEqual(params.category, "shoes")


class TestGetSourceFactory(unittest.TestCase):
    """get_source() の解決と fallback。"""

    def test_baseblu_returns_baseblu_source(self):
        s = get_source("baseblu")
        self.assertIsInstance(s, BasebluSource)

    def test_case_insensitive(self):
        s = get_source("BASEBLU")
        self.assertIsInstance(s, BasebluSource)

    def test_empty_string_falls_back_to_baseblu(self):
        s = get_source("")
        self.assertIsInstance(s, BasebluSource)

    def test_unknown_falls_back_to_baseblu(self):
        # 旧 CSV を透過処理するための fallback 仕様
        s = get_source("unknown_source_xyz")
        self.assertIsInstance(s, BasebluSource)

    def test_registered_sources_contains_baseblu(self):
        self.assertIn("baseblu", REGISTERED_SOURCES)


class TestBaseSourceContract(unittest.TestCase):
    """BaseSource ABC の契約。"""

    def test_is_abstract(self):
        # fetch_products を実装しないインスタンス化は失敗する
        with self.assertRaises(TypeError):
            BaseSource()  # type: ignore[abstract]

    def test_baseblu_fetch_products_not_implemented(self):
        # Phase 2c では fetch_products は未実装
        with self.assertRaises(NotImplementedError):
            list(BasebluSource().fetch_products())


class TestBasebluShippingPolicy(unittest.TestCase):
    """baseblu の送料体系 (Asia €50 固定 / €850 以上無料)。"""

    def setUp(self):
        self.s = BasebluSource()

    def test_below_threshold_charges_flat_fee(self):
        self.assertEqual(self.s.shipping_cost_local(200.0), 50.0)

    def test_at_threshold_free(self):
        self.assertEqual(self.s.shipping_cost_local(850.0), 0.0)

    def test_above_threshold_free(self):
        self.assertEqual(self.s.shipping_cost_local(1200.0), 0.0)

    def test_shipping_jpy_injected_into_params(self):
        """get_pricing_params の shipping_jpy = €50 × 為替レート。"""
        from app.core.pricing import resolve_exchange_rate
        params = self.s.get_pricing_params(sale_price=200.0, category="wallet")
        expected = 50.0 * resolve_exchange_rate("EUR")
        self.assertAlmostEqual(params.shipping_jpy, expected, places=2)

    def test_free_shipping_injected_as_zero(self):
        params = self.s.get_pricing_params(sale_price=900.0, category="bag")
        self.assertEqual(params.shipping_jpy, 0.0)


class TestRealCostModel(unittest.TestCase):
    """Phase 2d: 海外決済手数料 + 国内発送費が原価に反映される。"""

    def test_params_carry_fx_fee_and_domestic_shipping(self):
        params = BasebluSource().get_pricing_params(sale_price=500.0, category="dress")
        self.assertEqual(params.purchase_fx_fee_rate, 0.022)
        self.assertEqual(params.domestic_shipping_jpy, 1000.0)
        self.assertEqual(params.vat_refund_rate, 0.167)

    def test_fx_fee_increases_total_cost(self):
        from app.core.pricing import calculate_pricing, PricingParams
        base = PricingParams(source_price=500.0, currency="EUR", category="dress")
        with_fee = PricingParams(
            source_price=500.0, currency="EUR", category="dress",
            purchase_fx_fee_rate=0.022,
        )
        r0 = calculate_pricing(base)
        r1 = calculate_pricing(with_fee)
        # fx fee = 仕入値(円) × 2.2%
        self.assertAlmostEqual(
            r1.total_cost_jpy - r0.total_cost_jpy,
            r0.source_price_jpy * 0.022,
            places=1,
        )
        self.assertAlmostEqual(r1.purchase_fx_fee_jpy, r0.source_price_jpy * 0.022, places=1)

    def test_domestic_shipping_increases_total_cost(self):
        from app.core.pricing import calculate_pricing, PricingParams
        base = PricingParams(source_price=500.0, currency="EUR", category="dress")
        with_ship = PricingParams(
            source_price=500.0, currency="EUR", category="dress",
            domestic_shipping_jpy=1000.0,
        )
        r0 = calculate_pricing(base)
        r1 = calculate_pricing(with_ship)
        self.assertAlmostEqual(r1.total_cost_jpy - r0.total_cost_jpy, 1000.0, places=1)

    def test_defaults_remain_backward_compatible(self):
        """PricingParams 直接生成 (Source 非経由) では追加コストゼロ。"""
        from app.core.pricing import calculate_pricing, PricingParams
        r = calculate_pricing(PricingParams(source_price=100.0, currency="EUR"))
        self.assertEqual(r.purchase_fx_fee_jpy, 0.0)
        self.assertEqual(r.domestic_shipping_jpy, 0.0)


class TestItalistSource(unittest.TestCase):
    """ItalistSource (Phase 2d 統合) のメタデータと実コスト設定。"""

    def setUp(self):
        self.s = ItalistSource()

    def test_metadata(self):
        self.assertEqual(self.s.name, "italist")
        self.assertEqual(self.s.currency, "USD")
        self.assertEqual(self.s.country, "IT")
        self.assertEqual(self.s.landed_cost_basis, "DDP")

    def test_vat_refund_is_zero(self):
        """DDP 表示価格は既に VAT 抜き輸出価格。16.7% 還付を適用すると
        原価を 16.7% 過小評価する (赤字出品リスク) ため 0 固定。"""
        self.assertEqual(self.s.vat_refund_rate, 0.0)
        params = self.s.get_pricing_params(sale_price=500.0, category="dress")
        self.assertEqual(params.vat_refund_rate, 0.0)

    def test_ddp_skips_customs_in_pricing(self):
        from app.core.pricing import calculate_pricing
        params = self.s.get_pricing_params(sale_price=500.0, category="dress")
        r = calculate_pricing(params)
        self.assertEqual(r.customs_jpy, 0.0)
        self.assertEqual(r.consumption_tax_jpy, 0.0)
        self.assertEqual(r.vat_refund_jpy, 0.0)

    def test_fx_fee_applies_to_usd(self):
        params = self.s.get_pricing_params(sale_price=500.0)
        self.assertEqual(params.purchase_fx_fee_rate, 0.022)

    def test_shipping_falls_back_to_weight_model(self):
        """送料体系が未確定のため shipping_cost_local は None (重量フォールバック)。"""
        self.assertIsNone(self.s.shipping_cost_local(500.0))
        params = self.s.get_pricing_params(sale_price=500.0, category="bag")
        self.assertIsNone(params.shipping_jpy)

    def test_registered_in_factory(self):
        self.assertIn("italist", REGISTERED_SOURCES)
        self.assertIsInstance(get_source("italist"), ItalistSource)
        self.assertIsInstance(get_source("ITALIST"), ItalistSource)


if __name__ == "__main__":
    unittest.main()
