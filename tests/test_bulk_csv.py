"""BUYMA 公式一括出品 CSV (items.csv + colorsizes.csv の zip) の生成テスト。

常に「下書き」しか書かないこと、ID 表が未設定なら推測せず空欄にすること、
在庫あり・基準価格のサイズだけ colorsizes に載ることを確認する。
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core import bulk_csv as bc  # noqa: E402
import generate_bulk_upload as gbu  # noqa: E402

PRODUCT = {
    "title": "Leather Ankle Boots", "vendor": "GUCCI", "sku": "443497 DTDIT", "product_type": "FOOTWEAR",
    "recommended_price": "98000", "profit_jpy": "12000", "total_cost_jpy": "80000", "sale_price_eur": "400",
    "currency": "EUR", "color": "Black", "sizes": "36, 37, 38, 39", "available_sizes": "37, 38",
    "priced_out_sizes": "39", "description_en": "Calfskin leather. Made in Italy.",
    "image_url": "https://cdn.example.com/a.jpg", "sub_images": "https://cdn.example.com/b.jpg|//cdn.example.com/c.png",
    "product_url": "https://www.baseblu.com/en-us/products/gucci-boots", "source_name": "baseblu",
}


def _read_zip(path):
    with zipfile.ZipFile(path) as zf:
        names = sorted(zf.namelist())
        data = {n: list(csv.DictReader(io.StringIO(zf.read(n).decode("utf-8")))) for n in names}
    return names, data


class IdTableTest(unittest.TestCase):
    def test_repo_tables_are_placeholders(self):
        t = bc.load_id_tables(PROJECT_ROOT / "data" / "buyma_id_tables")
        self.assertEqual(sorted(t.placeholders), sorted(bc.ID_TABLE_FILES))
        self.assertEqual(t.lookup("brands", "GUCCI"), "")

    def test_real_table_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "brands.json").write_text(json.dumps({"_placeholder": False, "entries": {"Gucci": 99}}))
            t = bc.load_id_tables(tmp)
        self.assertEqual(t.lookup("brands", "GUCCI"), "99")
        self.assertIn("categories", t.placeholders)


class RowTest(unittest.TestCase):
    def setUp(self):
        self.tables = bc.IdTables()

    def test_item_row_is_draft_and_leaves_unknown_ids_blank(self):
        warn = []
        row = bc.build_item_row(PRODUCT, title="【GUCCI】 Boots", comment="c", category_path=["a", "b", "c"],
                                tables=self.tables, warnings=warn)
        self.assertEqual(row["コントロール"], "下書き")
        self.assertNotIn("商品ID", row)
        self.assertEqual(row["ブランド"], "")
        self.assertEqual(row["ブランド名"], "GUCCI")
        self.assertEqual(row["カテゴリ"], "")
        self.assertEqual(row["単価"], "98000")
        self.assertEqual(row["買付可数量"], "1")
        self.assertEqual(row["商品イメージ3"], "https://cdn.example.com/c.png")
        self.assertEqual(row["ブランド型番1"], "443497 DTDIT")
        self.assertIn("39", row["出品メモ"])
        self.assertTrue(any("ブランド ID 未設定" in w for w in warn))
        self.assertTrue(any("配送方法" in w for w in warn))

    def test_management_number(self):
        self.assertEqual(bc.management_number(PRODUCT), "baseblu-443497-DTDIT")
        self.assertEqual(bc.management_number({"source_name": "x", "product_url": "https://a/products/h-1"}), "x-h-1")

    def test_colorsizes_without_color_table(self):
        warn = []
        rows = bc.build_colorsize_rows(PRODUCT, sizes=["37", "38"], color_family_ja="ブラック",
                                       color_name="Black", tables=self.tables, warnings=warn)
        self.assertEqual([r["並び順"] for r in rows], ["1", "2"])
        self.assertEqual({r["色名称"] for r in rows}, {"色指定なし"})
        self.assertEqual({r["色系統"] for r in rows}, {"0"})
        self.assertEqual({r["在庫ステータス"] for r in rows}, {"1"})

    def test_colorsizes_with_color_table(self):
        t = bc.IdTables(tables={"color_families": {"ブラック": "1"}})
        rows = bc.build_colorsize_rows(PRODUCT, sizes=["37"], color_family_ja="ブラック",
                                       color_name="Black", tables=t, warnings=[])
        self.assertEqual((rows[0]["色名称"], rows[0]["色系統"]), ("Black", "1"))


class ValidateAndWriteTest(unittest.TestCase):
    def _rows(self):
        warn = []
        item = bc.build_item_row(PRODUCT, title="t", comment="c", category_path="x", tables=bc.IdTables(), warnings=warn)
        cs = bc.build_colorsize_rows(PRODUCT, sizes=["37", "38"], color_family_ja="", color_name="",
                                     tables=bc.IdTables(), warnings=warn)
        return [item], cs

    def test_publish_control_rejected(self):
        items, cs = self._rows()
        for bad in ("公開", "停止", "削除", ""):
            items[0]["コントロール"] = bad
            self.assertTrue(bc.validate_rows(items, cs), bad)

    def test_item_id_rejected_for_new(self):
        items, cs = self._rows()
        items[0]["商品ID"] = "123"
        self.assertTrue(bc.validate_rows(items, cs))

    def test_write_zip(self):
        items, cs = self._rows()
        with tempfile.TemporaryDirectory() as tmp:
            path = bc.write_bulk_zip(items, cs, Path(tmp) / "x.zip")
            names, data = _read_zip(path)
        self.assertEqual(names, ["colorsizes.csv", "items.csv"])
        self.assertEqual(data["items.csv"][0]["コントロール"], "下書き")
        self.assertNotIn("商品ID", data["items.csv"][0])
        self.assertNotIn("ブランド", data["items.csv"][0])    # 全行空の ID 列は省く
        self.assertEqual(len(data["colorsizes.csv"]), 2)

    def test_write_refuses_invalid(self):
        items, cs = self._rows()
        items[0]["コントロール"] = "公開"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            bc.write_bulk_zip(items, cs, Path(tmp) / "x.zip")

    def test_template_order_and_sjis(self):
        items, cs = self._rows()
        tmpl = ["コントロール", "商品管理番号", "商品名", "単価", "買付可数量", "商品ID"]
        warn = []
        with tempfile.TemporaryDirectory() as tmp:
            path = bc.write_bulk_zip(items, cs, Path(tmp) / "x.zip", encoding="sjis",
                                     items_template=tmpl, warnings=warn)
            with zipfile.ZipFile(path) as zf:
                header = zf.read("items.csv").decode("cp932").splitlines()[0]
        self.assertEqual(header, "コントロール,商品管理番号,商品名,単価,買付可数量")
        self.assertTrue(any("テンプレートに無い列" in w for w in warn))


class TemplateRequiredColumnsTest(unittest.TestCase):
    def test_template_dropping_required_colorsizes_column_fails(self):
        warn = []
        item = bc.build_item_row(PRODUCT, title="t", comment="c", category_path="x", tables=bc.IdTables(), warnings=warn)
        cs = bc.build_colorsize_rows(PRODUCT, sizes=["37"], color_family_ja="", color_name="",
                                     tables=bc.IdTables(), warnings=warn)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            bc.write_bulk_zip([item], cs, Path(tmp) / "x.zip", colorsizes_template=["サイズ名称"])


class ScriptTest(unittest.TestCase):
    def test_prepare_uses_listable_sizes_only(self):
        with contextlib.redirect_stdout(io.StringIO()):
            res = gbu.prepare([dict(PRODUCT)], bc.IdTables(), include_review=True)
        self.assertEqual(len(res["items"]), 1)
        sizes = [r["サイズ名称"] for r in res["colorsizes"]]
        self.assertEqual(len(sizes), 2)            # 37, 38 (39 は高いので除外、36 は在庫なし)
        self.assertEqual(res["manifest"][0]["available_sizes"], "37,38")

    def test_prepare_skips_when_only_priced_out_sizes(self):
        p = {**PRODUCT, "available_sizes": "", "priced_out_sizes": "39"}
        with contextlib.redirect_stdout(io.StringIO()):
            res = gbu.prepare([p], bc.IdTables(), include_review=True)
        self.assertEqual(res["items"], [])
        self.assertTrue(res["skipped"])

    def test_include_review_never_includes_ng(self):
        ng = {**PRODUCT, "image_url": "", "sub_images": ""}     # メイン画像なし = NG
        with contextlib.redirect_stdout(io.StringIO()):
            res = gbu.prepare([ng], bc.IdTables(), include_review=True)
        self.assertEqual(res["items"], [])
        self.assertIn("NG", res["skipped"][0][1])

    def test_import_ids_rejects_ambiguous_and_uses_actual_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bulk").mkdir()
            (tmp / "reports").mkdir()
            base = {"management_number": "m-1", "title": "A", "vendor": "V", "recommended_price": "1000",
                    "product_url": PRODUCT["product_url"], "source_name": "baseblu", "available_sizes": "S"}
            (tmp / "bulk" / "1_buyma_bulk_manifest.json").write_text(json.dumps({"items": [base]}), encoding="utf-8")
            (tmp / "bulk" / "2_buyma_bulk_manifest.json").write_text(
                json.dumps({"items": [{**base, "available_sizes": "S,M"}]}), encoding="utf-8")
            dl = tmp / "items.csv"
            dl.write_text("商品ID,商品管理番号,単価\n134000009,m-1,1200\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gbu.import_ids(str(dl), tmp / "bulk", tmp / "reports"), 0)   # 曖昧
                n = gbu.import_ids(str(dl), tmp / "bulk", tmp / "reports",
                                   manifest=str(tmp / "bulk" / "2_buyma_bulk_manifest.json"))
            files = list((tmp / "reports").glob("*_auto_listing_results.csv"))
            with open(files[0], encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(n, 1)
        self.assertEqual(rows[0]["price"], "1200")          # BUYMA 上の実際の単価
        self.assertEqual(rows[0]["listed_sizes"], "S,M")

    def test_import_ids_appends_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bulk").mkdir()
            (tmp / "reports").mkdir()
            (tmp / "bulk" / "1_buyma_bulk_manifest.json").write_text(json.dumps(
                {"items": [{"management_number": "baseblu-443497-DTDIT", "title": "Boots",
                            "vendor": "GUCCI", "recommended_price": "98000", "sku": "443497 DTDIT",
                            "product_type": "FOOTWEAR", "product_url": PRODUCT["product_url"],
                            "source_name": "baseblu", "available_sizes": "37,38"}]}), encoding="utf-8")
            dl = tmp / "items.csv"
            dl.write_text("商品ID,商品管理番号,コントロール\n134000001,baseblu-443497-DTDIT,下書き\n,other,下書き\n",
                          encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                n = gbu.import_ids(str(dl), tmp / "bulk", tmp / "reports")
            files = list((tmp / "reports").glob("*_auto_listing_results.csv"))
            with open(files[0], encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(n, 1)
        self.assertEqual(rows[0]["item_id"], "134000001")
        self.assertEqual(rows[0]["listed_sizes"], "37,38")
        self.assertEqual(rows[0]["source_name"], "baseblu")


if __name__ == "__main__":
    unittest.main()
