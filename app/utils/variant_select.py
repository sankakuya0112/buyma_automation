"""Shopify バリアントから「出品価格の基準」と「その価格で出せるサイズ」を決める。

2026-10 以前は在庫ありの最安バリアントの価格で原価計算しながら、在庫ありの **全サイズ**
を出品していた。サイズで値段が違う商品 (大きいサイズだけ高い等) は、高いサイズが
売れると赤字になる。ここでは最安価格と同じ (≤ 最安 + 0.005) サイズだけを出品対象にし、
それより高いサイズは priced_out_sizes として記録する (別価格で出すなら別出品にする)。

オプションの位置 (option1 がサイズとは限らない。Color / Size の 2 軸の店もある) は
商品の options (名前) から判定する。色の軸がある場合は、基準バリアントと同じ色の中だけで
サイズを選ぶ (別の色の在庫・価格を混ぜない)。
"""

from __future__ import annotations

from typing import Optional

PRICE_TOLERANCE = 0.005

_SIZE_NAMES = ("size", "taglia", "taille", "größe", "groesse", "grosse", "talla", "misura", "サイズ")
_COLOR_NAMES = ("color", "colour", "colore", "couleur", "farbe", "カラー", "色")


def variant_price(v: dict) -> float:
    try:
        return float(v.get("price", 0))
    except (TypeError, ValueError):
        return float("inf")


def _option_name(opt) -> str:
    if isinstance(opt, dict):
        return str(opt.get("name") or "")
    return str(opt or "")


def option_positions(options) -> tuple[Optional[int], Optional[int]]:
    """商品の options → (サイズの位置 1-3 or None, 色の位置 1-3 or None)。

    options が無い (旧データ / テスト) ときは従来どおり option1 = サイズとみなす。
    """
    if not options:
        return 1, None
    names = [_option_name(o).strip().lower() for o in options][:3]
    size_pos = color_pos = None
    for i, n in enumerate(names, 1):
        if size_pos is None and any(k in n for k in _SIZE_NAMES):
            size_pos = i
        elif color_pos is None and any(k in n for k in _COLOR_NAMES):
            color_pos = i
    if size_pos is None and color_pos is None and len(names) == 1 and names[0] != "title":
        size_pos = 1   # 名前が分からない 1 軸 (例: "Taglia/Size" 以外の表記) はサイズ扱い
    return size_pos, color_pos


def option_value(v: dict, pos: Optional[int]) -> str:
    if not pos:
        return ""
    val = str(v.get(f"option{pos}") or "").strip()
    return "" if val.lower() == "default title" else val


def _join_unique(sizes) -> str:
    seen, out = set(), []
    for s in sizes:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return ", ".join(out)


def all_sizes(variants: list[dict], options=None) -> str:
    size_pos, _ = option_positions(options)
    return _join_unique(option_value(v, size_pos) for v in variants or [])


def select_listing_variants(variants: list[dict], options=None) -> dict:
    """戻り値: {"variant": 価格・SKU の基準バリアント (在庫なしなら先頭) or None,
                "available": 在庫ありか,
                "available_sizes": 基準価格で出品できる在庫ありサイズ ("S, M"),
                "priced_out_sizes": 在庫はあるが基準価格より高いサイズ (同じ色の中),
                "listing_color": 色の軸がある場合の基準バリアントの色 (無ければ "")}"""
    variants = list(variants or [])
    empty = {"variant": None, "available": False, "available_sizes": "", "priced_out_sizes": "",
             "listing_color": ""}
    if not variants:
        return empty
    size_pos, color_pos = option_positions(options)
    avail = [v for v in variants if v.get("available", False)]
    if not avail:
        return {**empty, "variant": variants[0]}
    base = min(avail, key=variant_price)
    color = option_value(base, color_pos)
    if color_pos:
        avail = [v for v in avail if option_value(v, color_pos) == color]
    limit = variant_price(base) + PRICE_TOLERANCE
    listable = [option_value(v, size_pos) for v in avail if variant_price(v) <= limit]
    priced_out = [option_value(v, size_pos) for v in avail if variant_price(v) > limit]
    listable_str = _join_unique(listable)
    priced_out_str = _join_unique(s for s in priced_out if s not in set(listable))
    return {"variant": base, "available": True, "available_sizes": listable_str,
            "priced_out_sizes": priced_out_str, "listing_color": color}
