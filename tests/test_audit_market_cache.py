"""scripts/audit_market_cache.py のユニットテスト。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# scripts/ を package 化していないため importlib で直接ロード
_spec = importlib.util.spec_from_file_location(
    "audit_market_cache",
    PROJECT_ROOT / "scripts" / "audit_market_cache.py",
)
audit_market_cache = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_market_cache)

is_suspicious_price = audit_market_cache.is_suspicious_price
classify_entry = audit_market_cache.classify_entry
re_evaluate = audit_market_cache.re_evaluate


class TestIsSuspiciousPrice(unittest.TestCase):
    def test_25980_in_band(self):
        self.assertTrue(is_suspicious_price(25980))

    def test_30000_in_band(self):
        self.assertTrue(is_suspicious_price(30000))

    def test_165000_safe(self):
        self.assertFalse(is_suspicious_price(165000))

    def test_lower_boundary(self):
        self.assertTrue(is_suspicious_price(25000))
        self.assertFalse(is_suspicious_price(24999))


class TestClassifyEntry(unittest.TestCase):
    THRESHOLD = 0.5

    def test_empty_when_sample_zero(self):
        status, reasons = classify_entry({"sample_count": 0}, self.THRESHOLD)
        self.assertEqual(status, "empty")
        self.assertEqual(reasons, ["sample_count=0"])

    def test_legacy_when_no_confidence_field(self):
        entry = {"sample_count": 5, "median_jpy": 100000}
        status, reasons = classify_entry(entry, self.THRESHOLD)
        self.assertEqual(status, "legacy")
        self.assertIn("legacy_no_confidence_field", reasons)

    def test_ok_when_high_confidence_and_clean(self):
        entry = {
            "sample_count": 8,
            "median_jpy": 165000,
            "brand_match_confidence": 0.9,
            "excluded_count_default_price": 0,
            "default_price_warnings": [],
        }
        status, _ = classify_entry(entry, self.THRESHOLD)
        self.assertEqual(status, "ok")

    def test_suspicious_when_low_confidence(self):
        entry = {
            "sample_count": 8,
            "median_jpy": 165000,
            "brand_match_confidence": 0.2,
            "excluded_count_default_price": 0,
            "default_price_warnings": [],
        }
        status, reasons = classify_entry(entry, self.THRESHOLD)
        self.assertEqual(status, "suspicious")
        self.assertTrue(any("low_confidence" in r for r in reasons))

    def test_suspicious_when_default_price_excluded(self):
        entry = {
            "sample_count": 8,
            "median_jpy": 165000,
            "brand_match_confidence": 0.8,
            "excluded_count_default_price": 3,
            "default_price_warnings": [],
        }
        status, reasons = classify_entry(entry, self.THRESHOLD)
        self.assertEqual(status, "suspicious")
        self.assertTrue(any("default_price_excluded" in r for r in reasons))

    def test_suspicious_when_median_in_band(self):
        entry = {
            "sample_count": 8,
            "median_jpy": 25980,
            "brand_match_confidence": 0.8,
            "excluded_count_default_price": 0,
            "default_price_warnings": [],
        }
        status, reasons = classify_entry(entry, self.THRESHOLD)
        self.assertEqual(status, "suspicious")
        self.assertTrue(any("median_in_suspicious_band" in r for r in reasons))

    def test_threshold_respected(self):
        entry = {
            "sample_count": 8,
            "median_jpy": 165000,
            "brand_match_confidence": 0.6,
            "excluded_count_default_price": 0,
            "default_price_warnings": [],
        }
        # threshold 0.5 では ok、threshold 0.7 では suspicious
        ok_status, _ = classify_entry(entry, 0.5)
        sus_status, _ = classify_entry(entry, 0.7)
        self.assertEqual(ok_status, "ok")
        self.assertEqual(sus_status, "suspicious")


class TestReEvaluate(unittest.TestCase):
    def test_returns_none_when_no_raw_items(self):
        entry = {"brand": "X", "median_jpy": 100, "sample_count": 5}
        self.assertIsNone(re_evaluate(entry))

    def test_recomputes_with_raw_items(self):
        entry = {
            "brand": "Gucci",
            "raw_items": [
                {"price": 100000, "brand_text": "Gucci", "title_text": "bag"},
                {"price": 120000, "brand_text": "Gucci", "title_text": "bag"},
                {"price": 25980, "brand_text": "OtherBrand", "title_text": "x"},
                {"price": 25980, "brand_text": "OtherBrand", "title_text": "y"},
                {"price": 130000, "brand_text": "Gucci", "title_text": "bag"},
            ],
            "median_jpy": 999,  # 古い値、上書きされるはず
            "sample_count": 99,
        }
        updated = re_evaluate(entry)
        self.assertIsNotNone(updated)
        # raw_items は保持
        self.assertEqual(len(updated["raw_items"]), 5)
        # 新しい統計が入っている
        self.assertNotEqual(updated["median_jpy"], 999)
        self.assertIn("brand_match_confidence", updated)
        # mismatch されたブランドが存在するため confidence < 1.0
        self.assertLess(updated["brand_match_confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
