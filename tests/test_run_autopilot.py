"""scripts/run_autopilot.py のテスト: 工程組み立て・モック CSV・集計。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import run_autopilot as ap  # noqa: E402


def _args(**kw) -> Namespace:
    base = dict(source="baseblu", skip_scrape=False, skip_market=False, market_limit=None,
                ai_limit=30, no_ai=False, draft=0, weekly_review=False, test=False, dry_run=False)
    base.update(kw)
    return Namespace(**base)


class BuildStepsTest(unittest.TestCase):
    def _names(self, **kw):
        return [s["name"] for s in ap.build_steps(_args(**kw))]

    def test_default_full_pipeline(self):
        names = self._names()
        self.assertTrue(names[0].startswith("①"))
        self.assertTrue(any(n.startswith("③") for n in names))
        self.assertTrue(any(n.startswith("④") for n in names))
        self.assertTrue(any(n.startswith("⑤") for n in names))
        self.assertFalse(any(n.startswith("⑥") for n in names))
        self.assertTrue(names[-1].startswith("⑧"))

    def test_test_mode_uses_mock_and_no_network_steps(self):
        names = self._names(test=True, draft=2)
        self.assertTrue(names[0].startswith("⓪"))
        self.assertFalse(any(n.startswith("①") or n.startswith("③") or n.startswith("⑥") for n in names))

    def test_no_ai_removes_ai_steps(self):
        names = self._names(no_ai=True)
        self.assertFalse(any("AI" in n for n in names))

    def test_draft_and_review_flags(self):
        steps = ap.build_steps(_args(draft=3, weekly_review=True, skip_scrape=True, skip_market=True))
        names = [s["name"] for s in steps]
        self.assertFalse(any(n.startswith("①") or n.startswith("③") for n in names))
        draft = next(s for s in steps if s["name"].startswith("⑥"))
        self.assertIn("--draft", draft["cmd"])
        self.assertEqual(draft["cmd"][draft["cmd"].index("--limit") + 1], "3")
        self.assertIn("--yes", draft["cmd"])
        self.assertTrue(any(s.get("resolver") == "weekly_review" for s in steps))

    def test_baseblu_uses_dedicated_scraper(self):
        """baseblu は商品ページ HTML から色を取る専用スクリプトを使い続ける。"""
        steps = ap.build_steps(_args())
        scrape = next(s for s in steps if s["name"].startswith("①"))
        self.assertTrue(scrape["cmd"][1].endswith("baseblu_sales_to_csv.py"))
        filt = next(s for s in steps if s["name"].startswith("②"))
        self.assertEqual(filt["cmd"][-2:], ["--source", "baseblu"])

    def test_other_source_uses_generic_scraper(self):
        steps = ap.build_steps(_args(source="antonioli"))
        scrape = next(s for s in steps if s["name"].startswith("①"))
        self.assertTrue(scrape["cmd"][1].endswith("shopify_sales_to_csv.py"))
        self.assertEqual(scrape["cmd"][-2:], ["--source", "antonioli"])
        filt = next(s for s in steps if s["name"].startswith("②"))
        self.assertEqual(filt["cmd"][-2:], ["--source", "antonioli"])

    def test_market_filter_step_carries_source(self):
        steps = ap.build_steps(_args(source="antonioli"))
        market_step = next(s for s in steps if s.get("resolver") == "filter_with_market")
        self.assertEqual(market_step["source"], "antonioli")

    def test_missing_source_attribute_defaults_to_baseblu(self):
        """古い呼び出し (source 属性なし) でも落ちない。"""
        args = _args()
        del args.source
        scrape = next(s for s in ap.build_steps(args) if s["name"].startswith("①"))
        self.assertTrue(scrape["cmd"][1].endswith("baseblu_sales_to_csv.py"))

    def test_ai_limit_and_market_limit_propagate(self):
        steps = ap.build_steps(_args(ai_limit=7, market_limit=5))
        enrich = next(s for s in steps if s["name"].startswith("⑤"))
        self.assertEqual(enrich["cmd"][-1], "7")
        market = next(s for s in steps if s["name"].startswith("③"))
        self.assertEqual(market["cmd"][-1], "5")


class MockAndSummaryTest(unittest.TestCase):
    def test_mock_csv_uses_source_name(self):
        tmp = Path(tempfile.mkdtemp())
        with patch.object(ap, "REPORTS", tmp):
            path = ap.write_mock_sales_csv(source="antonioli")
        self.assertTrue(path.name.endswith("_antonioli_sales_products_sorted.csv"))
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(all(r["source_name"] == "antonioli" for r in rows))

    def test_mock_csv_matches_scraper_columns(self):
        tmp = Path(tempfile.mkdtemp()) / "mock.csv"
        ap.write_mock_sales_csv(tmp)
        with open(tmp, newline="", encoding="utf-8-sig") as f:
            r = csv.DictReader(f)
            fields = r.fieldnames
            rows = list(r)
        for col in ("title", "vendor", "sale_price", "available", "source_name", "currency", "landed_cost_basis"):
            self.assertIn(col, fields)
        self.assertEqual(len(rows), len(ap.MOCK_SALES_ROWS))
        self.assertTrue(any(r["available"] == "false" for r in rows))

    def test_summarize_pipeline_reads_latest_files(self):
        tmp = Path(tempfile.mkdtemp())
        with patch.object(ap, "REPORTS", tmp):
            ap.write_mock_sales_csv(tmp / "2026-01-01_baseblu_sales_products_sorted.csv")
            with open(tmp / "2026-01-01_baseblu_profitable_products.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["vendor", "action", "final_price_jpy", "expected_profit_jpy",
                                                  "competition_level", "ai_verdict"])
                w.writeheader()
                w.writerow({"vendor": "GUCCI", "action": "list", "final_price_jpy": "100000",
                            "expected_profit_jpy": "20000", "competition_level": "high", "ai_verdict": "list"})
                w.writerow({"vendor": "PRADA", "action": "list", "final_price_jpy": "50000",
                            "expected_profit_jpy": "9000", "competition_level": "low", "ai_verdict": "hold"})
                w.writerow({"vendor": "X", "action": "skip", "final_price_jpy": "", "expected_profit_jpy": "",
                            "competition_level": "", "ai_verdict": ""})
            s = ap.summarize_pipeline()
        self.assertEqual(s["sourced_total"], len(ap.MOCK_SALES_ROWS))
        self.assertEqual(s["listable"], 2)
        self.assertEqual(s["median_final_price_jpy"], 100000)
        self.assertEqual(s["competition_levels"], {"high": 1, "low": 1})
        self.assertEqual(s["ai_verdicts"], {"list": 1, "hold": 1})
        self.assertEqual(s["top_brands"], {"GUCCI": 1, "PRADA": 1})

    def test_dry_run_main_exits_zero(self):
        self.assertEqual(ap.main(["--dry-run", "--draft", "1", "--weekly-review"]), 0)


if __name__ == "__main__":
    unittest.main()
