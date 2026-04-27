"""BUYMA 出品フォーム用の純粋関数群。

scripts/buyma_auto_listing.py から切り出した、テストしやすい純粋関数。
副作用なし、Playwright 非依存。
"""

from __future__ import annotations

import re
import unicodedata


# ========== 色の英日マッピング（BUYMA 色の系統ドロップダウン用）==========
# baseblu 等は英語のカラー名（Black, Navy など）、BUYMA は日本語（ブラック、ネイビー等）。
# 部分一致ベースなので順序重要: より長いキーから先に並べる。
COLOR_JA_MAP: list[tuple[str, str]] = [
    # 長い / 複合キーを先に判定させる
    ("multicolor", "マルチカラー"), ("multi color", "マルチカラー"), ("multi-color", "マルチカラー"),
    ("off white", "ホワイト"), ("off-white", "ホワイト"),
    ("navy blue", "ネイビー"),
    ("wine red", "ワインレッド"), ("bordeaux", "ワインレッド"), ("burgundy", "ワインレッド"),
    # 単色
    ("navy", "ネイビー"),
    ("black", "ブラック"),
    ("white", "ホワイト"),
    ("red", "レッド"),
    ("pink", "ピンク"),
    ("blue", "ブルー"),
    ("green", "グリーン"),
    ("yellow", "イエロー"),
    ("orange", "オレンジ"),
    ("purple", "パープル"), ("violet", "パープル"),
    ("gray", "グレー"), ("grey", "グレー"),
    ("brown", "ブラウン"),
    ("beige", "ベージュ"), ("cream", "ベージュ"),
    ("gold", "ゴールド"),
    ("silver", "シルバー"),
    ("khaki", "カーキ"),
    ("wine", "ワインレッド"),
]


# ========== バリエーション出品用: IT → JP サイズマッピング ==========
# baseblu は Italian サイズ (32, 34, 36, 38, 40, 42, ...) を使う女性アパレル中心。
# BUYMA 「参考日本サイズ」ラベル (XS以下 / S / M / L / XL / XXL) に変換するための対応表。
# (numeric_lower_inclusive, numeric_upper_exclusive, jp_label)
_IT_SIZE_RANGES: list[tuple[int, int, str]] = [
    (0, 37, "XS以下"),    # IT32, 34, 36
    (37, 39, "S"),         # IT38
    (39, 43, "M"),         # IT40, 42
    (43, 47, "L"),         # IT44, 46
    (47, 51, "XL"),        # IT48, 50
    (51, 999, "XXL"),      # IT52+
]

# アルファベットサイズ (XS/S/M/L...) からの直接マッピング
_ALPHA_SIZE_TO_JP: dict[str, str] = {
    "XXS": "XS以下",
    "XS": "XS以下",
    "S": "S",
    "M": "M",
    "L": "L",
    "XL": "XL",
    "XXL": "XXL",
    "XXXL": "XXL",
    "FREE": "FREE",
    "UNI": "FREE",
    "ONE SIZE": "FREE",
    "TU": "FREE",
}


# ========== FOOTWEAR: EU/IT → JP cm マッピング ==========
# baseblu は女性靴 EU/IT サイズ(34〜42)中心。BUYMA の靴カテゴリは
# 「参考日本サイズ」が cm 単位 (21cm以下 / 21.5cm / ... / 27cm以上)。
# 一般的な変換表(EU → JP cm):
_EU_SHOE_TO_JP_CM: dict[float, str] = {
    34.0: "21cm以下",
    34.5: "21.5cm",
    35.0: "22cm",
    35.5: "22.5cm",
    36.0: "23cm",
    36.5: "23cm",
    37.0: "23.5cm",
    37.5: "24cm",
    38.0: "24.5cm",
    38.5: "25cm",
    39.0: "25cm",
    39.5: "25.5cm",
    40.0: "26cm",
    40.5: "26cm",
    41.0: "26.5cm",
    41.5: "26.5cm",
}


def normalize_size_for_buyma(raw_size: str) -> str:
    """仕入先の size 表記を BUYMA の 参考日本サイズ ドロップダウンに合う値に変換する。

    - "UNI" / "ONE SIZE" / 空 → "FREE"
    - "XS" / "S" / "M" / "L" / "XL" / "XXL" → そのまま（アパレル用）
    - 数字のみ（例 "40", "42"）→ そのまま（シューズ・バッグ用の EU サイズ想定）
    - それ以外 → そのまま返し、BUYMA 側で partial match に任せる
    """
    if not raw_size:
        return "FREE"
    s = raw_size.strip().upper()
    if s in ("UNI", "UNIC", "UNICA", "ONE SIZE", "ONESIZE", "OS", "FREE SIZE", "FREESIZE", "TU", "TAILLE UNIQUE"):
        return "FREE"
    return raw_size.strip()


