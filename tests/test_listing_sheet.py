"""出品シート (app/core/listing_sheet.py / scripts/generate_listing_sheet.py) と
利益計算の補助 (profit_at_price / min_price_for_profit) のテスト。ネットワークには触れない。"""

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from app.core import listing_sheet as ls  # noqa: E402
from app.core.pricing import (  # noqa: E402
    BUYMA_COMMISSION_RATE,
    calculate_pricing,
    min_price_for_profit,
    profit_at_price,
)
from app.core.sources import get_source  # noqa: E402
from app.utils.listing_helpers import (  # noqa: E402
    extract_gender,
    is_collar_size_shirt,
    map_size_to_jp_reference_for,
)

FX_ENV = {"EUR_TO_JPY": "180", "FX_BUFFER_PCT": "0", "BUYMA_FIXED_FEE_ENABLED": "1"}

CARD = {
    "source_name": "baseblu", "vendor": "MAISON MARGIELA", "title": "Leather Card Holder",
    "product_type": "ACCESSORIES", "sale_price_eur": "196.72", "recommended_price": "80100",
    "available_sizes": "UNI", "sku": "SA3VX0007P4455_T8013", "color": "Black",
    "product_url": "https://www.baseblu.com/en-us/products/card-holder-134",
    "image_urls": "https://cdn.example/a.jpg,https://cdn.example/b.jpg",
    "description_en": "Composition: 100% Calf Leather Bos Taurus\nCard slots",
}
SHIRT = {
    "source_name": "baseblu", "vendor": "ETRO", "title": "Roma cotton Shirt", "product_type": "CLOTHING",
    "sale_price_eur": "266.39", "recommended_price": "", "available_sizes": "43,39,41", "gender": "man",
    "sku": "MRIB0001AQ043_W0800", "product_url": "https://www.baseblu.com/en-us/products/shirt-roma-4",
}


class TestProfitHelpers(unittest.TestCase):
    def test_profit_at_price(self):
        r = profit_at_price(50_000, 30_000, 0.077, apply_fixed_fee=True)
        self.assertEqual(r["fixed_fee"], 165.0)
        self.assertAlmostEqual(r["profit"], 50_000 - 3_850 - 165 - 30_000)
        self.assertEqual(profit_at_price(50_000, 30_000, 0.077, apply_fixed_fee=False)["fixed_fee"], 0)

    def test_min_price_is_minimal_and_sufficient(self):
        for cost in (5_000, 9_000, 14_000, 58_953, 71_830, 86_900, 87_100, 87_200, 120_000):
            p = min_price_for_profit(cost, 5_000, BUYMA_COMMISSION_RATE, apply_fixed_fee=True)
            self.assertEqual(p % 100, 0)
            self.assertGreaterEqual(profit_at_price(p, cost, BUYMA_COMMISSION_RATE, True)["profit"], 5_000)
            # 100 円下では足りない (下限であること)
            lower = [profit_at_price(q, cost, BUYMA_COMMISSION_RATE, True)["profit"] for q in range(100, p, 100)]
            self.assertTrue(all(x < 5_000 for x in lower), cost)

    def test_min_price_fixed_fee_boundary(self):
        # 99,900 では利益不足、100,000 は定額手数料が ¥220 に上がって不足 → 100,100
        self.assertEqual(min_price_for_profit(87_100, 5_000, 0.077, apply_fixed_fee=True), 100_100)


