"""
shopify_sales_to_csv.py — Shopify 系の仕入先から セール商品を取得して CSV にする (汎用版)
--------------------------------------------------------------------------
仕入先ごとにスクリプトを書く代わりに、`data/sources.json` に設定を 1 ブロック
足すだけで新しい仕入先を追加できるようにしたもの。

使い方 (Mac のターミナルで):

    # 設定済みの仕入先を一覧表示
    python3 scripts/shopify_sales_to_csv.py --list

    # ① まず取得できるか確かめる (課金なし・CSV も作らない)
    python3 scripts/shopify_sales_to_csv.py --source antonioli --probe

    # ② 取得できたら CSV を作る
    python3 scripts/shopify_sales_to_csv.py --source antonioli

    # ③ 利益計算にかける (既存スクリプトがそのまま使える)
    python3 scripts/filter_baseblu_profitable.py --source antonioli

    # セール一覧の URL が違っていた場合は上書きできる
    python3 scripts/shopify_sales_to_csv.py --source antonioli \
        --url "https://antonioli.eu/collections/sale-woman/products.json"

    # ネットに繋がない動作確認 (モックデータ 3 件)
    python3 scripts/shopify_sales_to_csv.py --source antonioli --test

出力: outputs/reports/YYYY-MM-DD_<source>_sales_products_sorted.csv

設計メモ:
  - Shopify の商品解析 (色 / サイズ / SKU / シーズン) は
    scripts/baseblu_sales_to_csv.py の関数を再利用する (重複実装しない)
  - baseblu は商品ページ HTML からの色抽出があるため、専用の
    scripts/baseblu_sales_to_csv.py を引き続き使うこと (本スクリプトは JSON のみ)
  - チェックアウト / カート / アカウント領域には触れない。公開されている
    collection の商品 JSON だけを、設定した間隔を空けて取得する
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# 汎用 Shopify 解析ヘルパー (baseblu スクレイパーから再利用)
from baseblu_sales_to_csv import (  # noqa: E402
    _extract_color,
    _extract_season,
    _extract_sizes,
    _extract_sku_from_description,
    _extract_sku_from_variant,
    strip_html,
)

from app.core.sources import ConfigSource, get_source_config, load_source_configs  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "reports"

# CSV の列。filter_baseblu_profitable.py が読む形式に揃えること。
CSV_FIELDNAMES = [
    "title", "vendor", "product_type", "sku",
    "color", "sizes", "available_sizes", "season",
    "sale_price", "original_price", "discount_rate", "available",
    "description_en", "image_url", "sub_images", "product_url",
    "source_name", "currency", "landed_cost_basis",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

MAX_IMAGES = 5


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------

def build_page_url(products_json_url: str, page: int, limit: int = 250) -> str:
    """Shopify のページネーション付き URL を組み立てる。"""
    sep = "&" if "?" in products_json_url else "?"
    return f"{products_json_url}{sep}page={page}&limit={limit}"


def shop_base_url(products_json_url: str) -> str:
    """products.json の URL からショップのベース URL を取り出す。"""
    parsed = urlparse(products_json_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_all_products(
    products_json_url: str, max_pages: int = 40, delay_sec: float = 1.0
) -> list[dict]:
    """collection の products.json を全ページ取得する。"""
    import requests

    all_products: list[dict] = []
    print(f"商品を取得中... ({products_json_url})")
    for page in range(1, max_pages + 1):
        url = build_page_url(products_json_url, page)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️ ページ {page} の取得に失敗: {e}")
            if page == 1:
                print("  💡 --probe を実行して、URL と取得可否を確認してください:")
                print(f"     python3 scripts/shopify_sales_to_csv.py --source <名前> --probe")
            break

        products = data.get("products", []) or []
        if not products:
            print(f"  → ページ {page}: 商品なし（終了）")
            break

        print(f"  → ページ {page}: {len(products)} 件取得")
        all_products.extend(products)
        time.sleep(delay_sec)

    return all_products


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def parse_shopify_product(product: dict, source: ConfigSource) -> dict | None:
    """Shopify の商品 dict を CSV 1 行に変換する。

    baseblu 版 parse_product と同じ出力スキーマ。違いは商品ページ HTML を
    取りに行かない点 (サイトごとに HTML 構造が違うため JSON の情報だけを使う)。
    """
    variants = product.get("variants", []) or []
    if not variants:
        return None

    # 在庫判定はバリアント横断。variants[0] だけ見ると「最初のサイズだけ売切」の
    # 商品を在庫なし扱いにして機会損失する (2026-06 の実バグ)。
    available = any(v.get("available", False) for v in variants)

    def _price(v: dict) -> float:
        try:
            return float(v.get("price", 0))
        except (TypeError, ValueError):
            return float("inf")

    available_variants = [v for v in variants if v.get("available", False)]
    variant = min(available_variants, key=_price) if available_variants else variants[0]

    sku = _extract_sku_from_variant(variant.get("sku", ""), variant.get("option1", ""))

    try:
        sale_price = float(variant.get("price", 0))
    except (TypeError, ValueError):
        sale_price = 0.0
    try:
        compare_at = float(variant.get("compare_at_price") or 0)
    except (TypeError, ValueError):
        compare_at = 0.0

    if compare_at > 0 and sale_price < compare_at:
        original_price = compare_at
        discount_rate = round((1 - sale_price / compare_at) * 100, 1)
    else:
        original_price = sale_price
        discount_rate = 0.0

    body_html = product.get("body_html", "") or ""
    description_en = strip_html(body_html) if body_html else ""
    desc_sku = _extract_sku_from_description(description_en)
    if desc_sku:
        sku = desc_sku

    images = product.get("images", []) or []
    image_urls = [img.get("src", "") for img in images[:MAX_IMAGES] if img.get("src")]

    return {
        "title": product.get("title", ""),
        "vendor": product.get("vendor", ""),
        "product_type": product.get("product_type", ""),
        "sku": sku,
        "color": _extract_color(product),
        "sizes": _extract_sizes(variants, only_available=False),
        "available_sizes": _extract_sizes(variants, only_available=True),
        "season": _extract_season(description_en),
        "sale_price": sale_price,
        "original_price": original_price,
        "discount_rate": discount_rate,
        "available": available,
        "description_en": description_en,
        "image_url": image_urls[0] if image_urls else "",
        "sub_images": "|".join(image_urls[1:]) if len(image_urls) > 1 else "",
        "product_url": source.product_url(product.get("handle", "")),
        "source_name": source.name,
        "currency": source.currency,
        "landed_cost_basis": source.landed_cost_basis,
    }


def save_to_csv(rows: list[dict], output_path: str | Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    in_stock = sum(1 for r in rows if r.get("available"))
    print(f"\n✅ CSV を保存しました: {output_path}")
    print(f"   合計 {len(rows)} 件 (在庫あり {in_stock} 件)")


# ---------------------------------------------------------------------------
# probe (取得できるか確かめる)
# ---------------------------------------------------------------------------

def probe_source(source: ConfigSource, url: str | None = None) -> int:
    """products.json が取れるかを確認して結果を表示する。終了コードを返す。"""
    import requests

    target = url or source.products_json_url
    print(f"🔍 {source.display_name} ({source.name}) の取得可否を確認します")
    print(f"   URL: {target}")

    try:
        resp = requests.get(build_page_url(target, page=1, limit=5), headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"   ❌ 接続できませんでした: {e}")
        print("   → ネットワークか URL の問題です。ブラウザで同じ URL を開いて確認してください。")
        return 1

    print(f"   HTTP ステータス: {resp.status_code}")
    if resp.status_code == 404:
        print("   ❌ このアドレスに一覧がありません (collection 名が違う可能性)。")
        _print_sale_collections(target)
        return 1
    if resp.status_code in (401, 403, 429):
        print("   ❌ アクセスを拒否されました (bot 対策の可能性)。")
        print("   → このサイトは自動取得が難しいため、手動仕入れ用の比較先に回してください。")
        return 1
    if resp.status_code >= 400:
        print("   ❌ エラー応答です。時間をおいて再実行するか URL を確認してください。")
        return 1

    try:
        data = resp.json()
    except Exception:
        head = (resp.text or "")[:120].replace("\n", " ")
        print("   ❌ JSON ではなく HTML が返りました (Shopify ではないか、機能が無効)。")
        print(f"   → 先頭: {head}")
        return 1

    products = data.get("products")
    if not isinstance(products, list):
        print("   ❌ JSON に products がありません。Shopify の商品一覧ではないようです。")
        return 1
    if not products:
        print("   ⚠️ JSON は取れましたが商品が 0 件です (collection 名が違う可能性)。")
        _print_sale_collections(target)
        return 1

    print(f"   ✅ 取得できました: このページに {len(products)} 件")
    discounted = 0
    for p in products:
        for v in p.get("variants", []) or []:
            if v.get("compare_at_price"):
                discounted += 1
                break
    first = products[0]
    variant = (first.get("variants") or [{}])[0]
    print(f"   例: {first.get('vendor', '?')} / {first.get('title', '?')[:48]}")
    print(f"       価格 {variant.get('price')} / 元値 {variant.get('compare_at_price')}")
    print(f"   割引情報 (compare_at_price) を持つ商品: {discounted}/{len(products)} 件")
    if discounted == 0:
        print("   ⚠️ 割引の元値が取れていません。セール専用の collection を指定し直してください。")
        _print_sale_collections(target)

    print()
    print("   次のステップ:")
    print(f"     python3 scripts/shopify_sales_to_csv.py --source {source.name}")
    print(f"     python3 scripts/filter_baseblu_profitable.py --source {source.name}")
    print("   ⚠️ 価格が「関税込み」か「VAT が引かれているか」はブラウザで")
    print("      チェックアウト直前まで進めて確認し、data/sources.json を直してください。")
    return 0


def _print_sale_collections(products_json_url: str, limit: int = 250) -> None:
    """セールっぽい collection 名の候補を表示する (handle 探し用)。"""
    import requests

    base = shop_base_url(products_json_url)
    if not base:
        return
    try:
        resp = requests.get(f"{base}/collections.json?limit={limit}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        collections = resp.json().get("collections", []) or []
    except Exception:
        print("   (collection 一覧は取得できませんでした)")
        return

    keywords = ("sale", "outlet", "saldi", "markdown", "discount", "promo")
    hits = [c.get("handle", "") for c in collections
            if any(k in str(c.get("handle", "")).lower() for k in keywords)]
    if hits:
        print("   💡 セールらしい collection 候補:")
        for h in hits[:15]:
            print(f"      {base}/collections/{h}/products.json")
    else:
        print(f"   💡 collection は {len(collections)} 件見つかりましたが、sale/outlet 系の名前はありません。")


# ---------------------------------------------------------------------------
# モックデータ (--test)
# ---------------------------------------------------------------------------

def mock_products() -> list[dict]:
    """--test 用のモック商品。ネットワーク不要で CSV 生成まで確認できる。"""
    return [
        {
            "title": "Leather Shoulder Bag",
            "vendor": "GUCCI",
            "handle": "gucci-leather-shoulder-bag",
            "product_type": "BAGS",
            "body_html": "<p>Iconic shoulder bag.</p><p>Sku: GG123_456</p>",
            "images": [{"src": "https://cdn.example.com/g1.jpg"},
                       {"src": "https://cdn.example.com/g2.jpg"}],
            "options": [{"name": "Size", "values": ["UNI"]},
                        {"name": "Color", "values": ["Black"]}],
            "variants": [
                {"sku": "GG123_456_UNI", "option1": "UNI", "price": "1200.0",
                 "compare_at_price": "2000.0", "available": True},
            ],
        },
        {
            "title": "Wool Midi Dress",
            "vendor": "KHAITE",
            "handle": "khaite-wool-midi-dress",
            "product_type": "CLOTHING",
            "body_html": "<p>Season: AW25</p>",
            "images": [{"src": "https://cdn.example.com/k1.jpg"}],
            "variants": [
                {"sku": "KH001_38", "option1": "38", "price": "700.0",
                 "compare_at_price": "1300.0", "available": False},
                {"sku": "KH001_40", "option1": "40", "price": "650.0",
                 "compare_at_price": "1300.0", "available": True},
            ],
        },
        {
            "title": "Sold Out Pumps",
            "vendor": "MANOLO BLAHNIK",
            "handle": "mb-pumps",
            "product_type": "FOOTWEAR",
            "body_html": "",
            "images": [],
            "variants": [
                {"sku": "MB9_37", "option1": "37", "price": "500.0",
                 "compare_at_price": "900.0", "available": False},
            ],
        },
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_source_list() -> None:
    """data/sources.json の一覧を表示する。"""
    try:
        configs = load_source_configs()
    except ValueError as e:
        print(f"❌ data/sources.json を読めません: {e}")
        return
    if not configs:
        print("data/sources.json に仕入先がありません。")
        return

    status_mark = {"verified": "✅ 確認済み", "unverified": "🔶 未検証", "disabled": "⏸ 停止中"}
    print("設定済みの仕入先 (data/sources.json):\n")
    for name in sorted(configs):
        cfg = configs[name]
        status = str(cfg.get("status", "unverified")).lower()
        print(f"  {name:14} {status_mark.get(status, status):10} "
              f"{cfg.get('currency', '?'):4} {cfg.get('landed_cost_basis', '?'):4} "
              f"{cfg.get('display_name', '')}")
        print(f"                 {cfg.get('products_json_url', '')}")
    print("\n使い方: python3 scripts/shopify_sales_to_csv.py --source <名前> --probe")


def resolve_source(name: str) -> ConfigSource:
    """設定から ConfigSource を作る。未定義なら分かりやすいエラーで終了する。"""
    try:
        config = get_source_config(name)
    except ValueError as e:
        print(f"❌ data/sources.json の設定に問題があります: {e}")
        sys.exit(1)

    if config is None:
        try:
            known = sorted(load_source_configs())
        except ValueError:
            known = []
        print(f"❌ 仕入先 '{name}' は data/sources.json にありません (停止中の可能性もあります)。")
        if known:
            print(f"   使えるのは: {', '.join(known)}")
        print("   一覧は --list で確認できます。")
        sys.exit(1)

    return ConfigSource(name, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shopify 系仕入先のセール商品 → CSV (data/sources.json 設定ベース)",
    )
    parser.add_argument("--source", help="data/sources.json のキー名 (例: antonioli)")
    parser.add_argument("--list", action="store_true", help="設定済みの仕入先を一覧表示")
    parser.add_argument("--probe", action="store_true",
                        help="取得できるかだけ確認する (CSV は作らない)")
    parser.add_argument("--url", help="products.json の URL を一時的に上書きする")
    parser.add_argument("--max-pages", type=int, default=40, help="最大ページ数 (既定 40)")
    parser.add_argument("--limit", type=int, help="処理件数の上限 (デバッグ用)")
    parser.add_argument("--delay", type=float, help="ページ取得の間隔 (秒)。既定は設定値")
    parser.add_argument("--output", help="出力ファイルのパス")
    parser.add_argument("--test", action="store_true",
                        help="モックデータで CSV 生成だけ確認する (ネットワーク不要)")
    args = parser.parse_args(argv)

    if args.list:
        print_source_list()
        return 0

    if not args.source:
        parser.error("--source を指定してください (一覧は --list)")

    source = resolve_source(args.source)
    if source.status == "unverified" and not args.test:
        print(f"🔶 '{source.name}' は未検証の設定です。関税・送料・URL が仮の値の可能性があります。")
        print("   data/sources.json の notes を読み、ブラウザで条件を確認してください。\n")

    if args.probe:
        return probe_source(source, url=args.url)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.test:
        print(f"🧪 テストモード: モックデータ {len(mock_products())} 件で CSV を生成します")
        products = mock_products()
    else:
        products = fetch_all_products(
            args.url or source.products_json_url,
            max_pages=args.max_pages,
            delay_sec=args.delay if args.delay is not None else source.request_delay_sec,
        )
        if not products:
            print("❌ 商品データを取得できませんでした。")
            print(f"   python3 scripts/shopify_sales_to_csv.py --source {source.name} --probe")
            print("   で原因を確認してください。")
            return 1

    if args.limit:
        products = products[: args.limit]

    rows = []
    for p in products:
        parsed = parse_shopify_product(p, source)
        if parsed:
            rows.append(parsed)
    rows.sort(key=lambda x: x["discount_rate"], reverse=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = Path(args.output) if args.output else (
        OUTPUT_DIR / f"{date_str}_{source.name}_sales_products_sorted.csv"
    )
    save_to_csv(rows, output_path)

    print("\n次のステップ:")
    print(f"   python3 scripts/filter_baseblu_profitable.py --source {source.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
