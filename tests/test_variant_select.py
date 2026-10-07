"""サイズ別価格の商品で「最安サイズの価格で全サイズを出品」しないことのテスト (2026-10)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core.sources import ConfigSource  # noqa: E402
from app.utils.variant_select import select_listing_variants  # noqa: E402
import baseblu_sales_to_csv  # noqa: E402
import shopify_sales_to_csv  # noqa: E402

VARIANTS = [
    {"option1": "36", "price": "300.00", "available": False, "sku": "X-36"},
    {"option1": "38", "price": "200.00", "available": True, "sku": "X-38"},
    {"option1": "40", "price": "200.004", "available": True, "sku": "X-40"},
    {"option1": "42", "price": "260.00", "available": True, "sku": "X-42"},
]


class SelectTest(unittest.TestCase):
    def test_only_sizes_at_base_price(self):
        r = select_listing_variants(VARIANTS)
        self.assertEqual(r["variant"]["option1"], "38")
        self.assertTrue(r["available"])
        self.assertEqual(r["available_sizes"], "38, 40")
        self.assertEqual(r["priced_out_sizes"], "42")

    def test_uniform_price_lists_all_available(self):
        vs = [{"option1": s, "price": "100", "available": a} for s, a in (("S", True), ("M", False), ("L", True))]
        r = select_listing_variants(vs)
        self.assertEqual(r["available_sizes"], "S, L")
        self.assertEqual(r["priced_out_sizes"], "")

    def test_none_available(self):
        r = select_listing_variants([{"option1": "S", "price": "1", "available": False}])
        self.assertFalse(r["available"])
        self.assertEqual(r["variant"]["option1"], "S")
        self.assertEqual(r["available_sizes"], "")

    def test_empty(self):
        self.assertIsNone(select_listing_variants([])["variant"])


class ParsersTest(unittest.TestCase):
    def _product(self):
        return {"title": "Leather Boots", "vendor": "PRADA", "handle": "boots", "product_type": "FOOTWEAR",
                "variants": [dict(v) for v in VARIANTS], "images": []}

    def test_baseblu_parse_product(self):
        row = baseblu_sales_to_csv.parse_product(self._product(), fetch_details=False)
        self.assertEqual(row["sale_price"], 200.0)
        self.assertEqual(row["available_sizes"], "38, 40")
        self.assertEqual(row["priced_out_sizes"], "42")
        self.assertEqual(row["sizes"], "36, 38, 40, 42")

    def test_shopify_parse_product(self):
        import test_shopify_scraper
        src = ConfigSource("example", dict(test_shopify_scraper.SOURCE_CONFIG))
        row = shopify_sales_to_csv.parse_shopify_product(self._product(), src)
        self.assertEqual(row["sale_price"], 200.0)
        self.assertEqual(row["available_sizes"], "38, 40")
        self.assertEqual(row["priced_out_sizes"], "42")


if __name__ == "__main__":
    unittest.main()
