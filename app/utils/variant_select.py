"""Shopify バリアントから「出品価格の基準」と「その価格で出せるサイズ」を決める。

2026-10 以前は在庫ありの最安バリアントの価格で原価計算しながら、在庫ありの **全サイズ**
を出品していた。サイズで値段が違う商品 (大きいサイズだけ高い等) は、高いサイズが
売れると赤字になる。ここでは最安価格と同じ (≤ 最安 + 0.005) サイズだけを出品対象にし、
それより高いサイズは priced_out_sizes として記録する (別価格で出すなら別出品にする)。
"""

from __future__ import annotations

from typing import Optional

PRICE_TOLERANCE = 0.005


def variant_price(v: dict) -> float:
    try:
        return float(v.get("price", 0))
    except (TypeError, ValueError):
        return float("inf")


def _size(v: dict) -> str:
    return (v.get("option1") or "").strip()


def _join_unique(sizes) -> str:
    seen, out = set(), []
    for s in sizes:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return ", ".join(out)


def select_listing_variants(variants: list[dict]) -> dict:
    """戻り値: {"variant": 価格・SKU の基準バリアント (在庫なしなら先頭) or None,
                "available": 在庫ありか,
                "available_sizes": 基準価格で出品できる在庫ありサイズ ("S, M"),
                "priced_out_sizes": 在庫はあるが基準価格より高いサイズ}"""
    variants = list(variants or [])
    if not variants:
        return {"variant": None, "available": False, "available_sizes": "", "priced_out_sizes": ""}
    avail = [v for v in variants if v.get("available", False)]
    if not avail:
        return {"variant": variants[0], "available": False, "available_sizes": "", "priced_out_sizes": ""}
    base: Optional[dict] = min(avail, key=variant_price)
    limit = variant_price(base) + PRICE_TOLERANCE
    listable = [_size(v) for v in avail if variant_price(v) <= limit]
    priced_out = [_size(v) for v in avail if variant_price(v) > limit]
    listable_str = _join_unique(listable)
    # 同じサイズ名が安い方と高い方の両方にある (色違い等) なら出品可能側に寄せる
    priced_out_str = _join_unique(s for s in priced_out if s not in set(listable))
    return {"variant": base, "available": True,
            "available_sizes": listable_str, "priced_out_sizes": priced_out_str}
