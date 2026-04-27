"""
app.core.external_benchmark のユニットテスト。

ExternalBenchmark dataclass、evaluate_external_benchmark、
load/save_benchmarks、make_product_key を網羅する。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.external_benchmark import (
    DEFAULT_ADVANTAGE_MARGIN,
    ExternalBenchmark,
    evaluate_external_benchmark,
    load_benchmarks,
    make_product_key,
    save_benchmarks,
)


class TestExternalBenchmarkDataclass(unittest.TestCase):
    """ExternalBenchmark dataclass の基本動作。"""

    def test_empty_factory_default_source(self):
        """ExternalBenchmark.empty() の source は farfetch_jp がデフォルト。"""
        b = ExternalBenchmark.empty()
        self.assertEqual(b.source, "farfetch_jp")
        self.assertIsNone(b.matched_url)
        self.assertIsNone(b.matched_title)
        self.assertIsNone(b.min_price_jpy)
        self.assertEqual(b.sample_count, 0)
        self.assertTrue(b.fetched_at)  # ISO 文字列が入っている

    def test_empty_factory_custom_source(self):
        """source 引数で別の EC ソースに切り替えられる。"""
        b = ExternalBenchmark.empty(source="yoox_jp")
        self.assertEqual(b.source, "yoox_jp")

    def test_to_dict_roundtrip(self):
        """to_dict() → from_dict() で同値が復元される。"""
        original = ExternalBenchmark(
            source="farfetch_jp",
            matched_url="https://example.com/item",
            matched_title="Marmont Bag",
            min_price_jpy=80000,
            sample_count=5,
            fetched_at="2025-01-01T00:00:00",
        )
        roundtrip = ExternalBenchmark.from_dict(original.to_dict())
        self.assertEqual(roundtrip, original)

    def test_from_dict_default_values(self):
        """欠落キーがあっても from_dict は例外を出さずデフォルトで作る。"""
        b = ExternalBenchmark.from_dict({})
        self.assertEqual(b.source, "unknown")
        self.assertIsNone(b.matched_url)
        self.assertIsNone(b.min_price_jpy)
        self.assertEqual(b.sample_count, 0)
        self.assertEqual(b.fetched_at, "")


class TestEvaluateExternalBenchmark(unittest.TestCase):
    """evaluate_external_benchmark の判定ロジック。"""

    def _bench(self, min_price=80000, sample_count=5):
        return ExternalBenchmark(
            source="farfetch_jp",
            matched_url="https://example.com",
            matched_title="Foo",
            min_price_jpy=min_price,
            sample_count=sample_count,
            fetched_at="2025-01-01T00:00:00",
        )

    def test_no_benchmark_returns_pass(self):
        """benchmark=None → ("pass", "no_external_data")。"""
        action, reason = evaluate_external_benchmark(50000, None)
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "no_external_data")

    def test_no_match_returns_pass(self):
        """sample_count=0 / min_price_jpy=None → ("pass", "no_external_match")。"""
        action, reason = evaluate_external_benchmark(50000, ExternalBenchmark.empty())
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "no_external_match")

    def test_clearly_advantageous(self):
        """final 50000 vs ext 80000 (margin 0.10) → external_advantage。"""
        action, reason = evaluate_external_benchmark(50000, self._bench())
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "external_advantage")

    def test_close_to_external(self):
        """final 75000 vs ext 80000 → external_close。"""
        action, reason = evaluate_external_benchmark(75000, self._bench())
        self.assertEqual(action, "warn")
        self.assertEqual(reason, "external_close")

    def test_external_cheaper(self):
        """final 100000 vs ext 80000 → external_cheaper。"""
        action, reason = evaluate_external_benchmark(100000, self._bench())
        self.assertEqual(action, "skip")
        self.assertEqual(reason, "external_cheaper")

    def test_equal_to_external_returns_close(self):
        """final == ext min_price は "external_close" 扱い。"""
        action, reason = evaluate_external_benchmark(80000, self._bench())
        self.assertEqual(action, "warn")
        self.assertEqual(reason, "external_close")

    def test_custom_advantage_margin(self):
        """advantage_margin=0.20 にすると閾値が 80000 * 0.8 = 64000 になる。"""
        bench = self._bench()
        # final 64000 = 閾値 → pass
        action, reason = evaluate_external_benchmark(64000, bench, advantage_margin=0.20)
        self.assertEqual(action, "pass")
        self.assertEqual(reason, "external_advantage")
        # final 65000 > 閾値 → warn
        action, reason = evaluate_external_benchmark(65000, bench, advantage_margin=0.20)
        self.assertEqual(action, "warn")

    def test_default_margin_constant(self):
        """DEFAULT_ADVANTAGE_MARGIN は 0.10。"""
        self.assertAlmostEqual(DEFAULT_ADVANTAGE_MARGIN, 0.10)


class TestLoadSaveBenchmarks(unittest.TestCase):
    """load_benchmarks / save_benchmarks の入出力。"""

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "benchmarks.json")
            bench = ExternalBenchmark(
                source="farfetch_jp",
                matched_url="https://example.com/item",
                matched_title="Marmont",
                min_price_jpy=80000,
                sample_count=5,
                fetched_at="2025-01-01T00:00:00",
            )
            save_benchmarks(path, {"KEY1": bench})
            self.assertTrue(os.path.exists(path))
            loaded = load_benchmarks(path)
            self.assertIn("KEY1", loaded)
            self.assertEqual(loaded["KEY1"], bench)

    def test_load_nonexistent_path_returns_empty(self):
        """ファイルが存在しなくても空 dict を返し例外を出さない。"""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "no_such_file.json")
            self.assertEqual(load_benchmarks(path), {})

    def test_save_creates_parent_dirs(self):
        """親ディレクトリが存在しなくても自動的に作成される。"""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "deep", "nested", "dir", "benchmarks.json")
            save_benchmarks(path, {"K": ExternalBenchmark.empty()})
            self.assertTrue(os.path.exists(path))
            # 中身も valid JSON である
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            self.assertIn("K", raw)


class TestMakeProductKey(unittest.TestCase):
    """make_product_key の正規化挙動。"""

    def test_basic_normalization(self):
        """小文字・スペース → 大文字 + アンダースコア。"""
        key = make_product_key("Gucci", "Marmont Bag")
        self.assertEqual(key, "GUCCI_MARMONT_BAG")

    def test_with_sku(self):
        """SKU 付きで連結される。"""
        key = make_product_key("Gucci", "Marmont Bag", sku="SKU123")
        self.assertEqual(key, "GUCCI_MARMONT_BAG_SKU123")

    def test_long_title_truncated_to_120(self):
        """120 文字を超えると切り詰められる。"""
        long_title = "A" * 200
        key = make_product_key("Gucci", long_title)
        self.assertEqual(len(key), 120)
        self.assertTrue(key.startswith("GUCCI_"))

    def test_special_chars_replaced(self):
        """英数字以外の記号はアンダースコアに置換される (連続は 1 つに圧縮)。"""
        key = make_product_key("Gucci", "Voyou! Mini @ Bag/Lavalliere")
        # 連続アンダースコアが 1 つに圧縮されることを確認
        self.assertNotIn("__", key)
        self.assertTrue(key.startswith("GUCCI_VOYOU_MINI_BAG_LAVALLIERE"))


if __name__ == "__main__":
    unittest.main()
