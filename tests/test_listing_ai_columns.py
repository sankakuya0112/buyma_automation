"""scripts/buyma_auto_listing.py の AI 列統合テスト (playwright はスタブで代替)。"""

from __future__ import annotations

import csv
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# playwright 不在環境でも import できるようスタブを差し込む (モジュール import 時に sys.exit するため)
if "playwright.sync_api" not in sys.modules:
    pw = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: None
    sync_api.TimeoutError = TimeoutError
    pw.sync_api = sync_api
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = sync_api

import buyma_auto_listing as bal  # noqa: E402

CAT_DATA = {
    "_tier2_valid": ["バッグ・カバン", "アウター"],
    "default": ["レディースファッション", "バッグ・カバン", "ハンドバッグ"],
    "mappings": [{"product_type": "BAGS", "default": ["レディースファッション", "バッグ・カバン", "ハンドバッグ"],
                  "keywords": [{"match": ["shoulder"], "path": ["レディースファッション", "バッグ・カバン", "ショルダーバッグ"]}]}],
}


class ResolveHelpersTest(unittest.TestCase):
    def test_category_prefers_valid_ai_path(self):
        p = {"title": "shoulder bag", "product_type": "BAGS",
             "category_path": "レディースファッション > アウター > コート"}
        self.assertEqual(bal.resolve_listing_category(p, CAT_DATA), ["レディースファッション", "アウター", "コート"])

    def test_category_rejects_invalid_tier2_and_falls_back(self):
        p = {"title": "shoulder bag", "product_type": "BAGS", "category_path": "レディースファッション > 小物 > その他"}
        self.assertEqual(bal.resolve_listing_category(p, CAT_DATA), ["レディースファッション", "バッグ・カバン", "ショルダーバッグ"])
        p = {"title": "shoulder bag", "product_type": "BAGS", "category_path": "壊れた"}
        self.assertEqual(bal.resolve_listing_category(p, CAT_DATA)[2], "ショルダーバッグ")

    def test_title_prefers_ai_and_trims(self):
        p = {"title": "GG bag", "vendor": "GUCCI", "sku": "1", "ai_title_ja": "【GUCCI】Lavallière " + "あ" * 40}
        t = bal.resolve_listing_title(p)
        self.assertTrue(t.startswith("【GUCCI】Lavalliere"))
        self.assertLessEqual(bal._buyma_title_width(t), 60)
        self.assertEqual(bal.resolve_listing_title({"title": "GG bag", "vendor": "GUCCI", "sku": "1"}), "【GUCCI】 GG bag")

    def test_color_uses_ai_family_when_dictionary_unknown(self):
        self.assertEqual(bal.resolve_listing_color({"color": "Black"}), ("ブラック", "Black"))
        self.assertEqual(bal.resolve_listing_color({"color": "Parakeet", "ai_color_ja": "グリーン"}), ("グリーン", "Parakeet"))
        self.assertEqual(bal.resolve_listing_color({"color": "", "ai_color_ja": "ブルー"}), ("ブルー", "ブルー"))
        self.assertEqual(bal.resolve_listing_color({"color": ""}), ("マルチカラー", "マルチカラー"))

    def test_generate_description_uses_ai_text(self):
        d = bal.generate_description("T", "B", "SKU1", "leather bag", "cat", desc_ja="上質なレザーのバッグです。")
        self.assertIn("上質なレザーのバッグです。", d)
        self.assertIn("安心の正規品保証", d)          # 固定セクションは維持
        d2 = bal.generate_description("T", "B", "SKU1", "leather bag", "cat")
        self.assertNotIn("上質なレザー", d2)

    def test_sort_key_priority_then_opportunity_then_profit(self):
        rows = [
            {"ai_priority": "", "opportunity_score": "100", "profit_jpy": "9000"},
            {"ai_priority": "5", "opportunity_score": "10", "profit_jpy": "1000"},
            {"ai_priority": "", "opportunity_score": "100", "profit_jpy": "20000"},
        ]
        rows.sort(key=bal._listing_sort_key, reverse=True)
        self.assertEqual([r["profit_jpy"] for r in rows], ["1000", "20000", "9000"])


class LoadProductsTest(unittest.TestCase):
    def test_load_products_reads_ai_columns_and_skips_ai_skip(self):
        tmp = Path(tempfile.mkdtemp())
        fields = ["title", "vendor", "final_price_jpy", "selling_price_jpy", "expected_profit_jpy", "profit_jpy",
                  "total_cost_jpy", "sale_price_eur", "action", "opportunity_score",
                  "category_path", "ai_title_ja", "ai_description_ja", "ai_verdict", "ai_priority", "ai_reason"]
        with open(tmp / "2026-01-01_baseblu_profitable_products.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerow({"title": "A", "vendor": "GUCCI", "final_price_jpy": "100000", "selling_price_jpy": "100000",
                        "expected_profit_jpy": "20000", "profit_jpy": "20000", "total_cost_jpy": "70000",
                        "sale_price_eur": "300", "action": "list", "opportunity_score": "500",
                        "category_path": "レディースファッション > バッグ・カバン > ハンドバッグ",
                        "ai_title_ja": "【GUCCI】バッグ", "ai_description_ja": "説明", "ai_verdict": "list",
                        "ai_priority": "4", "ai_reason": "ok"})
            w.writerow({"title": "B", "vendor": "YSL", "final_price_jpy": "90000", "selling_price_jpy": "90000",
                        "expected_profit_jpy": "15000", "profit_jpy": "15000", "total_cost_jpy": "60000",
                        "sale_price_eur": "300", "action": "list", "opportunity_score": "900",
                        "ai_verdict": "skip", "ai_reason": "CITES"})
            w.writerow({"title": "C", "vendor": "PRADA", "final_price_jpy": "50000", "selling_price_jpy": "50000",
                        "expected_profit_jpy": "9000", "profit_jpy": "9000", "total_cost_jpy": "35000",
                        "sale_price_eur": "200", "action": "list", "opportunity_score": "800"})
        with patch.object(bal, "OUTPUT_DIR", str(tmp)):
            products = bal.load_products()
        self.assertEqual([p["title"] for p in products], ["A", "C"])       # B は AI skip、A は優先度で先頭
        a = products[0]
        self.assertEqual(a["ai_title_ja"], "【GUCCI】バッグ")
        self.assertEqual(a["ai_verdict"], "list")
        self.assertEqual(a["category_path"], "レディースファッション > バッグ・カバン > ハンドバッグ")
        self.assertEqual(products[1]["ai_verdict"], "")


if __name__ == "__main__":
    unittest.main()
