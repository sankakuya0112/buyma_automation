"""scripts/select_listing_candidates.py (在庫の取り直し・再計算・次点補充) のテスト。ネットワークには触れない。"""

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import select_listing_candidates as slc  # noqa: E402
from app.core.pricing import calculate_pricing  # noqa: E402
from app.core.sources import get_source  # noqa: E402

FX_ENV = {"EUR_TO_JPY": "180", "FX_BUFFER_PCT": "0", "BUYMA_FIXED_FEE_ENABLED": "1"}


def _row(**kw):
    base = {"title": "Leather Card Holder", "vendor": "MAISON MARGIELA", "product_type": "ACCESSORIES",
            "sku": "SA3VX0007P4455_T8013", "color": "", "available_sizes": "UNI", "sale_price_eur": "196.72",
            "original_price_eur": "327.87", "source_name": "baseblu", "action": "list",
            "total_cost_jpy": "58000", "expected_profit_jpy": "14000", "selling_price_jpy": "79000",
            "product_url": "https://www.baseblu.com/en-us/products/card-holder-134",
            "opportunity_score": "0.9", "market_median_jpy": "90000"}
    base.update(kw)
    return base


class TestReprice(unittest.TestCase):
    def test_reprice_recomputes_and_invalidates(self):
        with mock.patch.dict(os.environ, FX_ENV):
            out = slc.reprice(_row(), 150.0)
            r = calculate_pricing(get_source("baseblu").get_pricing_params(
                sale_price=150.0, category="ACCESSORIES", title="Leather Card Holder"))
        self.assertEqual(out["sale_price_eur"], 150.0)
        self.assertEqual(out["total_cost_jpy"], round(r.total_cost_jpy))
        self.assertEqual(out["buyma_commission_jpy"], round(r.buyma_commission_jpy))
        self.assertEqual(out["market_median_jpy"], "")
        self.assertEqual(out["opportunity_score"], "")
        self.assertAlmostEqual(out["discount_rate"], round((1 - 150 / 327.87) * 100, 1))
        self.assertTrue(out["repriced_note"])


class TestRefreshRow(unittest.TestCase):
    def test_unknown_color_with_color_variants_is_excluded(self):
        snap = {"has_color": True, "variants": []}
        with mock.patch("app.utils.supplier_stock.fetch_product_snapshot", return_value=snap), \
                mock.patch.object(slc.time, "sleep"):
            new, note = slc.refresh_row(_row(color=""), 0)
        self.assertIsNone(new)
        self.assertIn("色", note)


class TestRefreshPool(unittest.TestCase):
    def test_sold_out_top_candidate_is_replaced_and_requests_bounded(self):
        rows = [
            _row(title="A", sku="A1_1", expected_profit_jpy="20000"),
            _row(title="B", sku="B1_1", expected_profit_jpy="19000"),
            _row(title="C", sku="C1_1", expected_profit_jpy="18000"),
            _row(title="D", sku="D1_1", expected_profit_jpy="17000"),
        ]
        calls = []

        def fake_refresh(row, delay):
            calls.append(row["title"])
            return (None, "売切") if row["title"] == "A" else (row, "in_stock")

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.csv"
            with src.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            out = Path(d) / "out.csv"
            with mock.patch.object(slc, "refresh_row", side_effect=fake_refresh):
                slc.main(["--csv", str(src), "--limit", "2", "--max-per-brand", "2", "--refresh",
                          "--delay", "0", "--out", str(out)])
            picked = list(csv.DictReader(out.open(encoding="utf-8-sig")))
        self.assertEqual([r["title"] for r in picked], ["B", "C"])
        self.assertEqual(calls, ["A", "B", "C"])          # D は確認しない

    def test_refresh_with_limit_zero_means_unlimited(self):
        rows = [_row(title="A", sku="A1_1"), _row(title="B", sku="B1_1")]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.csv"
            with src.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            out = Path(d) / "out.csv"
            with mock.patch.object(slc, "refresh_row", side_effect=lambda r, d: (r, "in_stock")):
                slc.main(["--csv", str(src), "--limit", "0", "--refresh", "--delay", "0", "--out", str(out)])
            self.assertEqual(len(list(csv.DictReader(out.open(encoding="utf-8-sig")))), 2)


if __name__ == "__main__":
    unittest.main()
