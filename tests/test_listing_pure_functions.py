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


class CleanSourceDescriptionTest(unittest.TestCase):
    """clean_source_description (Phase 2d で Mac 実装 → helpers 移設)。"""

    def test_strips_html_and_keeps_text(self):
        from app.utils.listing_helpers import clean_source_description
        out = clean_source_description("<p>Leather shoulder bag</p><br>Made in Italy")
        self.assertIn("Leather shoulder bag", out)
        self.assertIn("Made in Italy", out)
        self.assertNotIn("<p>", out)

    def test_removes_shopify_json_noise(self):
        from app.utils.listing_helpers import clean_source_description
        desc = 'Nice bag\n{"id": 123, "price_min": 100}\n"variants": [{"option1": "S"}]'
        out = clean_source_description(desc)
        self.assertIn("Nice bag", out)
        self.assertNotIn("price_min", out)
        self.assertNotIn("variants", out)

    def test_strips_sku_and_season_lines(self):
        from app.utils.listing_helpers import clean_source_description
        out = clean_source_description("Elegant dress\nSku: AB123_456\nSeason: AW25")
        self.assertIn("Elegant dress", out)
        self.assertNotIn("AB123_456", out)
        self.assertNotIn("AW25", out)

    def test_composition_renamed_to_material(self):
        from app.utils.listing_helpers import clean_source_description
        out = clean_source_description("Composition: GENERAL 100% Calf Leather")
        self.assertIn("Material:", out)
        self.assertNotIn("Composition", out)

    def test_empty_input(self):
        from app.utils.listing_helpers import clean_source_description
        self.assertEqual(clean_source_description(""), "")
        self.assertEqual(clean_source_description(None), "")

    def test_caps_at_six_lines(self):
        from app.utils.listing_helpers import clean_source_description
        desc = "\n".join(f"Line number {i}" for i in range(10))
        out = clean_source_description(desc)
        self.assertEqual(len(out.split("\n")), 6)


class EvaluateListingReadinessTest(unittest.TestCase):
    """evaluate_listing_readiness (出品前安全判定)。"""

    def _product(self, **over):
        base = {
            "profit_jpy": "20000",
            "expected_margin_pct": "20.0",
            "image_url": "http://img/x.jpg",
            "sku": "AB123_456",
            "sizes": "36, 38",
            "available_sizes": "38",
        }
        base.update(over)
        return base

    def test_good_product_is_ok(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, reasons = evaluate_listing_readiness(
            self._product(), 100000, ["レディース", "バッグ"], "きれいな説明文",
        )
        self.assertEqual(verdict, "出品OK")

    def test_low_profit_and_margin_is_ng(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, reasons = evaluate_listing_readiness(
            self._product(profit_jpy="3000", expected_margin_pct="5.0"),
            100000, ["cat"], "desc",
        )
        self.assertEqual(verdict, "NG")
        self.assertTrue(any("利益基準未満" in r for r in reasons))

    def test_missing_image_is_ng(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, _ = evaluate_listing_readiness(
            self._product(image_url=""), 100000, ["cat"], "desc",
        )
        self.assertEqual(verdict, "NG")

    def test_missing_category_is_ng(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, _ = evaluate_listing_readiness(self._product(), 100000, None, "desc")
        self.assertEqual(verdict, "NG")

    def test_no_stock_info_is_ng(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, _ = evaluate_listing_readiness(
            self._product(sizes="", available_sizes=""), 100000, ["cat"], "desc",
        )
        self.assertEqual(verdict, "NG")

    def test_json_fragment_in_description_is_ng(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, reasons = evaluate_listing_readiness(
            self._product(), 100000, ["cat"], 'desc with "variants": [...]',
        )
        self.assertEqual(verdict, "NG")

    def test_expensive_item_needs_review(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, _ = evaluate_listing_readiness(
            self._product(profit_jpy="60000"), 350000, ["cat"], "desc",
        )
        self.assertEqual(verdict, "要確認")

    def test_weak_sku_needs_review(self):
        from app.utils.listing_helpers import evaluate_listing_readiness
        verdict, _ = evaluate_listing_readiness(
            self._product(sku=""), 100000, ["cat"], "desc",
        )
        self.assertEqual(verdict, "要確認")


class BuymaTitleTrimTest(unittest.TestCase):
    """_buyma_title_width / _trim_buyma_title (全角2/半角1 の幅計算)。"""

    def test_width_counts_fullwidth_as_two(self):
        from app.utils.listing_helpers import _buyma_title_width
        self.assertEqual(_buyma_title_width("abc"), 3)
        self.assertEqual(_buyma_title_width("あいう"), 6)
        self.assertEqual(_buyma_title_width("【A】"), 5)

    def test_short_title_unchanged(self):
        from app.utils.listing_helpers import _trim_buyma_title
        self.assertEqual(_trim_buyma_title("Short title"), "Short title")

    def test_long_title_trimmed_with_ellipsis(self):
        from app.utils.listing_helpers import _trim_buyma_title, _buyma_title_width
        long_title = "【BRUNELLO CUCINELLI】 Embellished Cashmere Sweater With Long Description"
        out = _trim_buyma_title(long_title, 60)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(_buyma_title_width(out), 60)

    def test_fullwidth_title_trimmed_within_width(self):
        from app.utils.listing_helpers import _trim_buyma_title, _buyma_title_width
        out = _trim_buyma_title("あ" * 50, 60)
        self.assertLessEqual(_buyma_title_width(out), 60)
        self.assertTrue(out.endswith("..."))


if __name__ == "__main__":
    unittest.main()
