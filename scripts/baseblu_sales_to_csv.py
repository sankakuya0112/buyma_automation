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

# HTML ページ取得用ヘッダー。baseblu は Accept に従って content-type を切り替える
# ため、JSON 用の HEADERS をそのまま使うと HTML URL でも JSON が返ってしまう。
HTML_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": HEADERS["Accept-Language"],
    "Referer": HEADERS["Referer"],
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


def fetch_product_html(handle):
    """個別商品の HTML ページを取得する。JSON API に含まれない色ラベル等を
    抽出するために使う。失敗時は空文字列。

    HEADERS は Accept=application/json なので流用すると HTML URL でも JSON が
    返る。HTML_HEADERS (Accept=text/html) を使って明示的に HTML を要求する。
    """
    if not handle:
        return ""
    url = PRODUCT_BASE_URL + handle
    try:
        resp = requests.get(url, headers=HTML_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text or ""
    except Exception:
        return ""


def _extract_color_from_html(html: str) -> str:
    """baseblu の商品ページ HTML から色ラベルを抽出する。

    ALAÏA ブラウスのような商品では右サイドバーに 'GREEN' のようなテキストが
    表示される。Shopify テーマの実装パターンは複数あるため、代表的な構造を順に試す。
    """
    if not html:
        return ""

    # パターン0（baseblu 固有・最優先）: product-page__colors__info__title(--desktop)?
    m = re.search(
        r'<div[^>]*class="[^"]*product-page__colors__info__title(?:--desktop)?[^"]*"[^>]*>\s*([A-Za-z][A-Za-z \-/]+?)\s*</div>',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().title()

    # パターン1: data-color / data-color-name 属性
    for pat in [
        r'data-color(?:-name)?\s*=\s*["\']([A-Za-z][A-Za-z \-/]+)["\']',
        r'data-swatch(?:-color)?\s*=\s*["\']([A-Za-z][A-Za-z \-/]+)["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # パターン2: <span class="...color...">NAME</span> / <div class="swatch-label">NAME</div>
    for pat in [
        r'<span[^>]*class="[^"]*(?:color-name|product-color|swatch-label)[^"]*"[^>]*>\s*([A-Z][A-Za-z \-/]+)\s*</span>',
        r'<div[^>]*class="[^"]*(?:color-name|product-color|swatch-label)[^"]*"[^>]*>\s*([A-Z][A-Za-z \-/]+)\s*</div>',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # パターン3: 関連商品ラベルやアクセシビリティ属性に色が載っているケース
    # 例: <a ... aria-label="GREEN"> / <img alt="Green">
    for pat in [
        r'aria-label="([A-Z]{3,15})"[^>]*(?:product|color|swatch)',
        r'(?:product|color|swatch)[^>]*aria-label="([A-Z]{3,15})"',
    ]:
        m = re.search(pat, html)
        if m:
            return m.group(1).strip().title()

    # パターン4: Shopify の productJson / 埋め込み JSON に "color" キーがあるケース
    m = re.search(r'"color"\s*:\s*"([A-Za-z][A-Za-z \-/]+)"', html)
    if m:
        return m.group(1).strip()

    # パターン5: 右サイドバー系のシンプルな色ラベル。典型例:
    #   <span class="color">GREEN</span> や <div class="variant-color">Green</div>
    m = re.search(
        r'<(?:span|div|p)[^>]*>\s*([A-Z]{3,15})\s*</(?:span|div|p)>\s*(?:</a>|<img[^>]*variant)',
        html,
    )
    if m:
        token = m.group(1).strip()
        # ALL_UPPERCASE の単語のうち、色キーワードに合致する場合だけ採用
        for kw in _COLOR_KEYWORDS:
            if kw.upper() == token or kw.upper() in token:
                return token.title()

    return ""


def _extract_sku_from_description(description: str) -> str:
    """body_html/description_en に "Sku: XXXXX" と明記されている場合に抽出する。

    baseblu は商品説明に "Sku: AA9C0962T666A_643" のように表示するため、
    これが最も正確な製品 SKU。variant SKU よりこちらを優先する。
    """
    if not description:
        return ""
    m = re.search(r"Sku\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9_\-]*)", description, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _extract_season(description: str) -> str:
    """商品説明テキストから "Season: AW25" のようなシーズン情報を抽出する。

    baseblu の body_html から得た description_en には
      Sku: AA9C0962T666A_643
      Season: AW25
      Fit: Regular
    のような情報が含まれることがある。
    """
    if not description:
        return ""
    m = re.search(r"Season\s*[:：]\s*([A-Z]{1,4}\d{2,4})", description, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""


def _extract_sku_from_variant(variant_sku: str, option1_value: str) -> str:
    """variant の SKU からサイズ suffix (_40, _XL 等) を剥がして製品レベルの SKU を返す。

    Shopify では各 variant に別 SKU が割り当てられるため、"AA9C0962T666A_643_40" の
    ように variant の option1 (サイズ) が末尾に付いていることが多い。
    BUYMA の品番欄には "AA9C0962T666A_643" のような製品共通 SKU を入れたい。
    """
    if not variant_sku:
        return ""
    opt = (option1_value or "").strip()
    if not opt:
        return variant_sku
    # "_{option1}" が末尾にあれば剥がす
    suffix = "_" + opt
    if variant_sku.endswith(suffix):
        return variant_sku[: -len(suffix)]
    # case-insensitive 比較（例: variant の sku が大文字、option1 が小文字など）
    if variant_sku.lower().endswith(suffix.lower()):
        return variant_sku[: -len(suffix)]
    return variant_sku


# 色キーワード（body_html / タイトル / tags 文字列中の検出用）。
# より具体的なもの (multi-word) を先に並べて誤一致を避ける。
_COLOR_KEYWORDS = [
    "off white", "off-white",
    "navy blue", "royal blue", "sky blue", "light blue", "dark blue",
    "wine red", "light pink", "dark green", "forest green",
    "black", "white", "red", "pink", "blue", "green", "yellow",
    "orange", "purple", "violet", "gray", "grey", "brown", "beige",
    "cream", "gold", "silver", "khaki", "burgundy", "bordeaux",
    "navy", "ivory", "camel", "mustard", "turquoise",
]


def _extract_color(product: dict) -> str:
    """Shopify product から色情報を抽出する。複数ソースを順番に試す。

    優先順位:
      1. options[name="Color"/"Colour"/"Colore"]
      2. variants[].option2 (Shopify 慣例)
      3. tags (例: "color:green" / "Green")
      4. body_html の "Color: XXX" パターン
      5. title 中の色キーワード
    """
    # 1) options
    for option in product.get("options", []) or []:
        name = (option.get("name") or "").strip().lower()
        if name in ("color", "colour", "colore"):
            values = option.get("values") or []
            out = ", ".join(v for v in values if v)
            if out:
                return out

    # 2) variants.option2
    seen = set()
    colors = []
    for v in product.get("variants", []) or []:
        c = (v.get("option2") or "").strip()
        if c and c not in seen:
            seen.add(c)
            colors.append(c)
    if colors:
        return ", ".join(colors)

    # 3) tags - "color:green" or just "green"
    tags = product.get("tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    for tag in tags:
        tl = tag.lower().strip()
        if tl.startswith("color:") or tl.startswith("colour:"):
            return tag.split(":", 1)[1].strip()
        for kw in _COLOR_KEYWORDS:
            if tl == kw:
                return tag.strip()

    # 4) body_html - "Color: XXX" pattern
    body = product.get("body_html", "") or ""
    if body:
        m = re.search(r"Colou?r\s*[:：]\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)", body, re.IGNORECASE)
        if m:
            return m.group(1).strip().title()

    # 5) title - scan for color keywords
    title = (product.get("title") or "").lower()
    for kw in _COLOR_KEYWORDS:
        if kw in title:
            return kw.title()

    return ""


def _extract_sizes_from_html(html: str) -> str:
    """baseblu の HTML から <div id="wrapper-option1-XS">... を抽出。
    JSON の variants にサイズ情報がない場合のフォールバック。
    """
    if not html:
        return ""
    # id="wrapper-option1-<SIZE>" パターン
    matches = re.findall(
        r'id=["\']wrapper-option1-([A-Za-z0-9][A-Za-z0-9 \./\-]{0,10})["\']',
        html,
    )
    seen = set()
    out = []
    for s in matches:
        key = s.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return ", ".join(out)


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
    # variant SKU からサイズ suffix を剥がして製品レベル SKU にする
    sku = _extract_sku_from_variant(variant.get("sku", ""), variant.get("option1", ""))

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
                    dv = detail_variants[0]
                    sku = _extract_sku_from_variant(dv.get("sku", ""), dv.get("option1", ""))
        time.sleep(0.3)  # レート制限対策

    # 色・サイズ・シーズン抽出（BUYMA 出品フォームに流し込むため）
    color = _extract_color(product)
    sizes = _extract_sizes(variants, only_available=False)
    available_sizes = _extract_sizes(variants, only_available=True)
    season = _extract_season(description_en)

    # JSON API で色またはサイズが取れなかった場合、商品ページ HTML から追加取得
    if fetch_details and handle and (not color or not sizes):
        html = fetch_product_html(handle)
        if not color:
            color = _extract_color_from_html(html)
        if not sizes:
            sizes = _extract_sizes_from_html(html)
            if sizes and not available_sizes:
                available_sizes = sizes  # HTML 由来の在庫は不明のため同一扱い
        time.sleep(0.3)  # レート制限対策

    # description_en に "Sku: XXX" が明記されていれば、それを優先（variant SKU より正確）
    desc_sku = _extract_sku_from_description(description_en)
    if desc_sku:
        sku = desc_sku

    return {
        "title": title,
        "vendor": vendor,
        "product_type": product_type,
        "sku": sku,
        "color": color,
        "sizes": sizes,
        "available_sizes": available_sizes,
        "season": season,
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
        "color", "sizes", "available_sizes", "season",
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
