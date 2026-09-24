"""scripts/ai_enrich_candidates.py のテスト: 候補選択・列追加・dry-run。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

import ai_enrich_candidates as enrich_mod  # noqa: E402
from _ai_fakes import ScriptedClient  # noqa: E402

CAT_DATA = json.loads((PROJECT_ROOT / "data" / "categories.json").read_text(encoding="utf-8"))

BASE_FIELDS = ["title", "vendor", "product_type", "sku", "color", "sizes", "description_en",
               "action", "opportunity_score", "expected_profit_jpy", "profit_jpy", "final_price_jpy"]


def _rows():
    return [
        {"title": "GG shoulder bag", "vendor": "GUCCI", "product_type": "BAGS", "sku": "G1", "color": "Black",
         "sizes": "UNI", "description_en": "Leather.", "action": "list", "opportunity_score": "500",
         "expected_profit_jpy": "20000", "profit_jpy": "20000", "final_price_jpy": "100000"},
        {"title": "Mystery item", "vendor": "PRADA", "product_type": "BAGS", "sku": "P2", "color": "",
         "sizes": "UNI", "description_en": "Nylon.", "action": "list", "opportunity_score": "900",
         "expected_profit_jpy": "9000", "profit_jpy": "9000", "final_price_jpy": "50000"},
        {"title": "Skipped", "vendor": "X", "product_type": "BAGS", "sku": "S3", "color": "", "sizes": "",
         "description_en": "", "action": "skip", "opportunity_score": "99999",
         "expected_profit_jpy": "1", "profit_jpy": "1", "final_price_jpy": "1"},
    ]


class SelectTest(unittest.TestCase):
    def test_select_candidates_orders_by_opportunity_and_skips_action_skip(self):
        idx = enrich_mod.select_candidates(_rows(), 10)
        self.assertEqual(idx, [1, 0])
        self.assertEqual(enrich_mod.select_candidates(_rows(), 1), [1])

    def test_row_id_unique_even_without_sku(self):
        self.assertEqual(enrich_mod.row_id({"sku": "A"}, 3), "A#3")
        self.assertEqual(enrich_mod.row_id({}, 3), "row3")


class EnrichTest(unittest.TestCase):
    def test_enrich_populates_columns(self):
        rows = _rows()
        cat_paths = None

        def _copy(user):
            ids = [p["id"] for p in json.loads(user.split("\n\n", 1)[1])]
            return {"items": [{"id": i, "title_ja": f"タイトル {i}", "description_ja": "説明" * 20,
                               "keywords": ["k1", "k2"], "color_ja": "ブラック"} for i in ids]}

        def _cat(user):
            ids = [p["id"] for p in json.loads(user.split("\n\n", 1)[1])]
            return {"items": [{"id": i, "category_index": 0, "confidence": "high"} for i in ids]}

        def _judge(user):
            ids = [p["id"] for p in json.loads(user.split("\n\n", 1)[1])]
            return {"items": [{"id": i, "verdict": "hold" if i.startswith("P2") else "list",
                               "risk_flags": [], "reason": "ok", "priority": 4} for i in ids]}

        client = ScriptedClient({"listing_copy": _copy, "category": _cat, "judge": _judge})
        stats = enrich_mod.enrich(rows, enrich_mod.select_candidates(rows, 10), client, CAT_DATA)
        self.assertEqual(stats["candidates"], 2)
        self.assertEqual(stats["copy"], 2)
        self.assertEqual(stats["judge"], 2)
        self.assertEqual(stats["verdict"]["hold"], 1)
        # G1 はキーワード辞書で決まる、P2 (Mystery) は AI
        self.assertEqual(rows[0]["category_source"], "keyword")
        self.assertEqual(rows[1]["category_source"], "ai")
        self.assertEqual(stats["category_ai"], 1)
        self.assertTrue(rows[0]["ai_title_ja"].startswith("【GUCCI】"))
        self.assertEqual(rows[0]["ai_keywords"], "k1|k2")
        self.assertEqual(rows[1]["ai_verdict"], "hold")
        self.assertEqual(rows[0]["ai_priority"], "4")
        self.assertNotIn("ai_title_ja", rows[2])           # action=skip は触らない
        self.assertIn("copy=", rows[0]["ai_models"])
        # カテゴリ AI は「未決の商品だけ」に送られている
        cat_calls = [c for c in client.calls if c[0] == "category"]
        self.assertEqual(len(cat_calls), 1)
        self.assertNotIn('"G1#0"', cat_calls[0][2])

    def test_enrich_offline_keeps_deterministic_category(self):
        rows = _rows()
        stats = enrich_mod.enrich(rows, [0, 1], ScriptedClient({}), CAT_DATA)
        self.assertEqual(stats["copy"], 0)
        self.assertEqual(rows[0]["category_path"], "レディースファッション > バッグ・カバン > ショルダーバッグ・ポシェット")
        self.assertEqual(rows[1]["category_source"], "type_default")
        self.assertEqual(rows[0].get("ai_verdict", ""), "")

    def test_write_rows_appends_ai_columns_once(self):
        tmp = Path(tempfile.mkdtemp()) / "x.csv"
        rows = _rows()
        rows[0]["ai_title_ja"] = "t"
        enrich_mod.write_rows(str(tmp), rows, BASE_FIELDS)
        with open(tmp, newline="", encoding="utf-8-sig") as f:
            r = csv.DictReader(f)
            fields = list(r.fieldnames)
            data = list(r)
        self.assertEqual(fields[:len(BASE_FIELDS)], BASE_FIELDS)
        for c in enrich_mod.AI_COLUMNS:
            self.assertIn(c, fields)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(data[0]["ai_title_ja"], "t")
        self.assertEqual(data[1]["ai_title_ja"], "")
        # 2 回目 (既に ai 列がある fieldnames) でも重複しない
        enrich_mod.write_rows(str(tmp), rows, fields)
        with open(tmp, newline="", encoding="utf-8-sig") as f:
            self.assertEqual(len(csv.DictReader(f).fieldnames), len(fields))

    def test_dry_run_report_estimates_without_calls(self):
        rows = _rows()
        rep = enrich_mod.dry_run_report(rows, [0, 1], CAT_DATA)
        self.assertEqual(rep["listing_copy"]["items"], 2)
        self.assertEqual(rep["category"]["items"], 1)      # 未決は Mystery item だけ
        self.assertEqual(rep["judge"]["calls"], 1)
        self.assertGreater(rep["listing_copy"]["usd"], 0)

    def test_main_dry_run_on_temp_csv(self):
        tmp = Path(tempfile.mkdtemp()) / "2026-01-01_baseblu_profitable_products.csv"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=BASE_FIELDS)
            w.writeheader()
            w.writerows(_rows())
        self.assertEqual(enrich_mod.main(["--input", str(tmp), "--dry-run", "--limit", "1"]), 0)
        self.assertEqual(enrich_mod.main(["--input", "/nonexistent.csv"]), 1)


if __name__ == "__main__":
    unittest.main()
