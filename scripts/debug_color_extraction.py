"""
scripts/debug_color_extraction.py
----------------------------------
色抽出ロジックの診断スクリプト。

CSV の color 列が空になっている商品について、
  - Shopify 個別 JSON の色関連フィールド
  - 商品ページ HTML の色関連マークアップ
  - _extract_color / _extract_color_from_html の戻り値
を表示する。これを元に抽出パターンを追加・修正する。

使い方:
    python3 scripts/debug_color_extraction.py              # CSV の先頭 empty-color 行
    python3 scripts/debug_color_extraction.py --index 1    # CSV の N 行目 (1-based)
    python3 scripts/debug_color_extraction.py --url URL    # URL 指定
"""

import argparse
import csv
import glob
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from baseblu_sales_to_csv import (  # noqa: E402
    _extract_color,
    _extract_color_from_html,
    fetch_product_detail,
    fetch_product_html,
)


# _extract_color_from_html の各パターンを個別に試すための定義
_HTML_PATTERNS = [
    ("P0 product-page__colors__info__title",
     r'<div[^>]*class="[^"]*product-page__colors__info__title(?:--desktop)?[^"]*"[^>]*>\s*([A-Za-z][A-Za-z \-/]+?)\s*</div>'),
    ("P1a data-color",
     r'data-color(?:-name)?\s*=\s*["\']([A-Za-z][A-Za-z \-/]+)["\']'),
    ("P1b data-swatch",
     r'data-swatch(?:-color)?\s*=\s*["\']([A-Za-z][A-Za-z \-/]+)["\']'),
    ("P2a span color-name/product-color/swatch-label",
     r'<span[^>]*class="[^"]*(?:color-name|product-color|swatch-label)[^"]*"[^>]*>\s*([A-Z][A-Za-z \-/]+)\s*</span>'),
    ("P2b div color-name/product-color/swatch-label",
     r'<div[^>]*class="[^"]*(?:color-name|product-color|swatch-label)[^"]*"[^>]*>\s*([A-Z][A-Za-z \-/]+)\s*</div>'),
    ("P4 JSON \"color\":\"XXX\"",
     r'"color"\s*:\s*"([A-Za-z][A-Za-z \-/]+)"'),
]


def pick_row(csv_path, index=None):
    """CSV を読んで対象行を返す。index 指定なしなら先頭の empty-color 行。"""
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    if index is not None:
        if 1 <= index <= len(rows):
            return rows[index - 1]
        print(f"[ERROR] --index {index} が範囲外 (1..{len(rows)})")
        return None
    for r in rows:
        if not (r.get("color") or "").strip():
            return r
    return rows[0]


def handle_from_url(url):
    m = re.search(r"/products/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def snippet(html, keyword, context=200):
    m = re.search(re.escape(keyword), html, re.IGNORECASE)
    if not m:
        return None
    start = max(0, m.start() - context // 2)
    end = min(len(html), m.end() + context)
    return html[start:end].replace("\n", " ")


def diagnose(title, product_url):
    handle = handle_from_url(product_url)
    print(f"[title] {title}")
    print(f"[url]   {product_url}")
    print(f"[handle] {handle}")
    print()

    if not handle:
        print("[ABORT] URL から handle を抽出できず")
        return

    # 1) Shopify 個別 JSON
    print("=" * 60)
    print("1) Shopify 個別 JSON 経由 (_extract_color)")
    print("=" * 60)
    detail = fetch_product_detail(handle)
    if not detail:
        print("  [WARN] 個別 JSON 取得失敗 or 空")
    else:
        extracted = _extract_color(detail)
        print(f"  _extract_color() → {extracted!r}")
        print()
        print("  [options]")
        for opt in detail.get("options") or []:
            print(f"    name={opt.get('name')!r}  values={opt.get('values')!r}")
        tags = detail.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        print(f"  [tags(上位20)] {tags[:20]}")
        body = (detail.get("body_html") or "")
        body_has_color = re.search(r"Colou?r\s*[:：]", body, re.IGNORECASE)
        print(f"  [body_html len] {len(body)}  body に 'Color:' あり? {bool(body_has_color)}")
    print()

    # 2) HTML ページ
    print("=" * 60)
    print("2) HTML ページ経由 (_extract_color_from_html)")
    print("=" * 60)
    html = fetch_product_html(handle)
    print(f"  [HTML size] {len(html)} bytes")
    print(f"  _extract_color_from_html() → {_extract_color_from_html(html)!r}")
    print()
    print("  [各パターン個別テスト]")
    for name, pat in _HTML_PATTERNS:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            print(f"    ✅ {name}: {m.group(1)!r}")
        else:
            print(f"    ❌ {name}")
    print()
    print("  [HTML 内キーワード snippet]")
    for kw in [
        "product-page__colors",
        "colors__info",
        "color-name",
        "data-color",
        "swatch",
        "variant-color",
        "color:",
    ]:
        sn = snippet(html, kw, context=260)
        if sn:
            print(f"    🔍 {kw!r} → ...{sn[:320]}...")
        else:
            print(f"    ⚪ {kw!r} 見つからず")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, help="CSV 行番号 (1-based)")
    parser.add_argument("--url", help="商品 URL を直接指定")
    args = parser.parse_args()

    if args.url:
        diagnose("(URL 指定)", args.url)
        return

    # 最新 CSV から対象行を選ぶ
    candidates = sorted(glob.glob("outputs/reports/*_baseblu_profitable_products.csv"))
    if not candidates:
        print("[ERROR] outputs/reports/*_baseblu_profitable_products.csv が見つからない")
        return
    csv_path = candidates[-1]
    print(f"[CSV] {csv_path}")
    row = pick_row(csv_path, index=args.index)
    if not row:
        return
    print(f"[CSV row color] {row.get('color')!r}")
    print()
    diagnose(row.get("title", ""), row.get("product_url", ""))


if __name__ == "__main__":
    main()
