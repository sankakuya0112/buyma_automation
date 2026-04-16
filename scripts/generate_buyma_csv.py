"""
scripts/generate_buyma_csv.py
==============================
BaseBlu のスクレイプ済み CSV から BUYMA 取込用 34 列 CSV を生成する。

PROFIT_FIRST フェーズ 1 の成果物：手動アップロードで売上を立てるための
統合パイプライン。app.core.pricing で統一された利益計算と、
app.core.csv_writer で PLUSELECT 準拠の 34 列形式を使う。

前提:
    outputs/reports/YYYY-MM-DD_baseblu_sales_products_sorted.csv が存在
    （scripts/baseblu_sales_to_csv.py で事前に生成）

使い方:
    python3 scripts/generate_buyma_csv.py
    python3 scripts/generate_buyma_csv.py --max-price 30000
    python3 scripts/generate_buyma_csv.py --min-profit 5000 --limit 20
    python3 scripts/generate_buyma_csv.py --currency EUR --target-margin 0.30
"""

from __future__ import annotations

import argparse
import csv
import glob
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.csv_writer import BuymaListingRow, join_images, write_buyma_csv
from app.core.pricing import PricingParams, calculate_pricing

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"

# ---------------------------------------------------------------------------
# BUYMA カテゴリ階層マッピング
# BaseBlu の product_type を BUYMA のカテゴリ文字列に対応付ける。
# ---------------------------------------------------------------------------
BUYMA_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # key: 小文字化した product_type, value: (BUYMA カテゴリパス, テーマ)
    "dress": ("ファッション > ワンピース・チュニック > ドレス", "レディース"),
    "shirt": ("ファッション > トップス > シャツ・ブラウス", "レディース"),
    "blouse": ("ファッション > トップス > シャツ・ブラウス", "レディース"),
    "pants": ("ファッション > パンツ", "レディース"),
    "trousers": ("ファッション > パンツ", "レディース"),
    "skirt": ("ファッション > スカート", "レディース"),
    "jacket": ("ファッション > ジャケット・アウター > ジャケット", "レディース"),
    "coat": ("ファッション > ジャケット・アウター > コート", "レディース"),
    "sweater": ("ファッション > トップス > ニット・セーター", "レディース"),
    "cardigan": ("ファッション > トップス > カーディガン", "レディース"),
    "t-shirt": ("ファッション > トップス > Tシャツ・カットソー", "レディース"),
    "jeans": ("ファッション > パンツ > デニム", "レディース"),
    "bag": ("バッグ > ショルダーバッグ", "レディース"),
    "handbag": ("バッグ > ハンドバッグ", "レディース"),
    "shoulder bag": ("バッグ > ショルダーバッグ", "レディース"),
    "tote bag": ("バッグ > トートバッグ", "レディース"),
    "clutch": ("バッグ > クラッチバッグ", "レディース"),
    "backpack": ("バッグ > バックパック・リュック", "レディース"),
    "wallet": ("財布・小物 > 財布", "レディース"),
    "belt": ("ファッション雑貨 > ベルト", "レディース"),
    "sneakers": ("シューズ > スニーカー", "レディース"),
    "boots": ("シューズ > ブーツ", "レディース"),
    "sandals": ("シューズ > サンダル", "レディース"),
    "shoes": ("シューズ", "レディース"),
    "loafers": ("シューズ > ローファー", "レディース"),
    "pumps": ("シューズ > パンプス", "レディース"),
    "scarf": ("ファッション雑貨 > マフラー・ストール・スカーフ", "レディース"),
    "sunglasses": ("ファッション雑貨 > サングラス", "レディース"),
    "watch": ("ジュエリー・時計 > 時計", "レディース"),
    "jewelry": ("ジュエリー・時計 > ジュエリー", "レディース"),
    "hat": ("ファッション雑貨 > 帽子", "レディース"),
    "cap": ("ファッション雑貨 > 帽子", "レディース"),
}
DEFAULT_BUYMA_CATEGORY = ("ファッション", "レディース")


def resolve_buyma_category(product_type: str) -> tuple[str, str]:
    """BaseBlu の product_type から BUYMA カテゴリ階層・テーマを決める。"""
    if not product_type:
        return DEFAULT_BUYMA_CATEGORY
    key = product_type.lower().strip()
    if key in BUYMA_CATEGORY_MAP:
        return BUYMA_CATEGORY_MAP[key]
    for keyword, value in BUYMA_CATEGORY_MAP.items():
        if keyword in key:
            return value
    return DEFAULT_BUYMA_CATEGORY


# ---------------------------------------------------------------------------
# タイトル・説明文生成（LLM/翻訳API 未導入時のヒューリスティック版）
# ---------------------------------------------------------------------------

