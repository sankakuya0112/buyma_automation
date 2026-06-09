"""baseblu_sales_to_csv.parse_product の在庫/価格判定をテストする。

過去バグ: variants[0] のみで available を判定していたため、最初のサイズが
売切れただけで商品全体が「在庫なし」扱いになり、filter で除外されていた。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import baseblu_sales_to_csv as scraper  # noqa: E402


def _product(variants, **kwargs):
    base = {
        "title": "Test Dress",
        "vendor": "TEST BRAND",
        "handle": "test-dress",
        "product_type": "CLOTHING",
        "images": [{"src": "https://cdn.example.com/1.jpg"}],
        "variants": variants,
        "body_html": "<p>Sku: AB123_456</p>",
    }
    base.update(kwargs)
    return base


class AvailabilityTest(unittest.TestCase):
    def test_first_variant_sold_out_but_others_available(self):
        """variants[0] 売切でも他バリアントに在庫があれば available=True。"""
        variants = [
            {"sku": "AB123_456_36", "option1": "36", "price": "500.0", "available": False},
            {"sku": "AB123_456_38", "option1": "38", "price": "500.0", "available": True},
            {"sku": "AB123_456_40", "option1": "40", "price": "500.0", "available": True},
        ]
        row = scraper.parse_product(_product(variants), fetch_details=False)
        self.assertTrue(row["available"])
        self.assertEqual(row["available_sizes"], "38, 40")
        self.assertEqual(row["sizes"], "36, 38, 40")

    def test_all_sold_out(self):
        variants = [
            {"sku": "AB123_456_36", "option1": "36", "price": "500.0", "available": False},
            {"sku": "AB123_456_38", "option1": "38", "price": "500.0", "available": False},
        ]
        row = scraper.parse_product(_product(variants), fetch_details=False)
        self.assertFalse(row["available"])

    def test_all_available(self):
        variants = [
            {"sku": "AB123_456_S", "option1": "S", "price": "300.0", "available": True},
        ]
        row = scraper.parse_product(_product(variants), fetch_details=False)
        self.assertTrue(row["available"])


class PriceVariantSelectionTest(unittest.TestCase):
    def test_price_from_cheapest_available_variant(self):
        """価格は在庫ありバリアントの最安値を採用する。"""
        variants = [
            {"sku": "AB123_456_36", "option1": "36", "price": "600.0", "available": False},
            {"sku": "AB123_456_38", "option1": "38", "price": "550.0", "available": True},
            {"sku": "AB123_456_40", "option1": "40", "price": "500.0", "available": True},
        ]
        row = scraper.parse_product(_product(variants), fetch_details=False)
        self.assertEqual(row["sale_price"], 500.0)

    def test_fallback_to_first_variant_when_none_available(self):
        variants = [
            {"sku": "AB123_456_36", "option1": "36", "price": "600.0",
             "compare_at_price": "1000.0", "available": False},
        ]
        row = scraper.parse_product(_product(variants), fetch_details=False)
        self.assertEqual(row["sale_price"], 600.0)
        self.assertEqual(row["original_price"], 1000.0)
        self.assertEqual(row["discount_rate"], 40.0)

    def test_sku_suffix_stripped_from_chosen_variant(self):
        """SKU は選択したバリアントからサイズ suffix を剥がす。

        description_en に 'Sku: XXX' がある場合はそちらが優先されるため、
        body_html なしの商品で variant SKU フォールバックを検証する。
        """
        variants = [
            {"sku": "ZZ999_111_38", "option1": "38", "price": "400.0", "available": True},
        ]
        row = scraper.parse_product(
            _product(variants, body_html=""), fetch_details=False,
        )
        self.assertEqual(row["sku"], "ZZ999_111")


if __name__ == "__main__":
    unittest.main()
