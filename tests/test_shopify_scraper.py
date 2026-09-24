"""scripts/shopify_sales_to_csv.py (汎用 Shopify 取得) のユニットテスト。

ネットワークには一切アクセスしない。解析・URL 組み立て・CSV 出力のみを検証する。
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import shopify_sales_to_csv as scraper  # noqa: E402
from app.core.sources import ConfigSource  # noqa: E402

SOURCE_CONFIG = {
    "display_name": "Example Boutique",
    "status": "unverified",
    "platform": "shopify",
    "products_json_url": "https://example.com/collections/sale/products.json",
    "product_url_template": "https://example.com/products/{handle}",
    "currency": "EUR",
    "country": "IT",
    "landed_cost_basis": "DDU",
    "vat_refund_rate": 0.0,
    "purchase_fx_fee_rate": 0.022,
    "domestic_shipping_jpy": 1000.0,
    "shipping_flat_local": 30.0,
    "free_shipping_threshold_local": None,
    "request_delay_sec": 1.0,
    "notes": "テスト用",
}


def _source() -> ConfigSource:
    return ConfigSource("example", dict(SOURCE_CONFIG))


class UrlTest(unittest.TestCase):
    def test_build_page_url_without_query(self):
        self.assertEqual(
            scraper.build_page_url("https://example.com/collections/sale/products.json", 2),
            "https://example.com/collections/sale/products.json?page=2&limit=250",
        )

    def test_build_page_url_with_existing_query(self):
        self.assertEqual(
            scraper.build_page_url("https://example.com/products.json?view=x", 3, limit=50),
            "https://example.com/products.json?view=x&page=3&limit=50",
        )

    def test_shop_base_url(self):
        self.assertEqual(
            scraper.shop_base_url("https://example.com/collections/sale/products.json"),
            "https://example.com",
        )
        self.assertEqual(scraper.shop_base_url("not a url"), "")


class ParseProductTest(unittest.TestCase):
    def setUp(self):
        self.source = _source()

    def test_no_variants_returns_none(self):
        self.assertIsNone(scraper.parse_shopify_product({"title": "x", "variants": []}, self.source))

    def test_availability_checks_all_variants(self):
        """最初のサイズが売切でも、他に在庫があれば在庫ありと判定する。"""
        product = {
            "title": "Dress", "vendor": "KHAITE", "handle": "dress", "variants": [
                {"sku": "K1_38", "option1": "38", "price": "700.0", "available": False},
                {"sku": "K1_40", "option1": "40", "price": "650.0", "available": True},
            ],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertTrue(row["available"])
        self.assertEqual(row["sizes"], "38, 40")
        self.assertEqual(row["available_sizes"], "40")

    def test_price_uses_cheapest_available_variant(self):
        product = {
            "title": "Dress", "handle": "d", "variants": [
                {"sku": "K1_38", "option1": "38", "price": "900.0", "available": False},
                {"sku": "K1_40", "option1": "40", "price": "650.0", "available": True},
                {"sku": "K1_42", "option1": "42", "price": "800.0", "available": True},
            ],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["sale_price"], 650.0)

    def test_sold_out_product_uses_first_variant(self):
        product = {
            "title": "Pumps", "handle": "p", "variants": [
                {"sku": "M_37", "option1": "37", "price": "500.0",
                 "compare_at_price": "900.0", "available": False},
            ],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertFalse(row["available"])
        self.assertEqual(row["sale_price"], 500.0)
        self.assertEqual(row["available_sizes"], "")

    def test_discount_rate_from_compare_at_price(self):
        product = {
            "title": "Bag", "handle": "b", "variants": [
                {"sku": "B1", "option1": "UNI", "price": "1200.0",
                 "compare_at_price": "2000.0", "available": True},
            ],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertEqual(row["original_price"], 2000.0)
        self.assertEqual(row["discount_rate"], 40.0)

    def test_no_compare_at_price_means_zero_discount(self):
        product = {
            "title": "Bag", "handle": "b", "variants": [
                {"sku": "B1", "option1": "UNI", "price": "1200.0",
                 "compare_at_price": None, "available": True},
            ],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertEqual(row["discount_rate"], 0.0)
        self.assertEqual(row["original_price"], 1200.0)

    def test_compare_at_lower_than_price_is_ignored(self):
        product = {
            "title": "Bag", "handle": "b", "variants": [
                {"sku": "B1", "option1": "UNI", "price": "1200.0",
                 "compare_at_price": "1000.0", "available": True},
            ],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["discount_rate"], 0.0)

    def test_sku_size_suffix_is_stripped(self):
        product = {
            "title": "Dress", "handle": "d", "variants": [
                {"sku": "KH001_40", "option1": "40", "price": "650.0", "available": True},
            ],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["sku"], "KH001")

    def test_sku_in_description_wins(self):
        product = {
            "title": "Bag", "handle": "b",
            "body_html": "<p>Sku: GG123_456</p>",
            "variants": [{"sku": "OTHER_UNI", "option1": "UNI", "price": "10.0", "available": True}],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["sku"], "GG123_456")

    def test_season_extracted_from_description(self):
        product = {
            "title": "Coat", "handle": "c", "body_html": "<p>Season: AW25</p>",
            "variants": [{"sku": "C1", "option1": "38", "price": "10.0", "available": True}],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["season"], "AW25")

    def test_images_split_into_main_and_subs(self):
        product = {
            "title": "Bag", "handle": "b",
            "images": [{"src": "https://cdn/1.jpg"}, {"src": "https://cdn/2.jpg"},
                       {"src": "https://cdn/3.jpg"}],
            "variants": [{"sku": "B1", "option1": "UNI", "price": "10.0", "available": True}],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertEqual(row["image_url"], "https://cdn/1.jpg")
        self.assertEqual(row["sub_images"], "https://cdn/2.jpg|https://cdn/3.jpg")

    def test_product_url_uses_source_template(self):
        product = {
            "title": "Bag", "handle": "my-bag",
            "variants": [{"sku": "B1", "option1": "UNI", "price": "10.0", "available": True}],
        }
        self.assertEqual(
            scraper.parse_shopify_product(product, self.source)["product_url"],
            "https://example.com/products/my-bag",
        )

    def test_source_metadata_columns(self):
        product = {
            "title": "Bag", "handle": "b",
            "variants": [{"sku": "B1", "option1": "UNI", "price": "10.0", "available": True}],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertEqual(row["source_name"], "example")
        self.assertEqual(row["currency"], "EUR")
        self.assertEqual(row["landed_cost_basis"], "DDU")

    def test_non_numeric_price_does_not_crash(self):
        product = {
            "title": "Bag", "handle": "b",
            "variants": [{"sku": "B1", "option1": "UNI", "price": "n/a", "available": True}],
        }
        row = scraper.parse_shopify_product(product, self.source)
        self.assertEqual(row["sale_price"], 0.0)

    def test_color_extracted_from_options(self):
        product = {
            "title": "Bag", "handle": "b",
            "options": [{"name": "Size", "values": ["UNI"]},
                        {"name": "Color", "values": ["Black"]}],
            "variants": [{"sku": "B1", "option1": "UNI", "price": "10.0", "available": True}],
        }
        self.assertEqual(scraper.parse_shopify_product(product, self.source)["color"], "Black")

    def test_every_mock_product_parses(self):
        rows = [scraper.parse_shopify_product(p, self.source) for p in scraper.mock_products()]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r is not None for r in rows))


class CsvTest(unittest.TestCase):
    def test_fieldnames_match_filter_input_schema(self):
        """filter_baseblu_profitable.py が読む列がすべて揃っていること。"""
        required = {
            "title", "vendor", "product_type", "sku", "color", "sizes", "available_sizes",
            "season", "sale_price", "original_price", "discount_rate", "available",
            "description_en", "image_url", "sub_images", "product_url",
            "source_name", "currency", "landed_cost_basis",
        }
        self.assertEqual(set(scraper.CSV_FIELDNAMES), required)

    def test_parse_output_keys_match_fieldnames(self):
        product = scraper.mock_products()[0]
        row = scraper.parse_shopify_product(product, _source())
        self.assertEqual(set(row.keys()), set(scraper.CSV_FIELDNAMES))

    def test_save_and_reload_roundtrip(self):
        rows = [scraper.parse_shopify_product(p, _source()) for p in scraper.mock_products()]
        path = Path(tempfile.mkdtemp()) / "out.csv"
        scraper.save_to_csv(rows, path)
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            loaded = list(reader)
            self.assertEqual(reader.fieldnames, scraper.CSV_FIELDNAMES)
        self.assertEqual(len(loaded), 3)
        # available 列は filter が "true"/"1"/"yes" で判定する
        self.assertIn(loaded[0]["available"].lower(), ("true", "false"))


class CliTest(unittest.TestCase):
    def test_test_mode_writes_csv(self):
        out = Path(tempfile.mkdtemp()) / "mock.csv"
        rc = scraper.main(["--source", "antonioli", "--test", "--output", str(out)])
        self.assertEqual(rc, 0)
        self.assertTrue(out.exists())
        with open(out, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["source_name"] == "antonioli" for r in rows))
        # 割引率の降順に並んでいる
        rates = [float(r["discount_rate"]) for r in rows]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_limit_option(self):
        out = Path(tempfile.mkdtemp()) / "mock.csv"
        scraper.main(["--source", "antonioli", "--test", "--limit", "1", "--output", str(out)])
        with open(out, newline="", encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 1)

    def test_list_option_runs(self):
        self.assertEqual(scraper.main(["--list"]), 0)

    def test_unknown_source_exits_with_error(self):
        with self.assertRaises(SystemExit) as ctx:
            scraper.main(["--source", "no_such_shop", "--test"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_missing_source_argument_exits(self):
        with self.assertRaises(SystemExit):
            scraper.main([])


if __name__ == "__main__":
    unittest.main()