def generate_title(brand: str, title: str, sku: str, max_len: int = 60) -> str:
    """BUYMA 向け SEO 最適化タイトル（60 文字以内）。"""
    parts = [p for p in [brand, title, sku, "正規品", "関税送料込"] if p]
    full = " ".join(parts)
    if len(full) <= max_len:
        return full
    for i in range(1, len(parts)):
        candidate = " ".join(parts[:-i])
        if len(candidate) <= max_len:
            return candidate
    return full[: max_len - 3] + "..."


def generate_description(
    brand: str,
    title: str,
    sku: str,
    color: str,
    description_en: str,
) -> str:
    """プロショッパー仕様の商品説明文を生成する。"""
    lines = [f"◆ {brand} / {title}"]
    if sku:
        lines.append(f"◆ 品番: {sku}")
    if color:
        lines.append(f"◆ カラー: {color}")
    lines.append("")

    if description_en:
        lines.append("━━━ 商品詳細 ━━━")
        lines.append(description_en.strip())
        lines.append("")

    lines.extend(
        [
            "━━━ 安心の正規品保証 ━━━",
            "・ヨーロッパ正規取扱店からの直接買付",
            "・100%正規品・新品未使用",
            "・ご希望の方にはレシート画像をご提示可能",
            "",
            "━━━ 配送について ━━━",
            "・買付地: イタリア",
            "・お届けまで: ご注文確定後 10〜21 日程度",
            "・関税/消費税は当方で負担いたします",
            "・追跡番号付きの安心配送",
            "",
            "━━━ ご注意事項 ━━━",
            "・海外買付のため、ご注文後のキャンセルはお受けできません",
            "・ご購入前に在庫確認をお願いいたします",
            "・モニター環境により実物と色味が異なる場合がございます",
        ]
    )
    return "\n".join(lines)


def generate_tags(brand: str, product_type: str) -> str:
    """BUYMA タグ（ハッシュタグ的な検索キーワード）。"""
    tags: list[str] = []
    if brand:
        tags.append(f"#{brand.replace(' ', '')}")
    if product_type:
        tags.append(f"#{product_type}")
    tags.extend(["#正規品", "#海外限定"])
    return " ".join(tags)


def generate_keywords(brand: str, product_type: str) -> str:
    """SEO キーワード（BUYMA 検索流入用）。"""
    parts = [p for p in [brand, product_type, "正規品", "関税送料込"] if p]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 入力 CSV
# ---------------------------------------------------------------------------

