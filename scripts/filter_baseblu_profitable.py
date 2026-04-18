"""
filter_baseblu_profitable.py
------------------------------
BaseBluのセール商品CSVから利益計算を行い、
利益5,000円以上の商品だけを抽出してCSVに保存するスクリプト。

計算には統一された pricing モジュール (app.core.pricing) を使用。
  - EUR 通貨、VAT還付 16.7%、カテゴリ別関税率、重量ベース送料
  - BUYMA 手数料 5.8% + 決済手数料 3%
  - フィルタ: available=True かつ 推定利益5,000円以上

使い方:
    python3 scripts/filter_baseblu_profitable.py
"""

import csv
import os
import sys
import glob
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加して app モジュールをインポート可能にする
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import PricingParams, calculate_pricing

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")
MIN_PROFIT_JPY = 5000          # フィルタ: 最低利益（円）


def get_latest_csv():
    """outputs/reports/ から最新の sales CSV を取得する"""
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_sales_products_sorted.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    return files[0]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 入力ファイル
    input_path = get_latest_csv()
    if not input_path:
        print("❌ 入力CSVが見つかりません。先に baseblu_sales_to_csv.py を実行してください。")
        return
    print(f"📂 入力ファイル: {os.path.basename(input_path)}")

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
                sale_price_eur = float(row["sale_price"])
            except (ValueError, KeyError):
                skipped += 1
                continue

            product_type = row.get("product_type", "")

            # 統一 pricing モジュールで利益計算
            params = PricingParams(
                source_price=sale_price_eur,
                currency="EUR",
                category=product_type,
            )
            result = calculate_pricing(params)

            # 利益フィルタ
            if result.profit_jpy < MIN_PROFIT_JPY:
                skipped += 1
                continue

            # 出力行を組み立て
            out_row = {
                "title": row.get("title", ""),
                "vendor": row.get("vendor", ""),
                "product_type": product_type,
                "sku": row.get("sku", ""),
                "color": row.get("color", ""),
                "sizes": row.get("sizes", ""),
                "available_sizes": row.get("available_sizes", ""),
                "season": row.get("season", ""),
                "sale_price_eur": sale_price_eur,
                "original_price_eur": row.get("original_price", ""),
                "discount_rate": row.get("discount_rate", ""),
                "description_en": row.get("description_en", ""),
                "image_url": row.get("image_url", ""),
                "sub_images": row.get("sub_images", ""),
                "product_url": row.get("product_url", ""),
                "exchange_rate": result.exchange_rate,
                "source_price_jpy": round(result.source_price_jpy),
                "vat_refund_jpy": round(result.vat_refund_jpy),
                "shipping_jpy": round(result.shipping_jpy),
                "customs_jpy": round(result.customs_jpy),
                "duty_rate": result.duty_rate,
                "consumption_tax_jpy": round(result.consumption_tax_jpy),
                "total_cost_jpy": round(result.total_cost_jpy),
                "selling_price_jpy": result.selling_price_jpy,
                "buyma_commission_jpy": round(result.buyma_commission_jpy),
                "payment_commission_jpy": round(result.payment_commission_jpy),
                "profit_jpy": round(result.profit_jpy),
                "margin_pct": result.margin_pct,
            }
            rows_out.append(out_row)

    # 利益の高い順にソート
    rows_out.sort(key=lambda x: x["profit_jpy"], reverse=True)

    # CSV保存
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}_baseblu_profitable_products.csv")

    fieldnames = [
        "title", "vendor", "product_type", "sku",
        "color", "sizes", "available_sizes", "season",
        "sale_price_eur", "original_price_eur", "discount_rate",
        "exchange_rate", "source_price_jpy", "vat_refund_jpy",
        "shipping_jpy", "customs_jpy", "duty_rate",
        "consumption_tax_jpy", "total_cost_jpy",
        "selling_price_jpy", "buyma_commission_jpy",
        "payment_commission_jpy", "profit_jpy", "margin_pct",
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
        print(f"   仕入れ: EUR {top['sale_price_eur']:.0f} → 総コスト: ¥{top['total_cost_jpy']:,}")
        print(f"   出品価格: ¥{top['selling_price_jpy']:,}  純利益: ¥{top['profit_jpy']:,} (利益率: {top['margin_pct']:.1f}%)")


if __name__ == "__main__":
    main()
