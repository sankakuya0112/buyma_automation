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


if __name__ == "__main__":
    unittest.main()
