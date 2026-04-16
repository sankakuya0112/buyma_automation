"""テキスト正規化・翻訳ユーティリティ"""

import hashlib
import logging
import os
import re
import unicodedata
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# BUYMA タイトルの最大文字数
_BUYMA_TITLE_MAX_LEN = 120

# DeepL API エンドポイント
_DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
_DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"

# インメモリ翻訳キャッシュ（md5(原文) -> 翻訳結果）
_translation_cache: dict[str, str] = {}

# ========== ファッション用語 英日辞書 ==========
# よく出るファッション用語の簡易翻訳（API 不使用時のヒューリスティック用）
FASHION_TERMS: dict[str, str] = {
    "composition": "素材",
    "material": "素材",
    "fabric": "生地",
    "cotton": "コットン",
    "silk": "シルク",
    "wool": "ウール",
    "polyester": "ポリエステル",
    "linen": "リネン",
    "cashmere": "カシミヤ",
    "leather": "レザー",
    "suede": "スエード",
    "nylon": "ナイロン",
    "viscose": "ビスコース",
    "elastane": "エラスタン",
    "lycra": "ライクラ",
    "made in italy": "イタリア製",
    "made in france": "フランス製",
    "made in spain": "スペイン製",
    "made in portugal": "ポルトガル製",
    "dry clean only": "ドライクリーニングのみ",
    "hand wash": "手洗い",
    "machine wash": "洗濯機可",
    "slim fit": "スリムフィット",
    "regular fit": "レギュラーフィット",
    "oversized": "オーバーサイズ",
    "relaxed fit": "リラックスフィット",
    "midi": "ミディ丈",
    "maxi": "マキシ丈",
    "mini": "ミニ丈",
    "long sleeve": "長袖",
    "short sleeve": "半袖",
    "sleeveless": "ノースリーブ",
    "round neck": "ラウンドネック",
    "v-neck": "Vネック",
    "crew neck": "クルーネック",
    "high waist": "ハイウエスト",
    "low rise": "ローライズ",
    "zip closure": "ジップ開閉",
    "button closure": "ボタン開閉",
    "lining": "裏地",
    "unlined": "裏地なし",
    "shoulder bag": "ショルダーバッグ",
    "tote bag": "トートバッグ",
    "crossbody": "クロスボディ",
    "clutch": "クラッチ",
}


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


def _get_deepl_endpoint(api_key: str) -> str:
    """DeepL API キーからエンドポイントを自動判定する。

    キーが ``:fx`` で終わる場合は Free プラン、それ以外は Pro プラン。
    """
    if api_key.endswith(":fx"):
        return _DEEPL_FREE_URL
    return _DEEPL_PRO_URL


def _translate_via_deepl(text: str, api_key: str) -> Optional[str]:
    """DeepL REST API を呼び出して英語→日本語翻訳を行う。

    成功時は翻訳文字列を返す。失敗時は ``None`` を返す。
    """
    url = _get_deepl_endpoint(api_key)
    headers = {
        "Authorization": f"DeepL-Auth-Key {api_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "text": text,
        "source_lang": "EN",
        "target_lang": "JA",
    }

    try:
        resp = requests.post(url, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        translations = result.get("translations", [])
        if translations:
            return translations[0].get("text", "")
        logger.warning("DeepL API returned empty translations array")
        return None
    except Exception as exc:
        logger.warning("DeepL API request failed: %s", exc)
        return None


def _heuristic_translate(en_text: str) -> str:
    """ファッション用語辞書を使った行単位のヒューリスティック翻訳。

    API が使えない場合のフォールバック。完全な翻訳ではないが、
    よく出るファッション用語を日本語に置換することで、
    BUYMA 上での可読性を向上させる。
    """
    lines = en_text.strip().split("\n")
    translated = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        for en, ja in FASHION_TERMS.items():
            # re.IGNORECASE で大文字・小文字・混在ケースすべてに対応
            line = re.sub(re.escape(en), ja, line, flags=re.IGNORECASE)
        translated.append(line)
    return "\n".join(translated)


def _cache_key(text: str) -> str:
    """翻訳キャッシュ用の MD5 ハッシュキーを生成する。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def translate_description(en_text: str, use_api: Optional[bool] = None) -> str:
    """
    英語説明文を日本語に翻訳。

    ``use_api`` の挙動:

    - ``None`` (デフォルト): ``DEEPL_API_KEY`` 環境変数が設定されていれば
      DeepL API を使用し、未設定ならヒューリスティック翻訳にフォールバック。
    - ``True``: DeepL API を明示的に使用（キー未設定や API エラー時は
      ヒューリスティックにフォールバック）。
    - ``False``: API を使わずヒューリスティック翻訳のみ。

    Args:
        en_text: 英語説明文
        use_api: API 使用を制御（None で自動判定）

    Returns:
        翻訳済みテキスト（失敗時はヒューリスティック翻訳結果を返す）
    """
    if not en_text:
        return ""

    # use_api が None の場合、環境変数の有無で自動判定
    if use_api is None:
        use_api = bool(os.getenv("DEEPL_API_KEY"))

    if use_api:
        api_key = os.getenv("DEEPL_API_KEY")
        if not api_key:
            logger.warning(
                "use_api=True but DEEPL_API_KEY not set; "
                "falling back to heuristic translation"
            )
            return _heuristic_translate(en_text)

        # キャッシュチェック
        key = _cache_key(en_text)
        if key in _translation_cache:
            logger.debug("Translation cache hit for %s", key[:8])
            return _translation_cache[key]

        # DeepL API 呼び出し
        translated = _translate_via_deepl(en_text, api_key)
        if translated is not None:
            _translation_cache[key] = translated
            return translated

        # API 失敗時はヒューリスティックにフォールバック
        logger.warning(
            "DeepL API failed; falling back to heuristic translation"
        )
        return _heuristic_translate(en_text)
    else:
        # API 未使用時はヒューリスティック翻訳
        return _heuristic_translate(en_text)


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
