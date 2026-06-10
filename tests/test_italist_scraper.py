"""italist_sales_to_csv.parse_italist_product のユニットテスト (Phase 2d)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from italist_sales_to_csv import _mock_products, parse_italist_product  # noqa: E402

META = {"source_name": "italist", "currency": "USD", "landed_cost_basis": "DDP"}


def _product(variants, **kwargs):
    base = {
        "title": "Test Bag",
        "vendor": "TEST BRAND",
        "handle": "test-bag",
        "product_type": "BAGS",
        "body_html": "<p>Nice bag</p>",
        "images": [{"src": "https://cdn.example.com/1.jpg"},
                   {"src": "https://cdn.example.com/2.jpg"}],
        "variants": variants,
    }
    base.update(kwargs)
    return base


class ParseItalistProductTest(unittest.TestCase):
    def test_basic_fields_and_meta(self):
        row = parse_italist_product(_product([
            {"sku": "AB1_UNI", "option1": "UNI", "price": "1200.0",
             "compare_at_price": "2000.0", "available": True},
        ]), META)
        self.assertEqual(row["source_name"], "italist")
        self.assertEqual(row["currency"], "USD")
        self.assertEqual(row["landed_cost_basis"], "DDP")
        self.assertEqual(row["sale_price"], 1200.0)
        self.assertEqual(row["original_price"], 2000.0)
        self.assertEqual(row["discount_rate"], 40.0)
        self.assertEqual(row["sku"], "AB1")
        self.assertEqual(row["product_url"],
                         "https://www.italist.com/products/test-bag")
        self.assertEqual(row["sub_images"], "https://cdn.example.com/2.jpg")

    def test_availability_across_variants(self):
        """variants[0] 売切でも他に在庫があれば available=True (baseblu と同仕様)。"""
        row = parse_italist_product(_product([
            {"sku": "X_36", "option1": "36", "price": "650.0", "available": False},
            {"sku": "X_38", "option1": "38", "price": "650.0", "available": True},
        ]), META)
        self.assertTrue(row["available"])
        self.assertEqual(row["available_sizes"], "38")
        self.assertEqual(row["sizes"], "36, 38")

    def test_price_from_cheapest_available_variant(self):
        row = parse_italist_product(_product([
            {"sku": "X_36", "option1": "36", "price": "700.0", "available": True},
            {"sku": "X_38", "option1": "38", "price": "600.0", "available": True},
        ]), META)
        self.assertEqual(row["sale_price"], 600.0)

    def test_sku_from_description_takes_priority(self):
        row = parse_italist_product(_product(
            [{"sku": "VARIANT_SKU_S", "option1": "S", "price": "100.0", "available": True}],
            body_html="<p>Sku: REAL_SKU_99</p>",
        ), META)
        self.assertEqual(row["sku"], "REAL_SKU_99")

    def test_no_variants_returns_none(self):
        self.assertIsNone(parse_italist_product(_product([]), META))

    def test_season_extracted_from_body(self):
        row = parse_italist_product(_product(
            [{"sku": "A_40", "option1": "40", "price": "650.0", "available": True}],
            body_html="<p>Season: AW25</p>",
        ), META)
        self.assertEqual(row["season"], "AW25")

    def test_mock_products_parse_cleanly(self):
        """--test モードのモック 3 件が全件 parse でき、スキーマが揃う。"""
        rows = [parse_italist_product(p, META) for p in _mock_products()]
        rows = [r for r in rows if r]
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIn("sale_price", r)
            self.assertEqual(r["landed_cost_basis"], "DDP")
        # KHAITE は 38 売切 / 40 在庫あり → available=True
        khaite = next(r for r in rows if r["vendor"] == "KHAITE")
        self.assertTrue(khaite["available"])
        # MANOLO は全サイズ売切 → available=False
        mb = next(r for r in rows if r["vendor"] == "MANOLO BLAHNIK")
        self.assertFalse(mb["available"])


if __name__ == "__main__":
    unittest.main()
