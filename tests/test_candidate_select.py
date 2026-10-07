"""出品候補の選定 (app/core/candidate_select.py) のテスト。ネットワークには触れない。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import candidate_select as cs  # noqa: E402

TIERS = {
    "tiers": {"A": ["MAISON MARGIELA", "MONCLER"], "B": ["ETRO", "PT TORINO"]},
    "aliases": {"MARGIELA": "MAISON MARGIELA", "CHLOÉ": "CHLOE"},
}


def row(**kw):
    base = {"vendor": "ETRO", "title": "Roma cotton Shirt", "product_type": "CLOTHING",
            "available_sizes": "39,40", "total_cost_jpy": "74588", "expected_profit_jpy": "18000",
            "action": "list"}
    base.update(kw)
    base.setdefault("sku", f"SKU{abs(hash((base['vendor'], base['title']))) % 10**8}_C1")
    return base


class TestBrand(unittest.TestCase):
    def test_alias_and_tier(self):
        self.assertEqual(cs.canonical_brand("Margiela", TIERS), "MAISON MARGIELA")
        self.assertEqual(cs.brand_tier("Margiela", TIERS), "A")
        self.assertEqual(cs.brand_tier("etro", TIERS), "B")
        self.assertEqual(cs.brand_tier("UNKNOWN BRAND", TIERS), "C")

    def test_real_tier_file_loads(self):
        data = cs.load_brand_tiers()
        self.assertEqual(cs.brand_tier("MAISON MARGIELA", data), "A")
        self.assertEqual(cs.canonical_brand("Margiela", data), "MAISON MARGIELA")


class TestCommonSizes(unittest.TestCase):
    def test_clothing(self):
        self.assertEqual(cs.common_sizes("XXS,XS,M,XXL", "CLOTHING"), ["XS", "M"])
        self.assertEqual(cs.common_sizes("34,38,IT 46,54", "CLOTHING"), ["38", "IT 46"])

    def test_jeans_waist(self):
        self.assertEqual(cs.common_sizes("23,26,31,34", "CLOTHING", "Straight Jeans"), ["26", "31"])

    def test_shoes(self):
        self.assertEqual(cs.common_sizes("35,35.5,40,44,45", "FOOTWEAR"), ["35.5", "40", "44"])

    def test_one_size_and_bags(self):
        self.assertEqual(cs.common_sizes("UNI", "ACCESSORIES"), ["UNI"])
        self.assertEqual(cs.common_sizes("TAGLIA UNICA", "CLOTHING"), ["TAGLIA UNICA"])
        self.assertEqual(cs.common_sizes("", "BAGS"), [])


class TestSearchUrls(unittest.TestCase):
    def test_urls(self):
        u = cs.search_urls("Margiela", "Leather Card Holder with logo", "SA3VX0007P4455_T8013", TIERS)
        self.assertEqual(u["buyma_search_url"], "https://www.buyma.com/r/MAISON%20MARGIELA%20Leather%20Card%20Holder/")
        self.assertEqual(u["buyma_search_url_sku"], "https://www.buyma.com/r/MAISON%20MARGIELA%20SA3VX0007P4455/")

    def test_no_sku(self):
        self.assertNotIn("buyma_search_url_sku", cs.search_urls("ETRO", "Shirt", "", TIERS))

    def test_model_number(self):
        self.assertEqual(cs.model_number("S56UI0143P4455_T8013"), "S56UI0143P4455")
        self.assertEqual(cs.model_number(""), "")


class TestSelect(unittest.TestCase):
    def test_filters(self):
        ev = cs.evaluate_candidate(row(total_cost_jpy="90000"), max_cost=80000, min_profit=5000, data=TIERS)
        self.assertFalse(ev["ok"])
        ev = cs.evaluate_candidate(row(expected_profit_jpy="4000"), max_cost=80000, min_profit=5000, data=TIERS)
        self.assertFalse(ev["ok"])
        ev = cs.evaluate_candidate(row(available_sizes="56,58"), max_cost=80000, min_profit=5000, data=TIERS)
        self.assertFalse(ev["ok"])
        ev = cs.evaluate_candidate(row(action="review"), max_cost=80000, min_profit=5000, data=TIERS)
        self.assertFalse(ev["ok"])
        ev = cs.evaluate_candidate(row(), max_cost=80000, min_profit=5000, data=TIERS)
        self.assertTrue(ev["ok"])
        self.assertEqual(ev["tier"], "B")

    def test_tier_beats_profit_and_dedupe_and_brand_cap(self):
        rows = [
            row(vendor="ETRO", title="A", expected_profit_jpy="30000"),
            row(vendor="MAISON MARGIELA", title="Card Holder", product_type="ACCESSORIES",
                available_sizes="UNI", expected_profit_jpy="9000", sku="S56UI0143_T8013"),
            row(vendor="Margiela", title="Card holder", product_type="ACCESSORIES",
                available_sizes="UNI", expected_profit_jpy="8000", sku="S56UI0143_T2000"),  # 色違い (別名表記)
            row(vendor="Margiela", title="Wallet", product_type="ACCESSORIES",
                available_sizes="UNI", expected_profit_jpy="7000"),
            row(vendor="MAISON MARGIELA", title="Belt", product_type="ACCESSORIES",
                available_sizes="UNI", expected_profit_jpy="6000"),
        ]
        picked, rejected = cs.select_candidates(rows, max_cost=80000, min_profit=5000, limit=5,
                                                data=TIERS, max_per_brand=2)
        self.assertEqual([r["title"] for r in picked], ["Card Holder", "Wallet", "A"])
        self.assertEqual(picked[0]["expected_profit_jpy"], "9000")
        self.assertEqual(len(rejected), 2)

    def test_same_generic_title_different_sku_kept(self):
        rows = [row(title="Shirt", sku="AAA1_01"), row(title="Shirt", sku="BBB2_01")]
        picked, _ = cs.select_candidates(rows, max_cost=80000, min_profit=5000, limit=5, data=TIERS)
        self.assertEqual(len(picked), 2)

    def test_dedupe_key_without_sku_uses_title(self):
        self.assertEqual(cs.dedupe_key({"vendor": "Margiela", "title": "Wallet", "sku": ""}, TIERS),
                         ("MAISON MARGIELA", "title", "WALLET"))

    def test_limit(self):
        rows = [row(title=str(i)) for i in range(5)]
        picked, _ = cs.select_candidates(rows, max_cost=80000, min_profit=5000, limit=3, data=TIERS)
        self.assertEqual(len(picked), 3)


if __name__ == "__main__":
    unittest.main()
