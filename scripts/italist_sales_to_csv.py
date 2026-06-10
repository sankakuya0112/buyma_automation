"""
italist_sales_to_csv.py
------------------------
Italist のセール商品を Shopify 互換 products.json から取得して CSV に保存する。

出力先: outputs/reports/YYYY-MM-DD_italist_sales_products_sorted.csv
後続:   python3 scripts/filter_baseblu_profitable.py --source italist

⚠️ collection URL は Mac 実走で要確認 (DEFAULT_PRODUCTS_JSON_URL 参照)。
   実際のパスが異なる場合は --url で上書きするか、定数を 1 行修正する。

使い方:
    # 実取得 (Mac で実行)
    python3 scripts/italist_sales_to_csv.py
    python3 scripts/italist_sales_to_csv.py --url "https://.../collections/sale/products.json"

    # モックデータで CSV 生成だけ確認 (サーバー可)
    python3 scripts/italist_sales_to_csv.py --test

設計メモ:
    - 汎用の Shopify JSON 解析 (色/サイズ/SKU/シーズン抽出) は
      baseblu_sales_to_csv.py の関数を再利用する (重複実装しない)
    - source メタ (italist / USD / DDP) は ItalistSource.metadata_dict() から注入
    - チェックアウト/カート/アカウント領域には触れない。公開 collection の
      商品 JSON だけを低頻度 (sleep 付き) で取得する
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# 汎用 Shopify 解析ヘルパー (baseblu スクレイパーから再利用)
from baseblu_sales_to_csv import (  # noqa: E402
    _extract_color,
    _extract_sizes,
    _extract_season,
    _extract_sku_from_description,
    _extract_sku_from_variant,
    strip_html,
)

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")

# 2026-06-10 Mac 実走で確認済みの実 URL (collection handle = women-sale)。
#
# ⚠️ 既知の制約 (Mac 調査結果):
#   - collections/women-sale : 正しい handle だが gating で 1 件しか返らない
#   - collections/sale       : 存在しない handle (空が返る)
#   - /products.json, collections/all : 250件/page で正常ページネーションするが
#     compare_at_price がほぼ全件 null → セール割引情報が取れない
#
# つまり「セール × 割引情報 × 量」を同時に満たす経路が未発見。
# 候補: 商品ページ HTML の旧価格表示 / 別 collection handle (カテゴリ別 sale) /
# 自前の価格履歴差分 (all を定期取得して値下がりを検出)。次回 Mac 調査タスク。
DEFAULT_PRODUCTS_JSON_URL = "https://www.italist.com/collections/women-sale/products.json"

REQUEST_DELAY_SEC = 1.0   # PROCUREMENT_ROADMAP.md: Italist は 5-10 秒/req 推奨だが
                          # collection JSON はページ数が少ないため 1 秒 + 低頻度運用
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def fetch_all_products(products_json_url: str, max_pages: int = 40) -> list[dict]:
    """collection の products.json を全ページ取得する (Shopify ページネーション)。"""
    import requests
    all_products = []
    page = 1
    print(f"Italist からセール商品を取得中... ({products_json_url})")
    while page <= max_pages:
        sep = "&" if "?" in products_json_url else "?"
        url = f"{products_json_url}{sep}page={page}&limit=250"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️ ページ {page} の取得に失敗: {e}")
            if page == 1:
                print("  💡 URL が違う可能性があります。Mac のブラウザで products.json の")
                print("     実パスを確認し、--url で指定してください。")
            break
        products = data.get("products", [])
        if not products:
            print(f"  → ページ {page}: 商品なし（終了）")
            break
        print(f"  → ページ {page}: {len(products)} 件取得")
        all_products.extend(products)
        page += 1
        time.sleep(REQUEST_DELAY_SEC)
    return all_products


def parse_italist_product(product: dict, source_meta: dict) -> dict | None:
    """Shopify 商品 dict から CSV 行を組み立てる。

    baseblu 版 parse_product と同じ出力スキーマ。違いは:
      - 価格は USD (ItalistSource.currency)
      - baseblu 固有の HTML フォールバック (色/DETAILS 抽出) は行わない
        (Italist のページ構造が未調査のため。JSON に無い情報は空のまま)
    """
    variants = product.get("variants", []) or []
    if not variants:
        return None

    # 在庫はバリアント横断 (baseblu と同じ修正済みロジック)
    available = any(v.get("available", False) for v in variants)

    def _price(v):
        try:
            return float(v.get("price", 0))
        except (ValueError, TypeError):
            return float("inf")

    available_variants = [v for v in variants if v.get("available", False)]
    variant = min(available_variants, key=_price) if available_variants else variants[0]

    sku = _extract_sku_from_variant(variant.get("sku", ""), variant.get("option1", ""))

    try:
        sale_price = float(variant.get("price", 0))
    except (ValueError, TypeError):
        sale_price = 0.0
    try:
        compare_at = float(variant.get("compare_at_price") or 0)
    except (ValueError, TypeError):
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
    image_urls = [img.get("src", "") for img in images[:5] if img.get("src")]

    handle = product.get("handle", "")
    product_url = f"https://www.italist.com/products/{handle}" if handle else ""

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
        "product_url": product_url,
        "source_name": source_meta.get("source_name", "italist"),
        "currency": source_meta.get("currency", "USD"),
        "landed_cost_basis": source_meta.get("landed_cost_basis", "DDP"),
    }


def save_to_csv(rows: list[dict], output_path: str) -> None:
    fieldnames = [
        "title", "vendor", "product_type", "sku",
        "color", "sizes", "available_sizes", "season",
        "sale_price", "original_price", "discount_rate", "available",
        "description_en", "image_url", "sub_images", "product_url",
        "source_name", "currency", "landed_cost_basis",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ CSVを保存しました: {output_path}")
    print(f"   合計 {len(rows)} 件 (在庫あり {sum(1 for r in rows if r['available'])} 件)")


def _mock_products() -> list[dict]:
    """--test 用のモック商品 (パイプライン疎通確認、サーバーでも実行可)。"""
    return [
        {
            "title": "Leather Shoulder Bag",
            "vendor": "GUCCI",
            "handle": "gucci-leather-shoulder-bag",
            "product_type": "BAGS",
            "body_html": "<p>Iconic shoulder bag.</p><p>Sku: GG123_456</p>",
            "images": [{"src": "https://cdn.example.com/g1.jpg"}],
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
                {"sku": "KH001_38", "option1": "38", "price": "650.0",
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


def main():
    parser = argparse.ArgumentParser(description="Italist セール商品 → CSV")
    parser.add_argument("--url", default=DEFAULT_PRODUCTS_JSON_URL,
                        help="products.json の URL (要 Mac 確認)")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--limit", type=int, help="処理件数上限 (デバッグ用)")
    parser.add_argument("--test", action="store_true",
                        help="モックデータで CSV 生成のみ (ネットワーク不要)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    from app.core.sources import ItalistSource
    source_meta = ItalistSource().metadata_dict()

    if args.test:
        print("🧪 テストモード: モックデータ 3 件で CSV を生成します")
        products = _mock_products()
    else:
        products = fetch_all_products(args.url, max_pages=args.max_pages)
        if not products:
            print("❌ 商品データを取得できませんでした。")
            return

    if args.limit:
        products = products[: args.limit]

    rows = []
    for p in products:
        parsed = parse_italist_product(p, source_meta)
        if parsed:
            rows.append(parsed)

    rows.sort(key=lambda x: x["discount_rate"], reverse=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}_italist_sales_products_sorted.csv")
    save_to_csv(rows, output_path)
    print("\n次のステップ:")
    print("   python3 scripts/filter_baseblu_profitable.py --source italist")


if __name__ == "__main__":
    main()