class TestCostBreakdown(unittest.TestCase):
    def test_matches_calculate_pricing(self):
        with mock.patch.dict(os.environ, FX_ENV):
            b = ls.cost_breakdown(CARD)
            src = get_source("baseblu")
            r = calculate_pricing(src.get_pricing_params(sale_price=196.72, category="ACCESSORIES",
                                                         title=CARD["title"]))
        self.assertEqual(b["exchange_rate"], 180.0)
        self.assertAlmostEqual(b["total_cost_jpy"], r.total_cost_jpy)
        self.assertEqual(b["target_price_jpy"], r.selling_price_jpy)
        self.assertEqual(b["proposed_price_jpy"], 80_100)
        self.assertAlmostEqual(b["profit_jpy"], profit_at_price(80_100, r.total_cost_jpy, b["commission_rate"])["profit"])
        self.assertEqual(b["min_price_jpy"], min_price_for_profit(r.total_cost_jpy, 5_000, b["commission_rate"]))
        self.assertLessEqual(b["min_price_jpy"], b["proposed_price_jpy"])
        self.assertEqual(b["landed_cost_basis"], "DDU")

    def test_missing_price_falls_back_to_target(self):
        with mock.patch.dict(os.environ, FX_ENV):
            b = ls.cost_breakdown(SHIRT)
        self.assertEqual(b["proposed_price_jpy"], b["target_price_jpy"])
        with mock.patch.dict(os.environ, FX_ENV):
            b2 = ls.cost_breakdown(SHIRT, proposed_price=90_000)
        self.assertEqual(b2["proposed_price_jpy"], 90_000)


class TestSizesAndText(unittest.TestCase):
    def test_gender_tag(self):
        self.assertEqual(extract_gender(["gender:man", "sale"]), "man")
        self.assertEqual(extract_gender("x, gender:woman"), "woman")
        self.assertEqual(extract_gender(None), "")

    def test_mens_it_sizes(self):
        self.assertEqual([map_size_to_jp_reference_for(s, "CLOTHING", "man", "Pants") for s in
                          ("44", "46", "48", "50", "52", "54")], ["XS以下", "S", "M", "L", "XL", "XXL"])

    def test_collar_sizes(self):
        self.assertTrue(is_collar_size_shirt("39", "CLOTHING", "Roma Shirt"))
        self.assertFalse(is_collar_size_shirt("39", "CLOTHING", "Logo T-shirt"))
        self.assertEqual(map_size_to_jp_reference_for("40", "CLOTHING", "man", "Roma Shirt"), "M")
        self.assertEqual(map_size_to_jp_reference_for("41", "CLOTHING", "man", "Roma Shirt"), "L")

    def test_size_rows_sorted_and_collar(self):
        rows = ls.size_rows(SHIRT)
        self.assertEqual([r["size_name"] for r in rows], ["39", "41", "43"])
        self.assertTrue(all(r["collar"] for r in rows))
        self.assertEqual([r["jp_reference"] for r in rows], ["M", "L", "XL"])

    def test_womens_shirt_is_not_collar(self):
        rows = ls.size_rows({"product_type": "CLOTHING", "gender": "woman", "title": "Cotton Shirt",
                             "available_sizes": "40,42"})
        self.assertFalse(any(r["collar"] for r in rows))
        self.assertEqual([r["size_name"] for r in rows], ["IT40", "IT42"])

    def test_denim_waist_kept_as_inches(self):
        rows = ls.size_rows({"product_type": "CLOTHING", "gender": "man", "title": "Straight Jeans",
                             "available_sizes": "30,28"})
        self.assertEqual([r["size_name"] for r in rows], ["28", "30"])
        self.assertTrue(all(r["waist"] and r["jp_reference"] == "指定なし" for r in rows))

    def test_mens_even_shirt_sizes_are_it_not_collar(self):
        rows = ls.size_rows({"product_type": "CLOTHING", "gender": "man", "title": "Oxford Shirt",
                             "available_sizes": "44,46"})
        self.assertFalse(any(r["collar"] for r in rows))
        self.assertEqual([r["jp_reference"] for r in rows], ["XS以下", "S"])

    def test_denim_jacket_is_not_waist(self):
        rows = ls.size_rows({"product_type": "CLOTHING", "gender": "woman", "title": "Denim Jacket",
                             "available_sizes": "36,38"})
        self.assertFalse(any(r["waist"] for r in rows))
        rows = ls.size_rows({"product_type": "CLOTHING", "gender": "woman", "title": "Straight Jeans",
                             "available_sizes": "40"})
        self.assertFalse(any(r["waist"] for r in rows))

    def test_sort_sizes(self):
        self.assertEqual(ls.sort_sizes(["XL", "40", "S", "38", "UNI", "M"]), ["38", "40", "S", "M", "XL", "UNI"])

    def test_gendered_category(self):
        path, note = ls.gendered_category_path(["レディースファッション", "トップス", "シャツ・ブラウス"], "man")
        self.assertEqual(path, ["メンズファッション", "トップス", "シャツ"])
        self.assertTrue(note)
        path, note = ls.gendered_category_path(["レディースファッション", "トップス"], "woman")
        self.assertEqual(path, ["レディースファッション", "トップス"])
        self.assertEqual(note, "")

    def test_materials(self):
        self.assertEqual(ls.materials_ja("Composition: GENERAL 95% Fleece Wool Ovis Aries 5% Elastane"),
                         "ウール 95% / エラスタン 5%")
        self.assertEqual(ls.materials_ja("Composition: 100% Calf Leather Bos Taurus"), "カーフレザー 100%")
        self.assertEqual(ls.materials_ja("no info"), "")

    def test_suggest_title(self):
        self.assertEqual(ls.suggest_title("ETRO シャツ", "シャツ"), "ETRO シャツ")
        self.assertEqual(ls.suggest_title("MAISON MARGIELA Card Holder", "カードケース"),
                         "MAISON MARGIELA Card Holder カードケース")
        self.assertEqual(ls.suggest_title("X" * 58, "カードケース"), "X" * 58)