def get_latest_sales_csv() -> Path | None:
    """最新の baseblu sales CSV を返す。"""
    pattern = str(OUTPUT_DIR / "*_baseblu_sales_products_sorted.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    return Path(files[0]) if files else None


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BUYMA 取込用 34 列 CSV を生成する",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="入力 CSV パス（省略時は最新ファイル）",
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=None,
        help="販売価格の上限（円）。初回運用は ¥30,000 以下を推奨",
    )
    parser.add_argument(
        "--min-profit",
        type=int,
        default=3000,
        help="最低利益額（円、デフォルト 3000）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="出力件数上限（利益順で上位 N 件）",
    )
    parser.add_argument(
        "--currency",
        type=str,
        default="EUR",
        help="仕入通貨（デフォルト EUR）",
    )
    parser.add_argument(
        "--target-margin",
        type=float,
        default=0.25,
        help="目標利益率（デフォルト 0.25 = 25%%）",
    )
    parser.add_argument(
        "--exchange-rate",
        type=float,
        default=None,
        help="為替レート。省略時はデフォルトマスタを使用",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="出力ファイル名（省略時は日付付きで自動命名）",
    )
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else get_latest_sales_csv()
    if not input_path or not input_path.exists():
        print(
            "❌ 入力 CSV が見つかりません。"
            "先に `python3 scripts/baseblu_sales_to_csv.py` を実行してください。"
        )
        sys.exit(1)
    print(f"📂 入力: {input_path.name}")

    rows_out: list[BuymaListingRow] = []
    skipped = {
        "unavailable": 0,
        "no_price": 0,
        "low_profit": 0,
        "too_expensive": 0,
    }

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 在庫なしスキップ
            available = (row.get("available") or "").strip().lower()
            if available not in ("true", "1", "yes"):
                skipped["unavailable"] += 1
                continue

            source_price = safe_float(row.get("sale_price"))
            if source_price <= 0:
                skipped["no_price"] += 1
                continue

            product_type = (row.get("product_type") or "").strip()
            brand = (row.get("vendor") or "").strip()
            title = (row.get("title") or "").strip()
            sku = (row.get("sku") or "").strip()
            description_en = (row.get("description_en") or "").strip()
            product_url = (row.get("product_url") or "").strip()
            original_price = safe_float(row.get("original_price"))

            # 価格計算
            params = PricingParams(
                source_price=source_price,
                currency=args.currency,
                category=product_type,
                target_margin_pct=args.target_margin,
                exchange_rate=args.exchange_rate,
            )
            result = calculate_pricing(params)

            # フィルタ
            if result.profit_jpy < args.min_profit:
                skipped["low_profit"] += 1
                continue
            if args.max_price and result.selling_price_jpy > args.max_price:
                skipped["too_expensive"] += 1
                continue

            # BUYMA カテゴリ解決
            buyma_category, thema = resolve_buyma_category(product_type)

            # 画像
            image_url = (row.get("image_url") or "").strip()
            sub_images_field = (row.get("sub_images") or "").strip()
            all_images = [image_url]
            if sub_images_field:
                all_images.extend(sub_images_field.split("|"))
            image_joined = join_images(all_images, max_images=5)

            # 参考上代（original_price が存在すれば円換算、なければ販売価格を流用）
            pub_price_jpy = (
                int(original_price * result.exchange_rate)
                if original_price > 0
                else result.selling_price_jpy
            )

            # 内部メモ（購入者には見えない）
            memo = (
                f"仕入れ元: BaseBlu\n"
                f"仕入値: {source_price} {args.currency}\n"
                f"URL: {product_url}\n"
                f"為替: 1 {args.currency} = ¥{result.exchange_rate:.2f}\n"
                f"送料(想定): ¥{int(result.shipping_jpy):,}\n"
                f"関税(想定): ¥{int(result.customs_jpy):,}\n"
                f"消費税(想定): ¥{int(result.consumption_tax_jpy):,}\n"
                f"VAT還付: ¥{int(result.vat_refund_jpy):,}\n"
                f"総原価: ¥{int(result.total_cost_jpy):,}\n"
                f"販売価格: ¥{result.selling_price_jpy:,}\n"
                f"想定利益: ¥{int(result.profit_jpy):,} ({result.margin_pct:.1f}%)"
            )

            buyma_row = BuymaListingRow(
                item_img_folder="",
                item_name=generate_title(brand, title, sku),
                item_brand=brand,
                item_model=sku,
                item_category=buyma_category,
                item_comment=generate_description(
                    brand, title, sku, "", description_en
                ),
                item_size_color="FREE",
                item_deadline="7-14日",
                item_url=product_url,
                item_buyplace="イタリア",
                item_shop="BaseBlu",
                item_sendplace="イタリア",
                color="マルチカラー",
                size="FREE",
                item_season=f"{datetime.now().year}SS",
                item_tag=generate_tags(brand, product_type),
                item_thema=thema,
                item_sell_price=str(result.selling_price_jpy),
                item_pub_price=str(pub_price_jpy),
                item_delivery="DHL",
                item_stock="1",
                item_sku=sku,
                item_duty="バイヤー負担なし",
                item_memo=memo,
                item_price=str(source_price),
                item_currency=args.currency,
                item_no_cur_price=str(source_price),
                item_deli_price=str(int(result.shipping_jpy)),
                item_vatoff=str(int(result.vat_refund_jpy)),
                item_profit=str(int(result.profit_jpy)),
                item_keywords=generate_keywords(brand, product_type),
                item_topic="セール",
                item_image=image_joined,
            )
            rows_out.append(buyma_row)

    # 利益額の降順ソート
    rows_out.sort(key=lambda r: int(r.item_profit or 0), reverse=True)

    if args.limit:
        rows_out = rows_out[: args.limit]

    # 出力
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_name = args.output or f"{date_str}_buyma_listing.csv"
    output_path = OUTPUT_DIR / output_name
    written = write_buyma_csv(rows_out, output_path)

    print(f"\n✅ 生成完了: {output_path}")
    print(f"   出力行数: {written} 件")
    print(
        f"   スキップ: 在庫なし={skipped['unavailable']}, "
        f"価格不正={skipped['no_price']}, "
        f"利益不足={skipped['low_profit']}, "
        f"上限超過={skipped['too_expensive']}"
    )

    if rows_out:
        top = rows_out[0]
        print("\n🏆 トップ利益商品:")
        print(f"   {top.item_brand} / {top.item_name}")
        print(
            f"   販売価格: ¥{int(top.item_sell_price):,}  "
            f"想定利益: ¥{int(top.item_profit):,}"
        )
        print("\n➡️ 次のステップ: BUYMA 管理画面から本 CSV をアップロードしてください。")


if __name__ == "__main__":
    main()
