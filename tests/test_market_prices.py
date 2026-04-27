"""
fetch_buyma_market_prices.py の精度改善ロジックに対するユニットテスト。

カバー範囲:
  - _is_brand_match: 大小無視 / 双方向 substring / 空文字 → None
  - _detect_default_prices: 同一価格の複数出現検出 / min_samples ガード
  - compute_stats: brand_match_confidence / default 価格除外 / brand 不一致
  - MarketStats.is_reliable: 新仕様 (confidence < 0.5 で False)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fetch_buyma_market_prices import (  # noqa: E402
    _detect_default_prices,
    _is_brand_match,
    compute_stats,
)
from app.core.pricing import MarketStats  # noqa: E402


class TestIsBrandMatch(unittest.TestCase):
    """_is_brand_match の動作確認。"""

    def test_is_brand_match_exact(self):
        self.assertTrue(_is_brand_match("Gucci", "gucci"))

    def test_is_brand_match_substring(self):
        # item brand に query が含まれる
        self.assertTrue(_is_brand_match("Gucci Women", "gucci"))
        # query に item brand が含まれる (逆方向)
        self.assertTrue(_is_brand_match("Gucci", "Gucci Marmont"))

    def test_is_brand_match_mismatch(self):
        self.assertFalse(_is_brand_match("Prada", "gucci"))

    def test_is_brand_match_empty_returns_none(self):
        # item_brand_text が空文字 → 不明 (None)
        self.assertIsNone(_is_brand_match("", "gucci"))
        # 空白のみも空扱い
        self.assertIsNone(_is_brand_match("   ", "gucci"))


class TestDetectDefaultPrices(unittest.TestCase):
    """_detect_default_prices の動作確認。"""

    def test_detect_default_prices_finds_duplicates(self):
        prices = [25980, 25980, 40000, 50000, 60000, 70000]
        result = _detect_default_prices(prices)
        self.assertEqual(result, {25980})

    def test_detect_default_prices_below_min_samples(self):
        # サンプル < min_samples (=5) → noisy 防止で空 set
        prices = [25980, 25980]
        self.assertEqual(_detect_default_prices(prices), set())

    def test_detect_default_prices_no_duplicates(self):
        # 全部ユニーク → 空 set
        prices = [10000, 20000, 30000, 40000, 50000, 60000]
        self.assertEqual(_detect_default_prices(prices), set())

    def test_detect_default_prices_multiple_default(self):
        prices = [25980, 25980, 30000, 30000, 40000, 50000, 60000]
        self.assertEqual(_detect_default_prices(prices), {25980, 30000})


class TestComputeStats(unittest.TestCase):
    """compute_stats の動作確認 (新シグネチャ)。"""

    def test_compute_stats_brand_match_confidence_high(self):
        # 全件 query_brand と一致 → confidence=1.0
        items = [
            {"price": 50000, "brand_text": "Gucci", "title_text": "bag A"},
            {"price": 55000, "brand_text": "Gucci Women", "title_text": "bag B"},
            {"price": 60000, "brand_text": "Gucci", "title_text": "bag C"},
            {"price": 65000, "brand_text": "Gucci", "title_text": "bag D"},
        ]
        stats = compute_stats(items, query_brand="Gucci")
        self.assertEqual(stats["brand_match_confidence"], 1.0)
        self.assertEqual(stats["brand_match_count"], 4)
        self.assertEqual(stats["brand_mismatch_count"], 0)

    def test_compute_stats_brand_match_confidence_low(self):
        # 半分以上が他ブランド → confidence < 0.5
        items = [
            {"price": 50000, "brand_text": "Gucci", "title_text": "x"},
            {"price": 26000, "brand_text": "Prada", "title_text": "y"},
            {"price": 27000, "brand_text": "Hermes", "title_text": "z"},
            {"price": 28000, "brand_text": "Chanel", "title_text": "w"},
        ]
        stats = compute_stats(items, query_brand="Gucci")
        self.assertLess(stats["brand_match_confidence"], 0.5)
        self.assertEqual(stats["brand_mismatch_count"], 3)

    def test_compute_stats_default_price_excluded(self):
        # ¥25980 が複数件 (>=2) かつ raw_n >= 5 → default として除外
        items = [
            {"price": 25980, "brand_text": "", "title_text": ""},
            {"price": 25980, "brand_text": "", "title_text": ""},
            {"price": 25980, "brand_text": "", "title_text": ""},
            {"price": 50000, "brand_text": "", "title_text": ""},
            {"price": 60000, "brand_text": "", "title_text": ""},
            {"price": 70000, "brand_text": "", "title_text": ""},
        ]
        stats = compute_stats(items, query_brand="The Latest")
        self.assertIn(25980, stats["default_price_warnings"])
        self.assertEqual(stats["excluded_count_default_price"], 3)
        # cleaned から除外されているので median は default に引っ張られない
        self.assertNotEqual(stats["median_jpy"], 25980)
        self.assertGreater(stats["median_jpy"], 25980)

    def test_compute_stats_empty_items(self):
        stats = compute_stats([], query_brand="Gucci")
        self.assertEqual(stats["sample_count"], 0)
        self.assertIsNone(stats["median_jpy"])
        self.assertEqual(stats["raw_sample_count"], 0)
        self.assertEqual(stats["brand_match_confidence"], 1.0)

    def test_compute_stats_backwards_compat_int_list(self):
        # 旧シグネチャ (list[int]) でも動作する後方互換
        prices = [50000, 55000, 60000, 65000, 70000]
        stats = compute_stats(prices)
        self.assertEqual(stats["sample_count"], 5)
        self.assertEqual(stats["median_jpy"], 60000)
        # brand 判定スキップ → confidence は 1.0 (mismatch なし)
        self.assertEqual(stats["brand_match_confidence"], 1.0)


class TestMarketStatsIsReliable(unittest.TestCase):
    """MarketStats.is_reliable の新仕様 (confidence ガード)。"""

    def test_market_stats_is_reliable_with_low_confidence(self):
        # confidence=0.3 → False (新仕様)
        ms = MarketStats(
            sample_count=10,
            median_jpy=50000,
            min_jpy=40000,
            max_jpy=60000,
            brand_match_confidence=0.3,
        )
        self.assertFalse(ms.is_reliable())

    def test_market_stats_is_reliable_with_high_confidence(self):
        ms = MarketStats(
            sample_count=10,
            median_jpy=50000,
            min_jpy=40000,
            max_jpy=60000,
            brand_match_confidence=0.8,
        )
        self.assertTrue(ms.is_reliable())

    def test_market_stats_is_reliable_default_confidence_backcompat(self):
        # 旧キャッシュ (brand_match_confidence 未指定) → default=1.0 → True
        ms = MarketStats(
            sample_count=5,
            median_jpy=40000,
            min_jpy=30000,
            max_jpy=50000,
        )
        self.assertTrue(ms.is_reliable())


if __name__ == "__main__":
    unittest.main()
