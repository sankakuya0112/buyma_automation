"""
filter_baseblu_profitable.py
------------------------------
BaseBluのセール商品CSVから利益計算を行い、BUYMA 出品候補を抽出する。

Phase 2a で市場連動価格決定ロジック (app.core.pricing.decide_final_price) を
統合。市場データ (outputs/reports/*_market_prices.json) があれば相場連動で
final_price_jpy を決め、原価割れになる商品は skip_reason を付けてスキップ
フラグを立てる。

使い方:
    # 通常 (市場データなし、従来どおり 25% 利益率売価)
    python3 scripts/filter_baseblu_profitable.py

    # 市場データ併用 (fetch_buyma_market_prices.py で取得済みの JSON を渡す)
    python3 scripts/filter_baseblu_profitable.py --market outputs/reports/2026-04-22_market_prices.json

出力 CSV カラム (Phase 2a で追加):
    market_median_jpy / market_sample_count
    breakeven_price_jpy / floor_profit_jpy
    final_price_jpy / skip_reason / action
    expected_profit_jpy / expected_margin_pct
"""

import argparse
import csv
import json
import os
import sys
import glob
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import (
    PricingParams, calculate_pricing,
    MarketStats, decide_final_price,
)
from app.core.external_benchmark import (
    ExternalBenchmark, evaluate_external_benchmark,
    load_benchmarks, make_product_key,
)

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")
MIN_PROFIT_JPY = 5000          # 予備フィルタ: 従来の最低利益 (profit_jpy) で予備除外


def get_latest_sales_csv():
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_sales_products_sorted.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def keyword_from_title(title: str) -> str:
    """市場データの lookup キー (scraper と同一ロジック)。"""
    import re
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"[\(\)\[\]\{\},.;:'\"!?/\\\-_]+", " ", text)
    stop = {"the", "a", "an", "with", "and", "of", "in", "for", "to"}
    words = [w for w in text.split() if w and w not in stop]
    return " ".join(words[:3])


def keyword_from_sku(sku: str) -> str:
    import re
    if not sku:
        return ""
    return re.sub(r"[_\-/]+", " ", sku).strip()


def load_market_data(path):
    """fetch_buyma_market_prices.py が出力した JSON を読込。"""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_market_stats(market_data, vendor, title, sku="") -> MarketStats:
    """SKU キー優先、なければ title キーで fetch 結果を引く。"""
    if not market_data:
        return MarketStats()
    v = (vendor or "").strip()
    sku_kw = keyword_from_sku(sku)
    keys_to_try = []
    if sku_kw:
        keys_to_try.append(f"{v}|{sku_kw}")
    keys_to_try.append(f"{v}|{keyword_from_title(title)}")
    entry = None
    for k in keys_to_try:
        if k in market_data:
            entry = market_data[k]
            break
    if not entry:
        return MarketStats()
    return MarketStats(
        sample_count=entry.get("sample_count", 0),
        median_jpy=entry.get("median_jpy"),
        min_jpy=entry.get("min_jpy"),
        max_jpy=entry.get("max_jpy"),
    )


