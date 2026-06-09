"""scout_demand.py (需要起点スカウト) のユニットテスト (Phase 2d)。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import scout_demand  # noqa: E402


def _entry(brand, sample_count, median=100000, confidence=1.0, wish_total=0):
    return {
        "brand": brand,
        "keyword": "x",
        "sample_count": sample_count,
        "median_jpy": median,
        "brand_match_confidence": confidence,
        "wish_total": wish_total,
    }


class BuildDemandIndexTest(unittest.TestCase):
    def test_classification_proven_high_demand(self):
        index = scout_demand.build_demand_index([_entry("GIVENCHY", 28)])
        self.assertEqual(index["GIVENCHY"]["classification"], "proven_high_demand")

    def test_classification_sweet_spot(self):
        index = scout_demand.build_demand_index([_entry("PETAR PETROV", 5)])
        self.assertEqual(index["PETAR PETROV"]["classification"], "sweet_spot")

    def test_classification_exclusive(self):
        index = scout_demand.build_demand_index([_entry("AFTERCOAT", 0)])
        self.assertEqual(index["AFTERCOAT"]["classification"], "exclusive")

    def test_classification_unreliable_low_confidence(self):
        index = scout_demand.build_demand_index(
            [_entry("THE LATEST", 11, confidence=0.3)]
        )
        self.assertEqual(index["THE LATEST"]["classification"], "unreliable")

    def test_multiple_queries_averaged(self):
        entries = [
            _entry("BRAND A", 4, median=80000),
            _entry("BRAND A", 8, median=120000),
        ]
        index = scout_demand.build_demand_index(entries)
        s = index["BRAND A"]
        self.assertEqual(s["n_queries"], 2)
        self.assertAlmostEqual(s["avg_sample_count"], 6.0)
        self.assertEqual(s["max_sample_count"], 8)
        self.assertEqual(s["median_price_jpy"], 100000)
        self.assertEqual(s["classification"], "sweet_spot")

    def test_wish_totals_summed(self):
        entries = [
            _entry("BRAND B", 5, wish_total=30),
            _entry("BRAND B", 5, wish_total=20),
        ]
        index = scout_demand.build_demand_index(entries)
        self.assertEqual(index["BRAND B"]["wish_total"], 50)

    def test_empty_brand_ignored(self):
        index = scout_demand.build_demand_index([_entry("", 5)])
        self.assertEqual(index, {})

    def test_legacy_entry_without_wish_or_confidence(self):
        """旧キャッシュ (wish_total / confidence 無し) でも壊れない。"""
        entry = {"brand": "OLD BRAND", "sample_count": 3, "median_jpy": 50000}
        index = scout_demand.build_demand_index([entry])
        s = index["OLD BRAND"]
        self.assertEqual(s["classification"], "sweet_spot")
        self.assertEqual(s["wish_total"], 0)
        self.assertEqual(s["min_confidence"], 1.0)


class MatchSourceTest(unittest.TestCase):
    def _write_csv(self, rows):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="",
        )
        writer = csv.DictWriter(f, fieldnames=[
            "title", "vendor", "sale_price", "discount_rate",
            "available", "product_url",
        ])
        writer.writeheader()
        writer.writerows(rows)
        f.close()
        return f.name

    def test_matches_demand_brands_only(self):
        index = scout_demand.build_demand_index([
            _entry("FAMOUS", 15, median=140000),
            _entry("NICHE", 0),
        ])
        path = self._write_csv([
            {"title": "Bag A", "vendor": "FAMOUS", "sale_price": "300",
             "discount_rate": "50.0", "available": "True", "product_url": "http://x/a"},
            {"title": "Bag B", "vendor": "NICHE", "sale_price": "200",
             "discount_rate": "40.0", "available": "True", "product_url": "http://x/b"},
        ])
        matches = scout_demand.match_source(index, path)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["vendor"], "FAMOUS")
        self.assertEqual(matches[0]["classification"], "proven_high_demand")
        self.assertEqual(matches[0]["market_median_jpy"], 140000)

    def test_unavailable_items_excluded(self):
        index = scout_demand.build_demand_index([_entry("FAMOUS", 15)])
        path = self._write_csv([
            {"title": "Sold Out", "vendor": "FAMOUS", "sale_price": "300",
             "discount_rate": "50.0", "available": "False", "product_url": "http://x"},
        ])
        self.assertEqual(scout_demand.match_source(index, path), [])

    def test_vendor_match_is_case_insensitive(self):
        index = scout_demand.build_demand_index([_entry("Famous Brand", 5)])
        path = self._write_csv([
            {"title": "Item", "vendor": "FAMOUS BRAND", "sale_price": "100",
             "discount_rate": "10.0", "available": "True", "product_url": "http://x"},
        ])
        self.assertEqual(len(scout_demand.match_source(index, path)), 1)


class LoadCacheEntriesTest(unittest.TestCase):
    def test_loads_valid_entries_and_skips_broken(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            with open(cache / "a.json", "w", encoding="utf-8") as f:
                json.dump(_entry("BRAND A", 5), f)
            with open(cache / "broken.json", "w", encoding="utf-8") as f:
                f.write("{not json")
            with open(cache / "no_brand.json", "w", encoding="utf-8") as f:
                json.dump({"sample_count": 3}, f)
            entries = scout_demand.load_cache_entries(cache)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["brand"], "BRAND A")


class WishExtractionTest(unittest.TestCase):
    """fetch_buyma_market_prices._extract_wish_count の抽出パターン。"""

    def test_fav_count_class(self):
        from fetch_buyma_market_prices import _extract_wish_count
        html = '<span class="fav-count">123</span>'
        self.assertEqual(_extract_wish_count(html), 123)

    def test_favorite_label_text(self):
        from fetch_buyma_market_prices import _extract_wish_count
        html = '<div>お気に入り <b>45</b> 件</div>'
        self.assertEqual(_extract_wish_count(html), 45)

    def test_data_attribute(self):
        from fetch_buyma_market_prices import _extract_wish_count
        html = '<button data-favorite-count="7">♡</button>'
        self.assertEqual(_extract_wish_count(html), 7)

    def test_no_signal_returns_zero(self):
        from fetch_buyma_market_prices import _extract_wish_count
        self.assertEqual(_extract_wish_count("<div>¥123,000</div>"), 0)
        self.assertEqual(_extract_wish_count(""), 0)

    def test_compute_stats_aggregates_wishes(self):
        from fetch_buyma_market_prices import compute_stats
        items = [
            {"price": 100000, "brand_text": "X", "title_text": "a", "wish": 10},
            {"price": 120000, "brand_text": "X", "title_text": "b", "wish": 25},
            {"price": 110000, "brand_text": "X", "title_text": "c"},  # wish なし
        ]
        stats = compute_stats(items, query_brand="X")
        self.assertEqual(stats["wish_total"], 35)
        self.assertEqual(stats["wish_max"], 25)

    def test_compute_stats_empty_has_wish_fields(self):
        from fetch_buyma_market_prices import compute_stats
        stats = compute_stats([], query_brand="X")
        self.assertEqual(stats["wish_total"], 0)
        self.assertEqual(stats["wish_max"], 0)


if __name__ == "__main__":
    unittest.main()
