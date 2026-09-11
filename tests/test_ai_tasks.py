"""app.ai.tasks のテスト: 出品文 / カテゴリ / 審査 / レビュー / 診断 (AI はスクリプト応答)。"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from app.ai.tasks import category, diagnose, judge, listing_copy, review  # noqa: E402
from _ai_fakes import ScriptedClient  # noqa: E402

CAT_DATA = {
    "_tier2_valid": ["バッグ・カバン", "アウター", "靴・シューズ"],
    "default": ["レディースファッション", "バッグ・カバン", "ハンドバッグ"],
    "mappings": [
        {"product_type": "BAGS",
         "default": ["レディースファッション", "バッグ・カバン", "ハンドバッグ"],
         "keywords": [
             {"match": ["shoulder bag"], "path": ["レディースファッション", "バッグ・カバン", "ショルダーバッグ"]},
             {"match": ["bogus"], "path": ["レディースファッション", "小物", "その他"]},   # 第2階層が無効
         ]},
        {"product_type": "CLOTHING",
         "default": ["レディースファッション", "アウター", "ジャケット"],
         "keywords": [{"match": ["coat"], "path": ["レディースファッション", "アウター", "コート"]}]},
    ],
}

PRODUCTS = [
    {"vendor": "GUCCI", "title": "GG shoulder bag", "product_type": "BAGS", "sku": "G1",
     "description_en": "Leather shoulder bag. Made in Italy.", "color": "Black", "sizes": "UNI"},
    {"vendor": "PRADA", "title": "Nylon thing", "product_type": "BAGS", "sku": "P2",
     "description_en": "Re-Nylon.", "color": "Navy", "sizes": "UNI"},
]


class ListingCopyTest(unittest.TestCase):
    def test_offline_returns_empty(self):
        self.assertEqual(listing_copy.generate_listing_copy(PRODUCTS, ScriptedClient({})), {})

    def test_copy_generated_and_sanitized(self):
        resp = {"items": [
            {"id": "G1", "title_ja": "★GG ショルダーバッグ Lavallière", "description_ja": "上質なレザーを使ったショルダーバッグです。" * 3,
             "keywords": ["グッチ", "グッチ", "ショルダーバッグ"], "color_ja": "ブラック"},
            {"id": "P2", "title_ja": "", "description_ja": "short", "keywords": [], "color_ja": "紫"},
            {"id": "ZZ", "title_ja": "unknown id", "description_ja": "x" * 50, "keywords": [], "color_ja": ""},
        ]}
        client = ScriptedClient({"listing_copy": resp})
        out = listing_copy.generate_listing_copy(PRODUCTS, client)
        self.assertIn("G1", out)
        self.assertNotIn("P2", out)          # タイトル空 → 使えない
        self.assertNotIn("ZZ", out)          # 知らない id は無視
        g = out["G1"]
        self.assertTrue(g["title_ja"].startswith("【GUCCI】"))
        self.assertNotIn("★", g["title_ja"])
        self.assertNotIn("è", g["title_ja"])
        self.assertEqual(g["keywords"], ["グッチ", "ショルダーバッグ"])
        self.assertEqual(g["color_ja"], "ブラック")

    def test_chunking_respects_items_per_call(self):
        many = [dict(PRODUCTS[0], sku=f"S{i}") for i in range(20)]
        client = ScriptedClient({"listing_copy": lambda user: {"items": [
            {"id": p["id"], "title_ja": "t", "description_ja": "d" * 40, "keywords": [], "color_ja": ""}
            for p in json.loads(user.split("\n\n", 1)[1])]}})
        out = listing_copy.generate_listing_copy(many, client)
        self.assertEqual(len(out), 20)
        from app.ai.router import policy_for
        expected_calls = -(-20 // policy_for("listing_copy").items_per_call)
        self.assertEqual(len(client.calls), expected_calls)

    def test_compact_product_truncates_description(self):
        p = dict(PRODUCTS[0], description_en="word " * 1000)
        c = listing_copy.compact_product(p, "x")
        self.assertLessEqual(len(c["description_en"]), listing_copy.MAX_DESC_CHARS + 1)

    def test_invalid_color_family_dropped(self):
        s = listing_copy.sanitize_copy({"title_ja": "t", "description_ja": "", "keywords": [], "color_ja": "紫"}, "B")
        self.assertEqual(s["color_ja"], "")


class CategoryTest(unittest.TestCase):
    def test_keyword_path_sources(self):
        self.assertEqual(category.keyword_category_path("GG shoulder bag", "BAGS", CAT_DATA),
                         (["レディースファッション", "バッグ・カバン", "ショルダーバッグ"], "keyword"))
        self.assertEqual(category.keyword_category_path("Nylon thing", "BAGS", CAT_DATA)[1], "type_default")
        self.assertEqual(category.keyword_category_path("x", "UNKNOWN", CAT_DATA)[1], "global_default")

    def test_allowed_paths_filters_invalid_tier2_and_dedupes(self):
        paths = category.allowed_paths(CAT_DATA)
        tier2 = {p[1] for p in paths}
        self.assertNotIn("小物", tier2)
        self.assertEqual(len(paths), len({tuple(p) for p in paths}))
        self.assertIn(["レディースファッション", "アウター", "コート"], paths)

    def test_classify_validates_index_and_confidence(self):
        paths = category.allowed_paths(CAT_DATA)
        target = paths.index(["レディースファッション", "アウター", "コート"])
        client = ScriptedClient({"category": {"items": [
            {"id": "G1", "category_index": target, "confidence": "high"},
            {"id": "P2", "category_index": 999, "confidence": "high"},     # 範囲外
        ]}})
        out = category.classify_categories(PRODUCTS, client, CAT_DATA)
        self.assertEqual(out["G1"]["path"], ["レディースファッション", "アウター", "コート"])
        self.assertNotIn("P2", out)
        # system prompt にカテゴリ一覧が番号付きで入っている
        self.assertIn(f"{target}: レディースファッション > アウター > コート", client.calls[0][1])

    def test_low_confidence_rejected(self):
        client = ScriptedClient({"category": {"items": [{"id": "G1", "category_index": 0, "confidence": "low"}]}})
        self.assertEqual(category.classify_categories(PRODUCTS, client, CAT_DATA), {})

    def test_resolve_category_precedence(self):
        ai = {"path": ["レディースファッション", "アウター", "コート"], "confidence": "high"}
        # キーワードが当たれば AI より辞書
        self.assertEqual(category.resolve_category(PRODUCTS[0], CAT_DATA, ai)[1], "keyword")
        # 当たらなければ AI
        path, src = category.resolve_category(PRODUCTS[1], CAT_DATA, ai)
        self.assertEqual((path, src), (ai["path"], "ai"))
        # AI も無ければ default
        self.assertEqual(category.resolve_category(PRODUCTS[1], CAT_DATA, None)[1], "type_default")


class JudgeTest(unittest.TestCase):
    ROWS = [
        {"vendor": "GUCCI", "title": "Bag", "product_type": "BAGS", "sku": "G1", "final_price_jpy": "120000",
         "expected_profit_jpy": "20000", "expected_margin_pct": "25.0", "competition_level": "high",
         "sale_probability": "0.12", "opportunity_score": "2400", "sizes": "UNI"},
        {"vendor": "YSL", "title": "Python boots", "product_type": "FOOTWEAR", "sku": "Y2",
         "final_price_jpy": "90000", "expected_profit_jpy": "15000"},
    ]

    def test_offline_empty(self):
        self.assertEqual(judge.judge_candidates(self.ROWS, ScriptedClient({})), {})

    def test_validation_of_fields(self):
        client = ScriptedClient({"judge": {"items": [
            {"id": "G1", "verdict": "list", "risk_flags": ["price_too_high_for_new_account", "made_up"],
             "reason": "r", "priority": 9},
            {"id": "Y2", "verdict": "banned", "risk_flags": ["restricted_material"], "reason": "CITES", "priority": "x"},
        ]}})
        out = judge.judge_candidates(self.ROWS, client, today=date(2026, 9, 11))
        self.assertEqual(out["G1"]["verdict"], "list")
        self.assertEqual(out["G1"]["risk_flags"], ["price_too_high_for_new_account"])
        self.assertEqual(out["G1"]["priority"], 5)
        self.assertEqual(out["Y2"]["verdict"], "hold")       # 不明な verdict は hold
        self.assertEqual(out["Y2"]["priority"], 3)

    def test_date_goes_to_user_not_system(self):
        client = ScriptedClient({"judge": {"items": []}})
        judge.judge_candidates(self.ROWS, client, today=date(2026, 9, 11))
        task, system, user, _ = client.calls[0]
        self.assertNotIn("2026-09-11", system)
        self.assertIn("2026-09-11", user)

    def test_compact_candidate_numeric_coercion(self):
        c = judge.compact_candidate(self.ROWS[0], "G1")
        self.assertEqual(c["final_price_jpy"], 120000)
        self.assertEqual(c["expected_margin_pct"], 25)
        self.assertEqual(c["sale_probability"], 0.12)
        self.assertNotIn("market_median_jpy", c)


class ReviewTest(unittest.TestCase):
    def test_payload_omits_missing(self):
        p = review.build_review_payload(pipeline={"listable": 3}, funnel=None, notes=["a"])
        self.assertEqual(set(p), {"pipeline", "notes"})

    def test_weekly_review(self):
        self.assertIsNone(review.weekly_review({}, ScriptedClient({"weekly_review": "x"})))
        client = ScriptedClient({"weekly_review": "1. 来週…"})
        self.assertEqual(review.weekly_review({"pipeline": {"listable": 3}}, client), "1. 来週…")
        self.assertEqual(client.calls[0][0], "weekly_review")


class DiagnoseTest(unittest.TestCase):
    def test_redaction(self):
        s = diagnose.redact_secrets("mail me@x.jp password: hunter2 key sk-ant-api03-abcdefghij token=abc")
        self.assertNotIn("me@x.jp", s)
        self.assertNotIn("hunter2", s)
        self.assertNotIn("sk-ant-api03", s)
        self.assertIn("<redacted>", s)

    def test_prepare_log_tail(self):
        text = "x" * (diagnose.MAX_LOG_CHARS + 500)
        out = diagnose.prepare_log(text)
        self.assertTrue(out.startswith("…(前略)…"))
        self.assertLess(len(out), diagnose.MAX_LOG_CHARS + 50)

    def test_diagnose_roundtrip(self):
        client = ScriptedClient({"diagnose": {"summary": "s", "probable_cause": "c", "confidence": "high",
                                              "fix_steps": ["a"], "needs_code_change": False, "files_to_check": []}})
        d = diagnose.diagnose_failure("Traceback ... 422 cate_id", client, context="下書き保存")
        self.assertEqual(d["summary"], "s")
        self.assertIn("422 cate_id", client.calls[0][2])
        self.assertIn("下書き保存", client.calls[0][2])
        self.assertIsNone(diagnose.diagnose_failure("   ", client))


if __name__ == "__main__":
    unittest.main()
