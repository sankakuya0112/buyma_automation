"""check_inventory / update_listed_prices が出品結果 CSV を読む部分のテスト。

2026-09-24: buyma_auto_listing.py の結果 CSV に product_url が無く、両スクリプトが
仕入先ハンドルを取れずに全件失敗していた。新形式 (product_url あり) は読め、
旧形式 (product_url なし) は件数表示付きで除外されることを確認する。
"""

from __future__ import annotations

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.utils.listing_helpers import RESULT_FIELDNAMES, build_result_row  # noqa: E402
import check_inventory  # noqa: E402
import update_listed_prices  # noqa: E402

LEGACY_FIELDS = ["status", "item_id", "title", "vendor", "price", "processed_at"]
URL = "https://www.baseblu.com/en-us/products/gucci-leather-tote"


def _write(path: Path, fieldnames, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _new_row(item_id, status="draft", url=URL):
    product = {"title": "Leather Tote", "vendor": "GUCCI", "recommended_price": "70800",
               "sku": "ABC", "product_type": "BAGS", "product_url": url, "source_name": "baseblu"}
    return build_result_row(product, status, item_id, "2026-09-24 09:00:00")


class ReadersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # 旧形式 (2026-04): product_url 列なし
        _write(self.tmp / "2026-04-08_auto_listing_results.csv", LEGACY_FIELDS, [
            {"status": "draft", "item_id": "100", "title": "Old", "vendor": "X", "price": "1", "processed_at": "t"},
        ])
        # 新形式: 下書き 2 件 + エラー 1 件 (エラーは対象外)
        _write(self.tmp / "2026-09-24_auto_listing_results.csv", RESULT_FIELDNAMES, [
            _new_row("201"), _new_row("202", status="published"), _new_row("", status="error"),
        ])
        self.glob = self.tmp / "*_auto_listing_results.csv"

    def _capture(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn()
        return out, buf.getvalue()

    def test_check_inventory_keeps_rows_with_handle_and_reports_legacy(self):
        with patch.object(check_inventory, "RESULTS_GLOB", self.glob):
            rows, printed = self._capture(check_inventory.load_all_listing_results)
        self.assertEqual(sorted(r["item_id"] for r in rows), ["201", "202"])
        self.assertTrue(all(check_inventory.extract_handle(r["product_url"]) == "gucci-leather-tote" for r in rows))
        self.assertIn("旧形式", printed)
        self.assertIn("1 件", printed)

    def test_update_listed_prices_keeps_rows_with_handle_and_reports_legacy(self):
        with patch.object(update_listed_prices, "RESULTS_GLOB", self.glob):
            rows, printed = self._capture(update_listed_prices.load_listing_records)
        self.assertEqual(sorted(r["item_id"] for r in rows), ["201", "202"])
        self.assertIn("旧形式", printed)

    def test_no_notice_when_all_rows_are_new_format(self):
        (self.tmp / "2026-04-08_auto_listing_results.csv").unlink()
        with patch.object(check_inventory, "RESULTS_GLOB", self.glob):
            rows, printed = self._capture(check_inventory.load_all_listing_results)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("旧形式", printed)


if __name__ == "__main__":
    unittest.main()
