"""
filter_baseblu_profitable.py
------------------------------
BaseBluのセール商品CSVから利益計算を行い、
利益5,000円以上の商品だけを抽出してCSVに保存するスクリプト。

計算式:
  - 為替: exchangerate-api.com（無料・登録不要）
  - 送料: 取得不可時は 3,000円固定
  - 関税: (セール価格円換算 + 送料) × 10%
  - 消費税: (仕入れコスト合計 + 関税) × 10%
  - 想定出品価格: 総コスト ÷ 0.85 (BUYMA手数料10% + 利益マージン確保)
  - フィルタ: available=True かつ 推定利益5,000円以上

使い方:
    python3 scripts/filter_baseblu_profitable.py
"""

import csv
import os
import glob
import requests
from datetime import datetime

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")
SHIPPING_FEE_JPY = 3000        # 送料の固定値（為替取得不可時も同じ）
CUSTOMS_RATE = 0.10            # 関税率 10%
CONSUMPTION_TAX_RATE = 0.10   # 消費税率 10%
BUYMA_MARGIN_RATE = 0.85       # BUYMA手数料10% + 利益10%の逆算
MIN_PROFIT_JPY = 5000          # フィルタ: 最低利益（円）


def get_usd_to_jpy():
    """USD→JPYの為替レートを取得する"""
    try:
        resp = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=10
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["JPY"]
        print(f"  💱 為替レート取得: 1 USD = {rate:.2f} 円")
        return rate
    except Exception as e:
        # デフォルトの保守的なレートを使用
        fallback_rate = 150.0
        print(f"  ⚠️  為替取得失敗 ({e}) → フォールバック: 1 USD = {fallback_rate} 円")
        return fallback_rate


def get_latest_csv():
    """outputs/reports/ から最新の sales CSV を取得する"""
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_sales_products_sorted.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    return files[0]


def calculate_profit(sale_price_usd, usd_to_jpy):
    """利益計算を行い、結果を dict で返す"""
    sale_price_jpy = sale_price_usd * usd_to_jpy
    shipping_jpy = SHIPPING_FEE_JPY
    customs_jpy = (sale_price_jpy + shipping_jpy) * CUSTOMS_RATE
    total_cost_jpy = sale_price_jpy + shipping_jpy + customs_jpy
    consumption_tax_jpy = total_cost_jpy * CONSUMPTION_TAX_RATE
    grand_total_cost_jpy = total_cost_jpy + consumption_tax_jpy
    suggested_price_jpy = grand_total_cost_jpy / BUYMA_MARGIN_RATE
    estimated_profit_jpy = suggested_price_jpy - grand_total_cost_jpy

    return {
        "sale_price_jpy": round(sale_price_jpy),
        "shipping_jpy": shipping_jpy,
        "customs_jpy": round(customs_jpy),
        "consumption_tax_jpy": round(consumption_tax_jpy),
        "total_cost_jpy": round(grand_total_cost_jpy),
        "suggested_buyma_price_jpy": round(suggested_price_jpy, -2),  # 100円単位に丸める
        "estimated_profit_jpy": round(estimated_profit_jpy),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 入力ファイル
    input_path = get_latest_csv()
    if not input_path:
        print("❌ 入力CSVが見つかりません。先に baseblu_sales_to_csv.py を実行してください。")
        return
    print(f"📂 入力ファイル: {os.path.basename(input_path)}")

    # 為替取得
    usd_to_jpy = get_usd_to_jpy()

    # 読み込み＆計算
    rows_out = []
    skipped = 0

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 在庫なしはスキップ
            if row.get("available", "").strip().lower() not in ("true", "1", "yes"):
                skipped += 1
                continue

            try:
                sale_price_usd = float(row["sale_price"])
            except (ValueError, KeyError):
                skipped += 1
                continue

            profit_data = calculate_profit(sale_price_usd, usd_to_jpy)

            # 利益フィルタ
            if profit_data["estimated_profit_jpy"] < MIN_PROFIT_JPY:
                skipped += 1
                continue

            # 出力行を組み立て（v3: 説明文・品番・サブ画像も通す）
            out_row = {
                "title": row.get("title", ""),
                "vendor": row.get("vendor", ""),
                "product_type": row.get("product_type", ""),
                "sku": row.get("sku", ""),
                "sale_price_usd": sale_price_usd,
                "original_price_usd": row.get("original_price", ""),
                "discount_rate": row.get("discount_rate", ""),
                "description_en": row.get("description_en", ""),
                "image_url": row.get("image_url", ""),
                "sub_images": row.get("sub_images", ""),
                "product_url": row.get("product_url", ""),
                **profit_data,
            }
            rows_out.append(out_row)

    # 利益の高い順にソート
    rows_out.sort(key=lambda x: x["estimated_profit_jpy"], reverse=True)

    # CSV保存
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}_baseblu_profitable_products.csv")

    fieldnames = [
        "title", "vendor", "product_type", "sku",
        "sale_price_usd", "original_price_usd", "discount_rate",
        "sale_price_jpy", "shipping_jpy", "customs_jpy",
        "consumption_tax_jpy", "total_cost_jpy",
        "suggested_buyma_price_jpy", "estimated_profit_jpy",
        "description_en", "image_url", "sub_images", "product_url",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\n✅ 利益計算完了！")
    print(f"   候補商品: {len(rows_out)} 件（スキップ: {skipped} 件）")
    print(f"   保存先: {output_path}")

    if rows_out:
        top = rows_out[0]
        print(f"\n🏆 最高利益商品:")
        print(f"   {top['title']} ({top['vendor']})")
        print(f"   仕入れ: ${top['sale_price_usd']:.0f} → 総コスト: ¥{top['total_cost_jpy']:,}")
        print(f"   出品価格: ¥{top['suggested_buyma_price_jpy']:,}  推定利益: ¥{top['estimated_profit_jpy']:,}")


if __name__ == "__main__":
    main()
