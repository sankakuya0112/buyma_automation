"""テキスト正規化・翻訳ユーティリティ"""

import logging
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# BUYMA タイトルの最大文字数
_BUYMA_TITLE_MAX_LEN = 120


def normalize_text(text: str) -> str:
    """
    テキスト正規化。

    - BUYMA で禁止されているアクセント記号（è, ï 等）を除去
    - NFD 正規化によりアクセント記号を分離・削除
    - 余分な空白を削除

    Args:
        text: 正規化対象のテキスト

    Returns:
        正規化済みテキスト
    """
    if not text:
        return ""

    # NFD で正規化（アクセント記号を分解）
    text = unicodedata.normalize("NFD", text)
    # 結合文字（アクセント記号 = Category "Mn"）のみを削除
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")

    # 余分な空白を整理
    text = " ".join(text.split())

    return text.strip()


def translate_description(en_text: str, use_api: bool = False) -> str:
    """
    英語説明文を日本語に翻訳。

    use_api=True の場合、Google Cloud Translation API を呼び出す。
    False の場合、英語テキストをそのまま返す（将来的に辞書ベース変換を追加）。

    Args:
        en_text: 英語説明文
        use_api: True で外部 API を使用

    Returns:
        翻訳済みテキスト（失敗時は原文を返す）
    """
    if not en_text:
        return ""

    if use_api:
        try:
            # Google Cloud Translation API 利用例
            # from google.cloud import translate_v2 as translate
            # client = translate.Client()
            # result = client.translate(en_text, target_language="ja")
            # return result["translatedText"]
            logger.warning("Translation API not configured; returning original text")
            return en_text
        except Exception as exc:
            logger.warning("Translation API failed: %s", exc)
            return en_text
    else:
        # API 未使用時は英語テキストをそのまま返す
        return en_text


def generate_buyma_title(
    brand: str,
    product_name: str,
    sku: str,
    color: Optional[str] = None,
) -> str:
    """
    BUYMA 向けタイトルを SEO 最適化フォーマットで生成。

    フォーマット: [ブランド] [商品名] [品番] [色] 正規品 関税送料込

    Args:
        brand: ブランド名
        product_name: 商品名
        sku: 品番（メーカー品番）
        color: 色（任意）

    Returns:
        BUYMA タイトル文字列（最大 120 文字）
    """
    parts = []
    if brand:
        parts.append(brand)
    if product_name:
        parts.append(product_name)
    if sku:
        parts.append(sku)
    if color:
        parts.append(color)
    parts.extend(["正規品", "関税送料込"])

    title = " ".join(parts)
    title = normalize_text(title)

    return title[:_BUYMA_TITLE_MAX_LEN]