def _map_footwear_to_jp_cm(raw_size: str) -> str:
    """靴サイズ(EU/IT 数値)を BUYMA 参考日本サイズの cm ラベルに変換する。"""
    s = (raw_size or "").strip().upper()
    if not s:
        return "指定なし"
    # 'IT40.5' 等の接頭辞を剥がして数値抽出
    m = re.match(r"(?:IT|EU|FR)?\s*(\d+(?:\.\d+)?)", s)
    if not m:
        return "指定なし"
    try:
        n = float(m.group(1))
    except ValueError:
        return "指定なし"
    if n <= 33.5:
        return "21cm以下"
    if n >= 42.0:
        return "27cm以上"
    # 0.5刻み丸め
    key = round(n * 2) / 2
    return _EU_SHOE_TO_JP_CM.get(key, "指定なし")


def map_size_to_jp_reference(raw_size: str, product_type: str = "") -> str:
    """仕入先サイズ文字列を BUYMA の「参考日本サイズ」ラベルに変換する。

    product_type:
      - FOOTWEAR: EU/IT 数値 → cm ラベル (例 '37.5' → '24cm')
      - その他: 数値は XS/S/M/L/XL、アルファベットはそのまま

    例:
      map('40', 'CLOTHING') → 'M'
      map('37.5', 'FOOTWEAR') → '24cm'
      map('39.5', 'FOOTWEAR') → '25.5cm'
      map('XS', '') → 'XS以下'
      map('', '') → '指定なし'
    """
    pt = (product_type or "").strip().upper()
    if pt == "FOOTWEAR":
        return _map_footwear_to_jp_cm(raw_size)
    s = (raw_size or "").strip().upper()
    if not s:
        return "指定なし"
    if s in _ALPHA_SIZE_TO_JP:
        return _ALPHA_SIZE_TO_JP[s]
    # 先頭の数値を抽出（"IT40" や "40.5" 等にも耐える）
    m = re.match(r"(\d+)", s)
    if m:
        n = int(m.group(1))
        for lo, hi, label in _IT_SIZE_RANGES:
            if lo <= n < hi:
                return label
    return "指定なし"


def classify_size_category(product_type: str) -> str:
    """product_type からサイズセクションの扱いを決める。

    - 'variation': バリエーションあり（CLOTHING, FOOTWEAR）
    - 'single': バリエーションなし（BAGS, ACCESSORIES, その他）
    """
    pt = (product_type or "").strip().upper()
    if pt in ("CLOTHING", "FOOTWEAR"):
        return "variation"
    return "single"


def format_size_name_for_listing(raw_size: str, product_type: str) -> str:
    """BUYMA 出品フォームの「サイズ名」欄に入れる表記を作る。

    - CLOTHING: 数値のみなら 'IT<n>' プレフィックス (例 '40' → 'IT40')
    - FOOTWEAR: 同上 ('IT' プレフィックス)
    - BAGS/ACCESSORIES: そのまま（バッグに付けても意味ないので）
    - アルファベットサイズはそのまま（'XS', 'M' 等）
    """
    s = (raw_size or "").strip()
    if not s:
        return ""
    pt = (product_type or "").strip().upper()
    if pt in ("CLOTHING", "FOOTWEAR") and re.fullmatch(r"\d+(?:\.\d+)?", s):
        return f"IT{s}"
    return s.upper() if re.fullmatch(r"[a-zA-Z]+", s) else s


def translate_color_to_jp(en_color: str) -> str:
    """英語の色名を BUYMA 色の系統ラベル（日本語）に変換する。

    マッチしない場合は「マルチカラー」を返す（万能のデフォルト）。
    """
    if not en_color:
        return "マルチカラー"
    lower = en_color.lower()
    for en, ja in COLOR_JA_MAP:
        if en in lower:
            return ja
    return "マルチカラー"


def _strip_accents(text: str) -> str:
    """Latin 系のアクセント文字 (è, é, â, ç 等) を ASCII に変換する。

    BUYMA の商品コメント欄は「不正な文字 è」等で validation ブロックするため必須。

    注意: NFD 分解するとカタカナ/ひらがなの 濁点(U+3099) / 半濁点(U+309A) も
    combining mark として分離される。これらは Japanese 用の必須マークなので
    除去してはいけない (パ → ハ, ゴ → コ のように読みが壊れる)。
    """
    if not text:
        return text
    _JP_COMBINING_MARKS = ("゙", "゚")  # 濁点・半濁点
    nfd = unicodedata.normalize("NFD", text)
    filtered = "".join(
        c for c in nfd
        if unicodedata.category(c) != "Mn" or c in _JP_COMBINING_MARKS
    )
    # NFC で結合して 濁点付きカタカナ(パ, ピ, ブ, ゴ 等)を再構築する
    return unicodedata.normalize("NFC", filtered)