def main():
    parser = argparse.ArgumentParser(description="baseblu 利益計算 + 市場連動価格フィルタ")
    parser.add_argument("--market", help="市場価格 JSON (fetch_buyma_market_prices.py の出力)")
    parser.add_argument("--include-skipped", action="store_true",
                        help="skip_reason 付きの商品も profitable CSV に含める (監査用)")
    parser.add_argument("--external-benchmark",
                        help="Farfetch JP 等の外部ベンチマーク JSON (fetch_farfetch_benchmarks.py の出力)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    input_path = get_latest_sales_csv()
    if not input_path:
        print("❌ 入力CSVが見つかりません。先に baseblu_sales_to_csv.py を実行してください。")
        return
    print(f"📂 入力ファイル: {os.path.basename(input_path)}")

    market_data = load_market_data(args.market)
    if market_data:
        print(f"📊 市場データ: {len(market_data)} 件ロード ({os.path.basename(args.market)})")
    else:
        print("📊 市場データ: なし (全商品を target_price 採用)")

    benchmarks: dict = {}
    if args.external_benchmark:
        benchmarks = load_benchmarks(args.external_benchmark)
        if benchmarks:
            print(f"🌐 外部ベンチマーク: {len(benchmarks)} 件ロード ({os.path.basename(args.external_benchmark)})")
        else:
            print(f"🌐 外部ベンチマーク: ファイルが空または存在しない ({args.external_benchmark})")

    rows_out = []
    skipped_count = {"total": 0, "unavailable": 0, "parse_error": 0,
                     "low_base_profit": 0, "skip_reason": 0}

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("available", "").strip().lower() not in ("true", "1", "yes"):
                skipped_count["unavailable"] += 1
                skipped_count["total"] += 1
                continue

            try:
                sale_price_eur = float(row["sale_price"])
            except (ValueError, KeyError):
                skipped_count["parse_error"] += 1
                skipped_count["total"] += 1
                continue

            product_type = row.get("product_type", "")
            vendor = row.get("vendor", "")
            title = row.get("title", "")

            params = PricingParams(
                source_price=sale_price_eur,
                currency="EUR",
                category=product_type,
                landed_cost_basis="DDU",  # Baseblu は DDU
            )
            result = calculate_pricing(params)

            # 予備フィルタ: 25% 利益率でも 5000 円に届かない商品は除外
            if result.profit_jpy < MIN_PROFIT_JPY:
                skipped_count["low_base_profit"] += 1
                skipped_count["total"] += 1
                continue

            market = get_market_stats(market_data, vendor, title, sku=row.get("sku", ""))
            decision = decide_final_price(result, market=market, category=product_type)

            # 外部ベンチマーク評価 (Phase 2b)
            #   BUYMA 内独占判定の商品 (no_market_data / low_competition / fake_market) は
            #   Farfetch 等の外部 EC で安く出ていれば SKIP/warn に変える。
            external_action = "pass"
            external_reason = "no_external_data"
            external_min = ""
            external_url = ""
            ext_target_reasons = ("no_market_data", "low_competition", "fake_market")
            if (
                benchmarks
                and decision.action == "list"
                and decision.reason in ext_target_reasons
                and decision.final_price_jpy
            ):
                key = make_product_key(vendor, title, row.get("sku", ""))
                bench = benchmarks.get(key)
                external_action, external_reason = evaluate_external_benchmark(
                    decision.final_price_jpy, bench,
                )
                if bench:
                    external_min = bench.min_price_jpy or ""
                    external_url = bench.matched_url or ""
                if external_action == "skip":
                    # 外部のほうが安い → 出品しても売れない見込み
                    decision.action = "skip"
                    decision.reason = "external_cheaper"
                    decision.final_price_jpy = None
                elif external_action == "warn":
                    # 出品はするが優位性薄を decision_reason に追記
                    decision.reason = f"{decision.reason}|external_close"

            if decision.action == "skip" and not args.include_skipped:
                skipped_count["skip_reason"] += 1
                skipped_count["total"] += 1
                continue

            out_row = {
                "title": title,
                "vendor": vendor,
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
                "selling_price_jpy": result.selling_price_jpy,   # target price (25%)
                "buyma_commission_jpy": round(result.buyma_commission_jpy),
                "payment_commission_jpy": round(result.payment_commission_jpy),
                "profit_jpy": round(result.profit_jpy),          # target での利益
                "margin_pct": result.margin_pct,
                # Phase 2a 追加カラム
                "market_median_jpy": decision.market_median_jpy or "",
                "market_sample_count": decision.market_sample_count,
                "breakeven_price_jpy": decision.breakeven_price_jpy,
                "floor_profit_jpy": decision.floor_profit_jpy,
                "final_price_jpy": decision.final_price_jpy or "",
                "action": decision.action,
                "skip_reason": "" if decision.action == "list" else decision.reason,
                "decision_reason": decision.reason,
                "expected_profit_jpy": decision.expected_profit_jpy,
                "expected_margin_pct": decision.expected_margin_pct,
                "competition_level": decision.competition_level,
                # Phase 2b 追加
                "landed_cost_basis": result.landed_cost_basis,
                "external_action": external_action,
                "external_reason": external_reason,
                "external_min_jpy": external_min,
                "external_url": external_url,
            }
            rows_out.append(out_row)
            skipped_count["total"] += 1

    # listing 可能なもの (action=list) を利益順にソート
    rows_out.sort(
        key=lambda x: (0 if x.get("action") == "list" else 1,
                       -int(x.get("expected_profit_jpy") or x.get("profit_jpy") or 0)),
    )

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
        # Phase 2a
        "market_median_jpy", "market_sample_count",
        "breakeven_price_jpy", "floor_profit_jpy",
        "final_price_jpy", "action", "skip_reason", "decision_reason",
        "expected_profit_jpy", "expected_margin_pct", "competition_level",
        # Phase 2b
        "landed_cost_basis",
        "external_action", "external_reason", "external_min_jpy", "external_url",
        # 末尾
        "description_en", "image_url", "sub_images", "product_url",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_out)

    listable = sum(1 for r in rows_out if r.get("action") == "list")
    skip = sum(1 for r in rows_out if r.get("action") == "skip")
    print(f"\n✅ 利益計算完了！")
    print(f"   出品可 (action=list)      : {listable} 件")
    print(f"   スキップ (action=skip)    : {skip} 件 (CSV 内訳参照用に残存)" if args.include_skipped else "")
    print(f"   除外 (利益不足)           : {skipped_count['low_base_profit']} 件")
    print(f"   除外 (在庫なし)           : {skipped_count['unavailable']} 件")
    print(f"   除外 (市場連動でスキップ) : {skipped_count['skip_reason']} 件")
    print(f"   保存先                    : {output_path}")

    if rows_out:
        listed = [r for r in rows_out if r.get("action") == "list"]
        if listed:
            top = listed[0]
            fp = int(top.get("final_price_jpy") or top.get("selling_price_jpy") or 0)
            ep = int(top.get("expected_profit_jpy") or top.get("profit_jpy") or 0)
            em = float(top.get("expected_margin_pct") or top.get("margin_pct") or 0)
            print(f"\n🏆 最高期待利益商品:")
            print(f"   {top['title']} ({top['vendor']})")
            print(f"   仕入: EUR {top['sale_price_eur']:.0f} → 原価: ¥{top['total_cost_jpy']:,}")
            print(f"   最終売価: ¥{fp:,}  期待利益: ¥{ep:,} ({em:.1f}%)")


if __name__ == "__main__":
    main()
