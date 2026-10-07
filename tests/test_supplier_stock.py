"""仕入先ごと・サイズごとの在庫 / 価格確認 (app/utils/supplier_stock.py) と、
check_inventory / update_listed_prices が BUYMA を自動操作しないことのテスト。

2026-10-07: 両スクリプトは全件 baseblu の /products/<handle>.json を見ていたが、
.json には variants[].available が無く「全件売切」「先頭バリアントの価格」と誤判定していた。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.utils import supplier_stock as ss  # noqa: E402
import check_inventory  # noqa: E402
import update_listed_prices  # noqa: E402

JS = {
    "title": "Wool Coat",
    "type": "CLOTHING",
    "variants": [
        {"option1": "S", "price": 66557, "available": False},
        {"option1": "M", "price": 66557, "available": True},
        {"option1": "L", "price": 71000, "available": True},
    ],
}


class ResolveSourceTest(unittest.TestCase):
    def test_source_name_column_wins(self):
        rec = {"source_name": "Antonioli", "product_url": "https://www.baseblu.com/en-us/products/x"}
        self.assertEqual(ss.resolve_record_source(rec, {"baseblu.com": "baseblu"}), "antonioli")

    def test_host_fallback(self):
        rec = {"product_url": "https://www.baseblu.com/en-us/products/x"}
        self.assertEqual(ss.resolve_record_source(rec, {"baseblu.com": "baseblu"}), "baseblu")

    def test_unknown_host_is_none(self):
        rec = {"product_url": "https://shop.example.com/products/x"}
        self.assertIsNone(ss.resolve_record_source(rec, {"baseblu.com": "baseblu"}))

    def test_known_hosts_include_config_sources(self):
        hosts = ss.known_source_hosts()
        self.assertEqual(hosts.get("baseblu.com"), "baseblu")
        self.assertGreaterEqual(len(hosts), 2)


class ProductJsUrlTest(unittest.TestCase):
    def test_keeps_market_path(self):
        self.assertEqual(ss.product_js_url("https://www.baseblu.com/en-us/products/coat-1?variant=9"),
                         "https://www.baseblu.com/en-us/products/coat-1.js")

    def test_replaces_json_suffix(self):
        self.assertEqual(ss.product_js_url("https://shop.example.com/products/a.json"),
                         "https://shop.example.com/products/a.js")

    def test_invalid(self):
        self.assertIsNone(ss.product_js_url(""))
        self.assertIsNone(ss.product_js_url("https://shop.example.com/collections/sale"))


class ParseAndEvaluateTest(unittest.TestCase):
    def setUp(self):
        self.snap = ss.parse_shopify_product_js(JS)

    def test_price_is_cents(self):
        self.assertAlmostEqual(self.snap["variants"][0]["price"], 665.57)
        self.assertEqual(self.snap["product_type"], "CLOTHING")

    def test_partial_when_listed_size_sold_out(self):
        r = ss.evaluate_stock(self.snap, "S,M")
        self.assertEqual(r["status"], "partial")
        self.assertEqual(r["missing_listed_sizes"], ["S"])

    def test_sold_out_when_all_listed_gone(self):
        self.assertEqual(ss.evaluate_stock(self.snap, ["S"])["status"], "sold_out")

    def test_in_stock(self):
        self.assertEqual(ss.evaluate_stock(self.snap, "m, L")["status"], "in_stock")

    def test_unknown_listed_sizes_any_available(self):
        self.assertEqual(ss.evaluate_stock(self.snap, "")["status"], "in_stock")
        none = ss.parse_shopify_product_js({"variants": [{"option1": "S", "price": 100, "available": False}]})
        self.assertEqual(ss.evaluate_stock(none, None)["status"], "sold_out")

    def test_error(self):
        self.assertEqual(ss.evaluate_stock({"error": "x"}, "S")["status"], "error")

    def test_price_for_listing_uses_highest_available_listed(self):
        self.assertAlmostEqual(ss.price_for_listing(self.snap, "S,M,L"), 710.0)
        self.assertAlmostEqual(ss.price_for_listing(self.snap, "M"), 665.57)
        self.assertIsNone(ss.price_for_listing(self.snap, "S"))
        self.assertAlmostEqual(ss.price_for_listing(self.snap, ""), 710.0)

    def test_fetch_uses_js_endpoint(self):
        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return JS

        with patch("requests.get", return_value=Resp()) as get:
            snap = ss.fetch_product_snapshot("https://www.baseblu.com/en-us/products/coat-1")
        self.assertTrue(get.call_args[0][0].endswith("/en-us/products/coat-1.js"))
        self.assertEqual(len(snap["variants"]), 3)

    def test_fetch_error_is_soft(self):
        with patch("requests.get", side_effect=OSError("down")):
            self.assertIn("error", ss.fetch_product_snapshot("https://x.example/products/a"))


class MultiOptionStockTest(unittest.TestCase):
    JS2 = {"title": "Tee", "type": "CLOTHING",
           "options": [{"name": "Color", "position": 1, "values": ["Black", "Red"]},
                       {"name": "Size", "position": 2, "values": ["S", "M"]}],
           "variants": [
               {"option1": "Black", "option2": "S", "price": 10000, "available": False},
               {"option1": "Red", "option2": "S", "price": 8000, "available": True},
               {"option1": "Black", "option2": "M", "price": 12000, "available": True},
           ]}

    def test_listed_color_filters_variants(self):
        snap = ss.parse_shopify_product_js(self.JS2)
        self.assertTrue(snap["has_color"])
        # 出品したのは Black/S。Red/S の在庫で「在庫あり」にしない
        self.assertEqual(ss.evaluate_stock(snap, "S", "Black")["status"], "sold_out")
        self.assertIsNone(ss.price_for_listing(snap, "S", "black"))
        self.assertAlmostEqual(ss.price_for_listing(snap, "S,M", "Black"), 120.0)

    def test_unknown_color_falls_back_to_all(self):
        snap = ss.parse_shopify_product_js(self.JS2)
        self.assertEqual(ss.evaluate_stock(snap, "S", "")["status"], "in_stock")

    def test_string_options(self):
        snap = ss.parse_shopify_product_js({"options": ["Size"], "variants": [
            {"option1": "M", "price": 100, "available": True}]})
        self.assertEqual(snap["variants"][0]["size"], "M")
        self.assertFalse(snap["has_color"])


class ScriptsDoNotWriteToBuymaTest(unittest.TestCase):
    def test_check_inventory_execute_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                check_inventory.main(["--execute"])
        self.assertEqual(cm.exception.code, 2)

    def test_update_prices_execute_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                update_listed_prices.main(["--execute"])
        self.assertEqual(cm.exception.code, 2)

    def test_no_playwright_in_scripts(self):
        for name in ("check_inventory.py", "update_listed_prices.py"):
            text = (PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("sync_playwright", text, name)


class CheckInventoryRunTest(unittest.TestCase):
    def test_uses_record_source_and_listed_sizes(self):
        rows = [
            {"item_id": "101", "product_url": "https://www.baseblu.com/en-us/products/coat-1",
             "source_name": "baseblu", "listed_sizes": "S,M", "title": "Coat"},
            {"item_id": "102", "product_url": "https://unknown.example/products/z",
             "source_name": "", "listed_sizes": "", "title": "?"},
        ]
        snap = ss.parse_shopify_product_js(JS)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(check_inventory, "STATUS_PATH", Path(tmp) / "st.json"), \
                patch.object(check_inventory, "load_all_listing_results", return_value=rows), \
                patch.object(check_inventory, "fetch_product_snapshot", return_value=snap) as fetch, \
                contextlib.redirect_stdout(io.StringIO()):
            summary = check_inventory.run(throttle_sec=0)
            saved = json.loads((Path(tmp) / "st.json").read_text(encoding="utf-8"))
        self.assertEqual(fetch.call_count, 1)   # 仕入先不明の行は問い合わせない
        self.assertEqual(summary["partial"], 1)
        self.assertEqual(summary["unknown_source"], 1)
        self.assertEqual(saved["101"]["missing_listed_sizes"], ["S"])


class UpdatePricesTest(unittest.TestCase):
    def test_fetch_current_source_price(self):
        snap = ss.parse_shopify_product_js(JS)
        rec = {"product_url": "https://www.baseblu.com/en-us/products/coat-1", "listed_sizes": "M,L"}
        with patch.object(update_listed_prices, "fetch_product_snapshot", return_value=snap):
            latest = update_listed_prices.fetch_current_source_price(rec, "baseblu")
        self.assertAlmostEqual(latest["price"], 710.0)
        self.assertEqual(latest["source_name"], "baseblu")
        self.assertNotIn("error", latest)

    def test_build_params_uses_record_source(self):
        p_bb = update_listed_prices.build_pricing_params(
            {"price": 200.0, "product_type": "BAGS", "title": "Tote", "source_name": "baseblu"})
        p_fr = update_listed_prices.build_pricing_params(
            {"price": 200.0, "product_type": "BAGS", "title": "Tote", "source_name": "monnierparis"})
        self.assertNotEqual(p_bb.shipping_jpy, p_fr.shipping_jpy)

    def test_unknown_source_raises(self):
        with self.assertRaises(ValueError):
            update_listed_prices.build_pricing_params({"price": 1.0, "source_name": "no_such_shop"})

    def test_confirm_sets_baseline(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(update_listed_prices, "HISTORY_PATH", Path(tmp) / "h.json"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(update_listed_prices.confirm_prices(["123=98000", "bad=1"]), 1)
            history = update_listed_prices.load_history()
        self.assertEqual(update_listed_prices.current_listed_price({"item_id": "123", "price": "70000"}, history),
                         98000)
        self.assertEqual(update_listed_prices.current_listed_price({"item_id": "9", "price": "70000"}, history),
                         70000)


if __name__ == "__main__":
    unittest.main()