class TestBuildSheet(unittest.TestCase):
    def _sheet(self, product=CARD, rank=1):
        with mock.patch.dict(os.environ, FX_ENV):
            b = ls.cost_breakdown(product)
        sheet = ls.build_sheet(
            product, key="baseblu-SA3VX0007P4455_T8013", title="MAISON MARGIELA カードケース",
            comment="コメント", category_path=["レディースファッション", "財布・小物", "カードケース・名刺入れ"],
            color_family="ブラック", color_name="Black", tags=[], brand_info={"name": "MAISON MARGIELA"},
            breakdown=b, purchase_memo="memo", today=date(2026, 10, 8), rank=rank)
        return sheet, b

    def test_fields_and_actions(self):
        sheet, b = self._sheet()
        by_label = {f.label: f for f in sheet.fields}
        self.assertEqual(by_label["商品名"].action, ls.ACTION_INPUT)
        for label in ("カテゴリ (第1 > 第2 > 第3)", "ブランド", "配送方法", "買付地", "発送地", "色の系統"):
            self.assertEqual(by_label[label].action, ls.ACTION_SELECT, label)
        self.assertEqual(by_label["販売価格 (提案)"].action, ls.ACTION_CHECK)
        self.assertEqual(by_label["購入期限"].value, "2027/01/06")
        self.assertEqual(by_label["品番"].value, "SA3VX0007P4455")
        self.assertEqual(by_label["買付地"].value, "ヨーロッパ > イタリア")
        self.assertEqual(by_label["買付先 URL"].value, CARD["product_url"])
        self.assertIn("buyma.com/r/", by_label["BUYMA 検索 (ブランド + 商品名)"].value)
        self.assertEqual(sheet.summary["proposed_price_jpy"], 80_100)
        self.assertTrue(any("VAT" in a and "未確認" in a for a in sheet.assumptions))
        sections = [f.section for f in sheet.fields]
        self.assertEqual(sections[0], "1. 商品画像")
        self.assertEqual(sections[-1], "16. 保存")

    def test_sizeless_accessory_is_single_one_size(self):
        # Default Title (サイズ表記なし) の小物: 候補選定と同じく「バリエーションなし」で出す
        sheet, _ = self._sheet({**CARD, "available_sizes": "", "sizes": "", "priced_out_sizes": ""})
        f = {x.label: x for x in sheet.fields}["サイズ"]
        self.assertEqual(f.value, "バリエーションなし (サイズ表記なし)")
        self.assertEqual(f.action, ls.ACTION_SELECT)
        # サイズの軸があるのに在庫ありサイズが無い = 売切 → 出さない
        sheet, _ = self._sheet({**CARD, "available_sizes": "", "sizes": "UNI"})
        self.assertEqual({x.label: x for x in sheet.fields}["サイズ"].value, "(出品できるサイズなし)")

    def test_renderers(self):
        sheet, b = self._sheet()
        md = ls.to_markdown(sheet, b, "2026-10-08 07:00")
        self.assertIn("MAISON MARGIELA", md)
        self.assertIn(ls.BUYMA_LISTING_FORM_URL, md)
        html = ls.to_html([(sheet, b)], "2026-10-08 07:00")
        self.assertIn("<html", html.lower())
        self.assertIn("Leather Card Holder", html)
        rows = list(csv.DictReader(io.StringIO(ls.to_csv([sheet]))))
        self.assertEqual(tuple(rows[0].keys()), ls.CSV_COLUMNS)
        self.assertEqual(len(rows), len(sheet.fields))


