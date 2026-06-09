"""audit_pricing.py のレガシー CSV (USD 列のみ) 対応をテストする。

Phase 2a 以前の filter_baseblu_profitable.py が出力していた
sale_price_jpy / suggested_buyma_price_jpy / estimated_profit_jpy 列のみの
CSV でも、新フィールドにマップして集計が成立することを保証する。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import audit_pricing  # noqa: E402


class LegacyNormalizationTest(unittest.TestCase):
    def test_legacy_columns_mapped(self):
        legacy_row = {
            "title": "Foo Bag",
            "vendor": "BENEDETTA BRUZZICHES",
            "sale_price_jpy": "294008",
            "shipping_jpy": "3000",
            "customs_jpy": "29701",
            "consumption_tax_jpy": "32671",
            "total_cost_jpy": "359380",
            "suggested_buyma_price_jpy": "422800",
            "estimated_profit_jpy": "63420",
        }
        out = audit_pricing._normalize_legacy_row(legacy_row)

        self.assertEqual(out["source_price_jpy"], "294008")
        self.assertEqual(out["selling_price_jpy"], "422800")
        self.assertEqual(out["profit_jpy"], "63420")
        # margin_pct = 63420 / 422800 * 100 = 15.0%
        self.assertIn("margin_pct", out)
        self.assertAlmostEqual(float(out["margin_pct"]), 15.0, places=1)

    def test_new_columns_preserved(self):
        """新スキーマの CSV では legacy 値で上書きしない。"""
        new_row = {
            "selling_price_jpy": "100000",
            "suggested_buyma_price_jpy": "200000",  # 旧形式の値
            "profit_jpy": "20000",
            "estimated_profit_jpy": "40000",
            "margin_pct": "20.0",
        }
        out = audit_pricing._normalize_legacy_row(new_row)
        self.assertEqual(out["selling_price_jpy"], "100000")
        self.assertEqual(out["profit_jpy"], "20000")
        self.assertEqual(out["margin_pct"], "20.0")

    def test_margin_skips_when_zero_sell(self):
        out = audit_pricing._normalize_legacy_row({
            "sale_price_jpy": "100",
            "suggested_buyma_price_jpy": "0",
            "estimated_profit_jpy": "0",
        })
        # 0 除算回避: margin_pct は付与されない
        self.assertNotIn("margin_pct", out)

    def test_load_rows_returns_normalized(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig") as f:
            f.write("title,sale_price_jpy,suggested_buyma_price_jpy,estimated_profit_jpy,total_cost_jpy\n")
            f.write("Foo,100000,150000,30000,120000\n")
            f.write("Bar,200000,250000,20000,230000\n")
            path = f.name

        try:
            rows = audit_pricing.load_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["selling_price_jpy"], "150000")
            self.assertEqual(rows[1]["profit_jpy"], "20000")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
