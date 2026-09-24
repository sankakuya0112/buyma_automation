"""BUYMA カテゴリ分類 (cheap 階層 / Haiku 4.5)。

決定論的なキーワード辞書 (data/categories.json) を先に当て、**キーワードが当たらず
product_type のデフォルトに落ちた商品だけ** AI に番号で選ばせる。
番号回答なので出力トークンが極小で、かつ実在カテゴリ以外を返せない。
第 2 階層は `_tier2_valid` に無いものを拒否する (BUYMA の 422 対策、CLAUDE.md §16)。
"""

from __future__ import annotations

import json
from typing import Optional

from app.ai.router import policy_for

GLOBAL_DEFAULT = ["レディースファッション", "小物", "その他"]


def keyword_category_path(title: str, product_type: str, cat_data: dict) -> tuple[list[str], str]:
    """scripts/buyma_auto_listing.get_category_path と同じ規則で 3 階層パスを返す。

    Returns:
        (path, source)  source は 'keyword' | 'type_default' | 'global_default'
    """
    t = (title or "").lower()
    pt = (product_type or "").strip().upper()
    for mapping in cat_data.get("mappings", []):
        if str(mapping.get("product_type", "")).upper() != pt:
            continue
        for rule in mapping.get("keywords", []):
            for kw in rule.get("match", []):
                if kw.lower() in t:
                    return list(rule["path"]), "keyword"
        return list(mapping.get("default") or cat_data.get("default") or GLOBAL_DEFAULT), "type_default"
    return list(cat_data.get("default") or GLOBAL_DEFAULT), "global_default"


def allowed_paths(cat_data: dict) -> list[list[str]]:
    """categories.json に出てくる全 3 階層パス (第 2 階層が検証済みのものだけ)。"""
    tier2_valid = set(cat_data.get("_tier2_valid") or [])
    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []

    def _add(path):
        if not path or len(path) != 3:
            return
        if tier2_valid and path[1] not in tier2_valid:
            return
        key = tuple(path)
        if key not in seen:
            seen.add(key)
            out.append(list(path))

    _add(cat_data.get("default"))
    for mapping in cat_data.get("mappings", []):
        _add(mapping.get("default"))
        for rule in mapping.get("keywords", []):
            _add(rule.get("path"))
    return out


def build_system_prompt(paths: list[list[str]]) -> str:
    lines = [f"{i}: {' > '.join(p)}" for i, p in enumerate(paths)]
    return (
        "あなたはBUYMAの出品カテゴリ分類担当です。商品情報を読み、次の番号付きカテゴリ一覧から"
        "最も適切なものを 1 つ選び、番号 (category_index) で答えてください。\n"
        "一覧に無いカテゴリは選べません。迷う場合は最も近い上位概念を選び confidence を low にしてください。\n"
        "レディース/メンズは商品情報 (product_type やタイトル、説明文の men/women 表記) から判断します。\n\n"
        "## カテゴリ一覧\n" + "\n".join(lines) + "\n"
    )


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category_index": {"type": "integer"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["id", "category_index", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _compact(product: dict, pid: str) -> dict:
    desc = (product.get("description_en") or "")[:300]
    return {
        "id": pid,
        "brand": (product.get("vendor") or product.get("brand") or "").strip(),
        "title": (product.get("title") or "").strip(),
        "product_type": (product.get("product_type") or "").strip(),
        "description_en": desc,
    }


def classify_categories(
    products: list[dict], client, cat_data: dict, ids: Optional[list[str]] = None,
) -> dict[str, dict]:
    """{id: {"path": [...], "confidence": str}}。AI 不可・低信頼の商品は含まれない。"""
    if not products:
        return {}
    if ids is None:
        ids = [str(p.get("sku") or f"row{i}") for i, p in enumerate(products)]
    paths = allowed_paths(cat_data)
    if not paths:
        return {}
    system = build_system_prompt(paths)
    policy = policy_for("category")
    results: dict[str, dict] = {}
    for start in range(0, len(products), policy.items_per_call):
        chunk = products[start:start + policy.items_per_call]
        chunk_ids = ids[start:start + policy.items_per_call]
        payload = [_compact(p, pid) for p, pid in zip(chunk, chunk_ids)]
        user = "次の商品のカテゴリを選んでください。\n\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        data = client.complete_json("category", system, user, OUTPUT_SCHEMA)
        if not data or not isinstance(data.get("items"), list):
            continue
        for item in data["items"]:
            pid = str(item.get("id") or "")
            try:
                idx = int(item.get("category_index"))
            except (TypeError, ValueError):
                continue
            conf = str(item.get("confidence") or "low")
            if pid in chunk_ids and 0 <= idx < len(paths) and conf in ("high", "medium"):
                results[pid] = {"path": list(paths[idx]), "confidence": conf}
    return results


def resolve_category(product: dict, cat_data: dict, ai_result: Optional[dict] = None) -> tuple[list[str], str]:
    """決定論 → AI の順で最終カテゴリを決める。source は keyword|ai|type_default|global_default。"""
    path, source = keyword_category_path(product.get("title", ""), product.get("product_type", ""), cat_data)
    if source == "keyword":
        return path, source
    if ai_result and ai_result.get("path"):
        return list(ai_result["path"]), "ai"
    return path, source
