"""
buyma_brand_lookup.py
---------------------
BUYMAのブランドサジェストAPIを使ってブランドIDを自動取得し、
data/brands.json を更新するスクリプト。

【できること】
  - 利益商品CSVに含まれるブランド名をBUYMAで検索
  - 見つかったブランドIDを data/brands.json に自動追記
  - 見つからないブランドは unregistered リストに追加

【使い方】
  python3 scripts/buyma_brand_lookup.py

必要なもの:
  pip install requests --break-system-packages
"""

import csv
import glob
import json
import os
import time
import unicodedata
import requests

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR  = os.path.join(BASE_DIR, "outputs", "reports")
BRANDS_PATH = os.path.join(BASE_DIR, "data", "brands.json")

BUYMA_SUGGEST_URL = "https://www.buyma.com/rorapi/suggest/brands.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.buyma.com/my/sell/new",
}


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    result = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", result)


def load_brands():
    if os.path.exists(BRANDS_PATH):
        with open(BRANDS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"brands": {}, "unregistered": [], "auto_lookup_enabled": True}


def save_brands(data):
    os.makedirs(os.path.dirname(BRANDS_PATH), exist_ok=True)
    with open(BRANDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def lookup_brand(brand_name):
    """BUYMAのサジェストAPIでブランドを検索する"""
    try:
        resp = requests.get(
            BUYMA_SUGGEST_URL,
            params={"keyword": brand_name},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()

        if not results:
            return None

        # 完全一致を優先、なければ最初の結果を使用
        safe_name = normalize_text(brand_name).upper()
        for item in results:
            item_name = normalize_text(item.get("text", "")).upper()
            if item_name == safe_name:
                return item

        # 部分一致: ブランド名が含まれていれば採用
        for item in results:
            item_name = normalize_text(item.get("text", "")).upper()
            if safe_name in item_name or item_name in safe_name:
                return item

        return None

    except Exception as e:
        print(f"  ⚠️  API検索エラー ({brand_name}): {e}")
        return None


def get_vendors_from_csv():
    """利益商品CSVからブランド名一覧を取得"""
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_profitable_products.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("❌ 利益商品CSVが見つかりません")
        return set()

    vendors = set()
    with open(files[0], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            vendor = row.get("vendor", "").strip()
            if vendor:
                vendors.add(vendor)
    return vendors


def main():
    print("🏷️  BUYMAブランドID自動取得")
    print("=" * 50)

    brands_data = load_brands()
    known = brands_data.get("brands", {})
    unregistered = set(brands_data.get("unregistered", []))

    vendors = get_vendors_from_csv()
    if not vendors:
        return

    print(f"📦 CSVから {len(vendors)} ブランドを検出\n")

    new_found = 0
    new_unreg = 0

    for vendor in sorted(vendors):
        safe_vendor = normalize_text(vendor)

        # 既知ならスキップ
        if safe_vendor in known:
            print(f"  ✅ {safe_vendor} → ID={known[safe_vendor]['brand_id']} (既知)")
            continue
        if safe_vendor in unregistered:
            print(f"  ⏭️  {safe_vendor} → 未登録 (既知)")
            continue

        # APIで検索
        print(f"  🔍 {safe_vendor} を検索中...", end=" ")
        result = lookup_brand(safe_vendor)
        time.sleep(0.5)  # レート制限対策

        if result:
            brand_id = result.get("brand_id", -1)
            phonetic = result.get("phonetic", "")
            text = result.get("text", safe_vendor)
            known[safe_vendor] = {
                "brand_id": brand_id,
                "phonetic": phonetic,
            }
            print(f"→ ID={brand_id} ({text}, {phonetic})")
            new_found += 1
        else:
            unregistered.add(safe_vendor)
            print(f"→ BUYMA未登録")
            new_unreg += 1

    # 保存
    brands_data["brands"] = known
    brands_data["unregistered"] = sorted(list(unregistered))
    save_brands(brands_data)

    print(f"\n{'='*50}")
    print(f"✅ 完了！ 新規発見: {new_found}件  未登録: {new_unreg}件")
    print(f"📄 保存先: {BRANDS_PATH}")
    print(f"   登録済み: {len(known)}件  未登録: {len(unregistered)}件")


if __name__ == "__main__":
    main()