class TestBuildSheetsEligibility(unittest.TestCase):
    def test_low_but_sufficient_profit_is_not_rejected_by_auto_listing_rule(self):
        """自動出品用の『利益 ¥10,000 か 15%』基準ではなく --min-profit (再計算した利益) で判定する。"""
        import generate_listing_sheet as gls
        p = {**CARD, "image_url": "https://cdn.example/a.jpg", "profit_jpy": "4000", "expected_margin_pct": "5"}
        with mock.patch.dict(os.environ, FX_ENV):
            b = ls.cost_breakdown(p)
            price = min_price_for_profit(b["total_cost_jpy"], 5_000, b["commission_rate"])
            p["recommended_price"] = str(price)          # 利益 ¥5,000 ちょうど付近
            sheets, skipped = gls.build_sheets([p], limit=3, min_profit=5_000, deadline_days=90,
                                               today=date(2026, 10, 8))
        self.assertEqual(len(sheets), 1, skipped)
        self.assertGreaterEqual(sheets[0][1]["profit_jpy"], 5_000)
        self.assertLess(sheets[0][1]["profit_jpy"], 10_000)

    def test_content_blocker_still_rejects(self):
        import generate_listing_sheet as gls
        p = {**CARD, "image_url": ""}
        with mock.patch.dict(os.environ, FX_ENV):
            sheets, skipped = gls.build_sheets([p], limit=3, min_profit=5_000, deadline_days=90)
        self.assertEqual(sheets, [])
        self.assertIn("メイン画像なし", skipped[0][1])


class TestRecordListings(unittest.TestCase):
    def test_record_appends_draft_rows(self):
        import generate_listing_sheet as gls
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / gls.MANIFEST_NAME
            manifest.write_text(json.dumps({"generated_at": "x", "items": [
                {"rank": 1, "key": "baseblu-K1", "proposed_price_jpy": 80100,
                 "product": {k: CARD[k] for k in gls.MANIFEST_PRODUCT_KEYS if k in CARD}},
            ]}), encoding="utf-8")
            n = gls.record_listings(["1=133231149", "baseblu-K1=133231150@78000", "1=abc", "9=1",
                                     "1=133231151@abc", "1=133231152@0"],
                                    manifest, reports_dir=Path(d), now=datetime(2026, 10, 8, 9, 0))
            self.assertEqual(n, 2)
            out = Path(d) / "2026-10-08_auto_listing_results.csv"
            rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
        self.assertEqual([r["item_id"] for r in rows], ["133231149", "133231150"])
        self.assertTrue(all(r["status"] == "draft" for r in rows))
        prices = [v for r in rows for k, v in r.items() if "price" in k]
        self.assertIn("80100", prices)
        self.assertIn("78000", prices)


if __name__ == "__main__":
    unittest.main()
