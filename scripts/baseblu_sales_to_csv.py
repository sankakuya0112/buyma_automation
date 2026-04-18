"""
baseblu_sales_to_csv.py
------------------------
BaseBluのセール商品をJSON APIから取得してCSVに保存するスクリプト。

取得先: https://www.baseblu.com/en-us/collections/sales/products.json
出力先: outputs/reports/YYYY-MM-DD_baseblu_sales_products_sorted.csv

v3: 商品説明(body_html)・品番(sku)・全画像URLも取得するように拡張

使い方:
    python3 scripts/baseblu_sales_to_csv.py
"""

import requests
import csv
import os
import re
import time
from datetime import datetime

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")
BASE_URL = "https://www.baseblu.com/en-us/collections/sales/products.json"
PRODUCT_DETAIL_URL = "https://www.baseblu.com/en-us/products/{handle}.json"
PRODUCT_BASE_URL = "https://www.baseblu.com/en-us/products/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.baseblu.com/",
}


def strip_html(html_text):
    """HTMLタグを除去してプレーンテキストにする"""
    if not html_text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', html_text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def fetch_all_products():
    """全ページのセール商品を取得する（ページネーション対応）"""
    all_products = []
    page = 1
    print("BaseBluからセール商品を取得中...")

    while True:
        url = f"{BASE_URL}?page={page}&limit=250"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠️  ページ {page} の取得に失敗: {e}")
            break

        data = resp.json()
        products = data.get("products", [])
        if not products:
            print(f"  → ページ {page}: 商品なし（終了）")
            break

        print(f"  → ページ {page}: {len(products)} 件取得")
        all_products.extend(products)
        page += 1

    return all_products


def fetch_product_detail(handle):
    """個別商品のJSON APIから詳細情報（body_html等）を取得"""
    url = PRODUCT_DETAIL_URL.format(handle=handle)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json().get("product", {})
    except Exception:
        return {}


def _extract_color(product: dict) -> str:
    """Shopify product の options から Color 情報を抽出する。無ければ空文字列。

    例1: options = [{"name": "Size", "values": [...]}, {"name": "Color", "values": ["Black"]}]
         → "Black"
    例2: options に Color がない場合、variants の option2 からカラー値を収集してカンマ区切り
    """
    for option in product.get("options", []) or []:
        name = (option.get("name") or "").strip().lower()
        if name in ("color", "colour", "colore"):
            values = option.get("values") or []
            return ", ".join(v for v in values if v)
    # variants の option2 (Shopify 慣例で option2 が color) をフォールバック
    seen = set()
    colors = []
    for v in product.get("variants", []) or []:
        c = (v.get("option2") or "").strip()
        if c and c not in seen:
            seen.add(c)
            colors.append(c)
    return ", ".join(colors)


def _extract_sizes(variants: list, only_available: bool = False) -> str:
    """variants から Size 情報（option1）を抽出。only_available=True なら在庫ありのみ。"""
    seen = set()
    out = []
    for v in variants or []:
        if only_available and not v.get("available", False):
            continue
        s = (v.get("option1") or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return ", ".join(out)


def parse_product(product, fetch_details=True):
    """Shopify APIの商品データから必要な項目を抽出する"""
    title = product.get("title", "")
    vendor = product.get("vendor", "")
    handle = product.get("handle", "")
    product_url = f"{PRODUCT_BASE_URL}{handle}" if handle else ""
    product_type = product.get("product_type", "")

    # 画像URL（メイン + サブ画像、最大5枚）
    images = product.get("images", [])
    image_urls = [img.get("src", "") for img in images[:5] if img.get("src")]
    image_url = image_urls[0] if image_urls else ""
    sub_images = "|".join(image_urls[1:]) if len(image_urls) > 1 else ""

    # バリアントから価格・SKU情報を取得
    variants = product.get("variants", [])
    if not variants:
        return None

    variant = variants[0]
    available = variant.get("available", False)
    sku = variant.get("sku", "")

    try:
        sale_price = float(variant.get("price", 0))
    except (ValueError, TypeError):
        sale_price = 0.0

    try:
        compare_at_price = float(variant.get("compare_at_price") or 0)
    except (ValueError, TypeError):
        compare_at_price = 0.0

    if compare_at_price > 0 and sale_price < compare_at_price:
        original_price = compare_at_price
        discount_rate = round((1 - sale_price / compare_at_price) * 100, 1)
    else:
        original_price = sale_price
        discount_rate = 0.0

    # 商品説明（body_html）— コレクションAPIには含まれないことがあるので個別取得
    body_html = product.get("body_html", "")
    description_en = strip_html(body_html) if body_html else ""

    # コレクションAPIにbody_htmlがない場合、個別商品APIから取得
    if not description_en and fetch_details and handle:
        detail = fetch_product_detail(handle)
        if detail:
            body_html = detail.get("body_html", "")
            description_en = strip_html(body_html) if body_html else ""
            # SKUも個別APIから取得可能
            if not sku:
                detail_variants = detail.get("variants", [])
                if detail_variants:
                    sku = detail_variants[0].get("sku", "")
        time.sleep(0.3)  # レート制限対策

    # 色・サイズ抽出（BUYMA 出品フォームに流し込むため）
    color = _extract_color(product)
    sizes = _extract_sizes(variants, only_available=False)
    available_sizes = _extract_sizes(variants, only_available=True)

    return {
        "title": title,
        "vendor": vendor,
        "product_type": product_type,
        "sku": sku,
        "color": color,
        "sizes": sizes,
        "available_sizes": available_sizes,
        "sale_price": sale_price,
        "original_price": original_price,
        "discount_rate": discount_rate,
        "available": available,
        "description_en": description_en,
        "image_url": image_url,
        "sub_images": sub_images,
        "product_url": product_url,
    }


def save_to_csv(rows, output_path):
    fieldnames = [
        "title", "vendor", "product_type", "sku",
        "color", "sizes", "available_sizes",
        "sale_price", "original_price", "discount_rate", "available",
        "description_en", "image_url", "sub_images", "product_url"
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ CSVを保存しました: {output_path}")
    print(f"   合計 {len(rows)} 件")
    desc_count = sum(1 for r in rows if r.get("description_en"))
    sku_count = sum(1 for r in rows if r.get("sku"))
    print(f"   商品説明あり: {desc_count}件  品番あり: {sku_count}件")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    products = fetch_all_products()
    if not products:
        print("❌ 商品データを取得できませんでした。")
        return

    print(f"\n📝 商品詳細を取得中（説明文・品番）...")
    rows = []
    for i, p in enumerate(products, 1):
        parsed = parse_product(p, fetch_details=True)
        if parsed:
            rows.append(parsed)
        if i % 20 == 0:
            print(f"  → {i}/{len(products)} 件処理済み")

    rows.sort(key=lambda x: x["discount_rate"], reverse=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}_baseblu_sales_products_sorted.csv")
    save_to_csv(rows, output_path)


if __name__ == "__main__":
    main()
