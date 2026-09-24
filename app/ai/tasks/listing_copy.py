"""出品文生成 (cheap 階層 / Haiku 4.5)。

英語の商品情報 → BUYMA 用の日本語タイトル・説明文・検索キーワード・系統色。
1 リクエストに複数商品をまとめて送り、system prompt の再送を減らす。
AI が使えない場合は空 dict を返し、呼び出し側が従来の辞書翻訳にフォールバックする。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.ai.router import policy_for
from app.utils.listing_helpers import _strip_accents, _trim_buyma_title, clean_source_description

# 説明文原文の送信上限 (文字)。長すぎる原文は入力トークンの浪費
MAX_DESC_CHARS = 1200

BUYMA_COLOR_FAMILIES = [
    "ブラック", "ホワイト", "グレー", "ベージュ", "ブラウン", "レッド", "ピンク",
    "オレンジ", "イエロー", "グリーン", "ブルー", "パープル", "ゴールド", "シルバー",
    "マルチカラー", "その他",
]

SYSTEM_PROMPT = """あなたはBUYMAで実績のあるパーソナルショッパーの出品担当です。
海外ECサイトの英語の商品情報から、BUYMAで検索されやすく、規約に沿った日本語の出品文を作ります。

## 出力ルール
- 入力は商品の配列。各商品について同じ id を付けて返す。
- title_ja: 全角30文字(半角60文字)以内。形式は「【BRAND】商品種別 特徴語」。ブランド名は英語表記のまま。
  装飾記号(★☆♪◆■)や「正規品」「最安」「送料無料」はタイトルに入れない。アクセント付き文字(è, é, ü等)は使わず基本ラテン文字に直す。
- description_ja: 200〜400文字。原文にある素材・仕様・ディテール・サイズ感・カラーを自然な日本語で説明する。
  原文に無い情報(素材・原産国・付属品など)を推測で書かない。価格・仕入先名・割引率は書かない(別途固定文が付く)。
  誇大表現(「絶対」「最安値」「完璧」)、他社比較、断定的な品質保証は書かない。
- keywords: 日本語の検索語を5〜8個。ブランドのカタカナ読み、商品種別、素材、特徴語を含める。
- color_ja: 次の系統色から1つ: %s

## 品質基準
- 日本人の購入者が読んで商品の姿が正確に分かること。
- 翻訳調ではなく、ショップの商品ページとして自然な文体(です・ます調)。
""" % " / ".join(BUYMA_COLOR_FAMILIES)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title_ja": {"type": "string"},
                    "description_ja": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "color_ja": {"type": "string"},
                },
                "required": ["id", "title_ja", "description_ja", "keywords", "color_ja"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_DECORATION_RE = re.compile(r"[★☆♪◆■●▲♥♡※]+")


def compact_product(product: dict, pid: str) -> dict:
    """AI に渡す最小限のフィールドだけを抜き出す (トークン節約)。"""
    desc = clean_source_description(product.get("description_en") or "")
    if len(desc) > MAX_DESC_CHARS:
        desc = desc[:MAX_DESC_CHARS] + "…"
    return {
        "id": pid,
        "brand": (product.get("vendor") or product.get("brand") or "").strip(),
        "title": (product.get("title") or product.get("name") or "").strip(),
        "product_type": (product.get("product_type") or "").strip(),
        "sku": (product.get("sku") or "").strip(),
        "color": (product.get("color") or "").strip(),
        "sizes": (product.get("sizes") or "").strip(),
        "season": (product.get("season") or "").strip(),
        "description_en": desc,
    }


def sanitize_copy(item: dict, brand: str) -> Optional[dict]:
    """AI 出力を BUYMA 制約に合わせて後処理。使えない場合は None。"""
    title = _strip_accents(str(item.get("title_ja") or "")).strip()
    title = _DECORATION_RE.sub("", title)
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None
    brand_clean = _strip_accents(brand).strip()
    if brand_clean and not title.startswith("【"):
        title = f"【{brand_clean}】{title}"
    title = _trim_buyma_title(title, 60)

    desc = _strip_accents(str(item.get("description_ja") or "")).strip()
    if len(desc) < 30:
        desc = ""

    keywords_raw = item.get("keywords") or []
    keywords: list[str] = []
    seen: set[str] = set()
    for k in keywords_raw:
        k = _strip_accents(str(k)).strip()
        if k and k not in seen:
            seen.add(k)
            keywords.append(k)
        if len(keywords) >= 10:
            break

    color = str(item.get("color_ja") or "").strip()
    if color not in BUYMA_COLOR_FAMILIES:
        color = ""

    return {
        "title_ja": title,
        "description_ja": desc,
        "keywords": keywords,
        "color_ja": color,
    }


def generate_listing_copy(products: list[dict], client, ids: Optional[list[str]] = None) -> dict[str, dict]:
    """商品リスト → {id: {title_ja, description_ja, keywords, color_ja}}。

    AI が使えない・失敗した商品は結果に含まれない (呼び出し側でフォールバック)。
    """
    if not products:
        return {}
    if ids is None:
        ids = [str(p.get("sku") or f"row{i}") for i, p in enumerate(products)]
    policy = policy_for("listing_copy")
    results: dict[str, dict] = {}
    brand_by_id = {pid: (p.get("vendor") or p.get("brand") or "") for pid, p in zip(ids, products)}

    for start in range(0, len(products), policy.items_per_call):
        chunk = products[start:start + policy.items_per_call]
        chunk_ids = ids[start:start + policy.items_per_call]
        payload = [compact_product(p, pid) for p, pid in zip(chunk, chunk_ids)]
        user = "次の商品の出品文を作成してください。\n\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        data = client.complete_json("listing_copy", SYSTEM_PROMPT, user, OUTPUT_SCHEMA)
        if not data or not isinstance(data.get("items"), list):
            continue
        for item in data["items"]:
            pid = str(item.get("id") or "")
            if pid not in brand_by_id:
                continue
            cleaned = sanitize_copy(item, brand_by_id[pid])
            if cleaned:
                results[pid] = cleaned
    return results
