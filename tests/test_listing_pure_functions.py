"""
app.utils.listing_helpers の純粋関数のユニットテスト。

対象 (Phase 2c+ で scripts.buyma_auto_listing から切り出し):
  - _strip_accents
  - normalize_size_for_buyma
  - _map_footwear_to_jp_cm
  - map_size_to_jp_reference
  - translate_color_to_jp
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.listing_helpers import (
    _map_footwear_to_jp_cm,
    _strip_accents,
    map_size_to_jp_reference,
    normalize_size_for_buyma,
    translate_color_to_jp,
)


class TestStripAccents(unittest.TestCase):
    """_strip_accents の文字列正規化。"""

    def test_basic_latin_accents(self):
        """è é â ç 等の Latin アクセントが ASCII に落ちる。"""
        self.assertEqual(_strip_accents("Lavallière"), "Lavalliere")
        self.assertEqual(_strip_accents("café"), "cafe")

    def test_japanese_dakuten_preserved(self):
        """カタカナの濁点 (U+3099) は除去されない: パンプス → パンプス。"""
        self.assertEqual(_strip_accents("パンプス"), "パンプス")
        self.assertEqual(_strip_accents("ゴールド"), "ゴールド")

    def test_mixed_jp_latin(self):
        """日本語 + Latin 混在でも片方だけ正規化される。"""
        self.assertEqual(_strip_accents("café パンプス"), "cafe パンプス")

    def test_empty_string(self):
        """空文字はそのまま空文字。"""
        self.assertEqual(_strip_accents(""), "")

    def test_none_returns_none(self):
        """None もそのまま返る (エラーにならない)。"""
        self.assertIsNone(_strip_accents(None))


class TestNormalizeSizeForBuyma(unittest.TestCase):
    """normalize_size_for_buyma の挙動。"""

    def test_uni_to_free(self):
        """UNI / ONE SIZE / 空 → "FREE"。"""
        self.assertEqual(normalize_size_for_buyma("UNI"), "FREE")
        self.assertEqual(normalize_size_for_buyma("one size"), "FREE")
        self.assertEqual(normalize_size_for_buyma("OS"), "FREE")
        self.assertEqual(normalize_size_for_buyma("TU"), "FREE")

    def test_passthrough_alpha(self):
        """XS/S/M/L/XL はそのまま返る。"""
        self.assertEqual(normalize_size_for_buyma("M"), "M")
        self.assertEqual(normalize_size_for_buyma("XL"), "XL")

    def test_empty(self):
        """空文字は "FREE"。"""
        self.assertEqual(normalize_size_for_buyma(""), "FREE")

    def test_numeric_passthrough(self):
        """数値サイズはそのまま (strip 後)。"""
        self.assertEqual(normalize_size_for_buyma("40"), "40")
        self.assertEqual(normalize_size_for_buyma(" 42 "), "42")


class TestMapFootwearToJpCm(unittest.TestCase):
    """_map_footwear_to_jp_cm の EU/IT サイズ変換。"""

    def test_basic_conversion(self):
        """37.5 → 24cm, 40 → 26cm。"""
        self.assertEqual(_map_footwear_to_jp_cm("37.5"), "24cm")
        self.assertEqual(_map_footwear_to_jp_cm("40"), "26cm")

    def test_with_prefix(self):
        """IT40 のような接頭辞付きでも数値抽出される。"""
        self.assertEqual(_map_footwear_to_jp_cm("IT40"), "26cm")

    def test_below_floor_returns_min(self):
        """33 以下 → 21cm以下。"""
        self.assertEqual(_map_footwear_to_jp_cm("33"), "21cm以下")

    def test_above_ceiling_returns_max(self):
        """42 以上 → 27cm以上。"""
        self.assertEqual(_map_footwear_to_jp_cm("43"), "27cm以上")

    def test_empty_returns_unspecified(self):
        self.assertEqual(_map_footwear_to_jp_cm(""), "指定なし")

    def test_non_numeric_returns_unspecified(self):
        self.assertEqual(_map_footwear_to_jp_cm("xx"), "指定なし")


class TestMapSizeToJpReference(unittest.TestCase):
    """map_size_to_jp_reference の総合変換。"""

    def test_clothing_xs(self):
        self.assertEqual(map_size_to_jp_reference("XS", ""), "XS以下")

    def test_clothing_m(self):
        self.assertEqual(map_size_to_jp_reference("M", ""), "M")

    def test_clothing_xxl(self):
        self.assertEqual(map_size_to_jp_reference("XXL", ""), "XXL")

    def test_alpha_size_lowercase(self):
        """小文字でも大文字化されてマッピング。"""
        self.assertEqual(map_size_to_jp_reference("m", ""), "M")

    def test_unique_size(self):
        """UNI → FREE 扱い。"""
        self.assertEqual(map_size_to_jp_reference("UNI", ""), "FREE")

    def test_empty_returns_unspecified(self):
        self.assertEqual(map_size_to_jp_reference("", ""), "指定なし")

    def test_numeric_clothing_to_m(self):
        """数値 40 (CLOTHING) → M。"""
        self.assertEqual(map_size_to_jp_reference("40", "CLOTHING"), "M")

    def test_footwear_dispatched(self):
        """product_type=FOOTWEAR で _map_footwear_to_jp_cm に委譲される。"""
        self.assertEqual(map_size_to_jp_reference("37.5", "FOOTWEAR"), "24cm")
        self.assertEqual(map_size_to_jp_reference("40", "FOOTWEAR"), "26cm")


class TestTranslateColorToJp(unittest.TestCase):
    """translate_color_to_jp の英→日 マッピング。"""

    def test_known_color_black(self):
        self.assertEqual(translate_color_to_jp("Black"), "ブラック")

    def test_multiword_color(self):
        """navy blue は単独 navy より長いので先にマッチ。"""
        self.assertEqual(translate_color_to_jp("navy blue"), "ネイビー")

    def test_off_white_to_white(self):
        """off white → ホワイト (multi-word キー)。"""
        self.assertEqual(translate_color_to_jp("off white"), "ホワイト")
        self.assertEqual(translate_color_to_jp("Off-White"), "ホワイト")

    def test_wine_red(self):
        self.assertEqual(translate_color_to_jp("Wine Red"), "ワインレッド")

    def test_unknown_returns_default(self):
        """マッピングにない文字列は "マルチカラー" を返す。"""
        self.assertEqual(translate_color_to_jp("zomg-not-a-color"), "マルチカラー")

    def test_empty_returns_default(self):
        """空文字は "マルチカラー"。"""
        self.assertEqual(translate_color_to_jp(""), "マルチカラー")


if __name__ == "__main__":
    unittest.main()
