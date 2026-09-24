"""app/utils/reports.py (outputs/reports の最新ファイル解決) のテスト。

2026-09-24: 各スクリプトが baseblu 固定の glob を持ち、他仕入先や同日 2 仕入先の
実行で違う表を読んでいた。仕入先で絞れること、同日は更新時刻で決まることを確認する。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.reports import REPORTS_DIR, latest_report, list_reports, report_glob  # noqa: E402


def _touch(path: Path, mtime: float) -> None:
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


class ReportGlobTest(unittest.TestCase):
    def test_pattern_with_and_without_source(self):
        self.assertEqual(report_glob("profitable_products.csv"), "*_profitable_products.csv")
        self.assertEqual(report_glob("profitable_products.csv", "Antonioli "), "*_antonioli_profitable_products.csv")
        self.assertEqual(report_glob("market_prices.json", ""), "*_market_prices.json")


class LatestReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        now = time.time()
        _touch(self.tmp / "2026-09-23_baseblu_profitable_products.csv", now - 300)
        _touch(self.tmp / "2026-09-24_baseblu_profitable_products.csv", now - 200)
        _touch(self.tmp / "2026-09-24_antonioli_profitable_products.csv", now - 100)  # 同日・後に書かれた
        _touch(self.tmp / "2026-09-24_market_prices.json", now - 50)

    def test_source_filter_selects_that_supplier(self):
        self.assertTrue(latest_report("profitable_products.csv", "baseblu", self.tmp)
                        .endswith("2026-09-24_baseblu_profitable_products.csv"))
        self.assertTrue(latest_report("profitable_products.csv", "antonioli", self.tmp)
                        .endswith("2026-09-24_antonioli_profitable_products.csv"))

    def test_same_day_tie_breaks_by_mtime_not_name(self):
        # 名前順なら baseblu > antonioli だが、後に書かれた antonioli を選ぶ
        self.assertTrue(latest_report("profitable_products.csv", None, self.tmp)
                        .endswith("2026-09-24_antonioli_profitable_products.csv"))

    def test_date_prefix_wins_over_mtime(self):
        now = time.time()
        _touch(self.tmp / "2026-09-01_baseblu_profitable_products.csv", now)  # 古い日付を今触った
        self.assertTrue(latest_report("profitable_products.csv", "baseblu", self.tmp)
                        .endswith("2026-09-24_baseblu_profitable_products.csv"))

    def test_kind_without_source_segment(self):
        self.assertTrue(latest_report("market_prices.json", None, self.tmp).endswith("2026-09-24_market_prices.json"))

    def test_missing_returns_none_and_list_is_oldest_first(self):
        self.assertIsNone(latest_report("profitable_products.csv", "slamjam", self.tmp))
        self.assertIsNone(latest_report("nothing.csv", None, Path(tempfile.mkdtemp())))
        names = [os.path.basename(p) for p in list_reports("profitable_products.csv", "baseblu", self.tmp)]
        self.assertEqual(names, ["2026-09-23_baseblu_profitable_products.csv",
                                 "2026-09-24_baseblu_profitable_products.csv"])

    def test_default_dir_is_outputs_reports(self):
        self.assertEqual(REPORTS_DIR, PROJECT_ROOT / "outputs" / "reports")


if __name__ == "__main__":
    unittest.main()
