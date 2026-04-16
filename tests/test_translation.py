"""
app.utils.text の翻訳機能に対するユニットテスト。

- ヒューリスティック翻訳（ファッション用語辞書による置換）
- DeepL API 連携（モックによるテスト）
- API キー未設定時のフォールバック
- 翻訳キャッシュ
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.text import (
    FASHION_TERMS,
    _cache_key,
    _get_deepl_endpoint,
    _heuristic_translate,
    _translation_cache,
    translate_description,
)


class TestHeuristicTranslation(unittest.TestCase):
    """ヒューリスティック翻訳（辞書ベース置換）のテスト。"""

    def test_known_fashion_terms_replaced(self):
        """FASHION_TERMS に含まれる用語が日本語に置換される。"""
        text = "Composition: 100% cotton\nMade in Italy"
        result = _heuristic_translate(text)
        self.assertIn("コットン", result)
        self.assertIn("イタリア製", result)
        # 元の英語キーワードが消えていることを確認
        self.assertNotIn("cotton", result)
        self.assertNotIn("Made in Italy", result)

    def test_multiple_terms_in_single_line(self):
        """1行に複数の用語がある場合もすべて置換される。"""
        text = "Material: silk and wool"
        result = _heuristic_translate(text)
        self.assertIn("シルク", result)
        self.assertIn("ウール", result)

    def test_case_insensitive_matching(self):
        """大文字・小文字に関係なく用語が置換される。"""
        text = "COTTON fabric"
        result = _heuristic_translate(text)
        self.assertIn("コットン", result)
        self.assertIn("生地", result)

    def test_unknown_terms_preserved(self):
        """辞書にない用語はそのまま残る。"""
        text = "Beautiful designer handbag"
        result = _heuristic_translate(text)
        self.assertIn("Beautiful", result)
        self.assertIn("designer", result)
        self.assertIn("handbag", result)

    def test_empty_lines_skipped(self):
        """空行はスキップされる。"""
        text = "cotton\n\n\nsilk"
        result = _heuristic_translate(text)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2)

    def test_empty_string(self):
        """空文字列は空文字列を返す。"""
        self.assertEqual(_heuristic_translate(""), "")

    def test_clothing_fit_terms(self):
        """フィット関連の用語が正しく翻訳される。"""
        text = "slim fit design with high waist"
        result = _heuristic_translate(text)
        self.assertIn("スリムフィット", result)
        self.assertIn("ハイウエスト", result)

    def test_care_instructions(self):
        """ケア方法の用語が翻訳される。"""
        text = "Dry clean only"
        result = _heuristic_translate(text)
        self.assertIn("ドライクリーニングのみ", result)


class TestTranslateDescriptionFallback(unittest.TestCase):
    """translate_description の use_api=False（ヒューリスティック）テスト。"""

    def test_use_api_false_applies_heuristic(self):
        """use_api=False ではヒューリスティック翻訳が適用される。"""
        text = "100% leather\nMade in France"
        result = translate_description(text, use_api=False)
        self.assertIn("レザー", result)
        self.assertIn("フランス製", result)
        # 英語のままではないことを確認
        self.assertNotIn("leather", result)
        self.assertNotIn("Made in France", result)

    def test_use_api_false_does_not_return_raw_english(self):
        """use_api=False は英語そのままを返さない（辞書にある用語は置換される）。"""
        text = "polyester lining"
        result = translate_description(text, use_api=False)
        self.assertNotEqual(result, text)
        self.assertIn("ポリエステル", result)
        self.assertIn("裏地", result)

    def test_empty_input(self):
        """空文字列入力は空文字列を返す。"""
        self.assertEqual(translate_description("", use_api=False), "")
        self.assertEqual(translate_description("", use_api=True), "")
        self.assertEqual(translate_description(""), "")


class TestTranslateDescriptionAutoDetect(unittest.TestCase):
    """use_api=None（自動判定）のテスト。"""

    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_uses_heuristic(self):
        """DEEPL_API_KEY が未設定なら use_api=None でもヒューリスティックを使う。"""
        # 環境変数をクリアした状態で呼び出し
        text = "cotton fabric"
        result = translate_description(text, use_api=None)
        self.assertIn("コットン", result)
        self.assertIn("生地", result)

    @patch.dict("os.environ", {"DEEPL_API_KEY": "test-key:fx"})
    @patch("app.utils.text._translate_via_deepl")
    def test_api_key_present_uses_deepl(self, mock_deepl):
        """DEEPL_API_KEY がある場合、use_api=None で DeepL を試みる。"""
        mock_deepl.return_value = "テスト翻訳結果"
        # キャッシュをクリア
        _translation_cache.clear()
        result = translate_description("test text", use_api=None)
        mock_deepl.assert_called_once()
        self.assertEqual(result, "テスト翻訳結果")

    @patch.dict("os.environ", {"DEEPL_API_KEY": "test-key:fx"})
    @patch("app.utils.text._translate_via_deepl", return_value=None)
    def test_api_failure_falls_back_to_heuristic(self, mock_deepl):
        """DeepL API が失敗した場合、ヒューリスティックにフォールバックする。"""
        _translation_cache.clear()
        text = "100% cashmere"
        result = translate_description(text, use_api=None)
        mock_deepl.assert_called_once()
        self.assertIn("カシミヤ", result)


class TestTranslateDescriptionWithMockAPI(unittest.TestCase):
    """DeepL API 連携のモックテスト。"""

    @patch.dict("os.environ", {"DEEPL_API_KEY": "fake-key:fx"})
    @patch("app.utils.text.requests.post")
    def test_successful_deepl_call(self, mock_post):
        """DeepL API が正常応答を返す場合のテスト。"""
        _translation_cache.clear()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "translations": [{"text": "翻訳されたテキスト"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = translate_description("Some English text", use_api=True)
        self.assertEqual(result, "翻訳されたテキスト")
        mock_post.assert_called_once()

        # API URL が Free エンドポイントであること（キーが :fx で終わるため）
        call_args = mock_post.call_args
        self.assertIn("api-free.deepl.com", call_args[1].get("url", call_args[0][0] if call_args[0] else ""))

    @patch.dict("os.environ", {"DEEPL_API_KEY": "fake-key:fx"})
    @patch("app.utils.text.requests.post", side_effect=Exception("Network error"))
    def test_network_error_falls_back(self, mock_post):
        """ネットワークエラー時にヒューリスティックへフォールバック。"""
        _translation_cache.clear()
        text = "wool sweater"
        result = translate_description(text, use_api=True)
        self.assertIn("ウール", result)

    @patch("os.getenv", return_value=None)
    def test_use_api_true_but_no_key(self, mock_getenv):
        """use_api=True だが API キーがない場合はヒューリスティックへ。"""
        _translation_cache.clear()
        text = "nylon bag"
        result = translate_description(text, use_api=True)
        self.assertIn("ナイロン", result)


class TestTranslationCache(unittest.TestCase):
    """翻訳キャッシュのテスト。"""

    @patch.dict("os.environ", {"DEEPL_API_KEY": "test-key:fx"})
    @patch("app.utils.text._translate_via_deepl")
    def test_cache_avoids_duplicate_api_calls(self, mock_deepl):
        """同じテキストの2回目はキャッシュから取得し、API を再呼び出ししない。"""
        _translation_cache.clear()
        mock_deepl.return_value = "キャッシュテスト"

        text = "cache test input"
        result1 = translate_description(text, use_api=True)
        result2 = translate_description(text, use_api=True)

        self.assertEqual(result1, "キャッシュテスト")
        self.assertEqual(result2, "キャッシュテスト")
        # API は1回だけ呼ばれる
        mock_deepl.assert_called_once()

    def test_cache_key_deterministic(self):
        """同じ入力に対して常に同じキャッシュキーが生成される。"""
        text = "hello world"
        key1 = _cache_key(text)
        key2 = _cache_key(text)
        self.assertEqual(key1, key2)

    def test_different_texts_different_keys(self):
        """異なる入力は異なるキャッシュキーを生成する。"""
        key1 = _cache_key("text A")
        key2 = _cache_key("text B")
        self.assertNotEqual(key1, key2)


class TestDeepLEndpointDetection(unittest.TestCase):
    """DeepL エンドポイント自動判定のテスト。"""

    def test_free_key_uses_free_endpoint(self):
        """:fx で終わるキーは Free エンドポイントを使う。"""
        url = _get_deepl_endpoint("abc123:fx")
        self.assertIn("api-free.deepl.com", url)

    def test_pro_key_uses_pro_endpoint(self):
        """:fx で終わらないキーは Pro エンドポイントを使う。"""
        url = _get_deepl_endpoint("abc123")
        self.assertIn("api.deepl.com", url)
        self.assertNotIn("api-free", url)


if __name__ == "__main__":
    unittest.main()
