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
from app.core.sources import get_source
from app.core.opportunity import (
    DemandSignals, estimate_sale_probability, opportunity_score,
    price_edge_ratio, count_sizes,
)

# ========== 設定 ==========
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "reports")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MIN_PROFIT_JPY = 5000          # 予備フィルタ: 従来の最低利益 (profit_jpy) で予備除外


def load_unregistered_brands(path=None) -> set[str]:
    """brands.json の unregistered リスト (BUYMA に存在しないブランド) を返す。

    これらのブランドは buyma_auto_listing.py が出品時に必ず brand_not_found
    でスキップするため、filter 段階で除外して出品枠の浪費を防ぐ
    (2026-06-10 実走で候補 16 件中 5 件が AFTERCOAT = 必スキップだった)。
    """
    path = path or os.path.join(DATA_DIR, "brands.json")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {str(b).strip().upper() for b in data.get("unregistered", []) if str(b).strip()}
    except Exception:
        return set()


def is_brand_unregistered(vendor: str, unregistered: set[str]) -> bool:
    """vendor が BUYMA 未登録ブランドリストに載っているか (大文字小文字無視)。"""
    if not vendor or not unregistered:
        return False
    return vendor.strip().upper() in unregistered


def get_latest_sales_csv(source="baseblu"):
    source = (source or "baseblu").strip().lower()
    pattern = os.path.join(OUTPUT_DIR, f"*_{source}_sales_products_sorted.csv")
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


def get_market_stats(market_data, vendor, title, sku="", source_name="") -> MarketStats:
    """市場データを引く。BasebluはSKU優先、Italistはタイトル優先。"""
    if not market_data:
        return MarketStats()
    v = (vendor or "").strip()
    sku_kw = keyword_from_sku(sku)
    keys_to_try = []
    title_key = f"{v}|{keyword_from_title(title)}"
    sku_key = f"{v}|{sku_kw}" if sku_kw else ""
    if (source_name or "").strip().lower() == "italist":
        keys_to_try.append(title_key)
        if sku_key:
            keys_to_try.append(sku_key)
    else:
        if sku_key:
            keys_to_try.append(sku_key)
        keys_to_try.append(title_key)
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
        brand_match_confidence=entry.get("brand_match_confidence", 1.0),
    )


def main():
    parser = argparse.ArgumentParser(description="仕入先 CSV 利益計算 + 市場連動価格フィルタ")
    parser.add_argument("--source", default="baseblu", help="仕入先名 (baseblu / italist など)")
    parser.add_argument("--market", help="市場価格 JSON (fetch_buyma_market_prices.py の出力)")
    parser.add_argument("--include-skipped", action="store_true",
                        help="skip_reason 付きの商品も profitable CSV に含める (監査用)")
    parser.add_argument("--external-benchmark",
                        help="Farfetch JP 等の外部ベンチマーク JSON (fetch_farfetch_benchmarks.py の出力)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    source_name = (args.source or "baseblu").strip().lower()
    input_path = get_latest_sales_csv(source_name)
    if not input_path:
        print(f"❌ 入力CSVが見つかりません。先に scripts/{source_name}_sales_to_csv.py を実行してください。")
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

    unregistered_brands = load_unregistered_brands()
    if unregistered_brands:
        print(f"🚫 BUYMA 未登録ブランド (出品不可): {len(unregistered_brands)} 件を除外対象に")

    rows_out = []
    skipped_count = {"total": 0, "unavailable": 0, "parse_error": 0,
                     "low_base_profit": 0, "skip_reason": 0,
                     "brand_unregistered": 0}

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("available", "").strip().lower() not in ("true", "1", "yes"):
                skipped_count["unavailable"] += 1
                skipped_count["total"] += 1
                continue

            try:
                source_price = float(row["sale_price"])
            except (ValueError, KeyError):
                skipped_count["parse_error"] += 1
                skipped_count["total"] += 1
                continue

            product_type = row.get("product_type", "")
            vendor = row.get("vendor", "")
            title = row.get("title", "")

            # BUYMA 未登録ブランドは出品時に必ず brand_not_found でスキップ
            # されるため、ここで除外して出品枠の浪費を防ぐ
            if is_brand_unregistered(vendor, unregistered_brands):
                skipped_count["brand_unregistered"] += 1
                skipped_count["total"] += 1
                continue

            # Phase 2c: source_name 列があれば BaseSource 経由で PricingParams を組み立てる。
            # 旧 CSV (列なし) は get_source() が baseblu (EUR/DDU) に fallback する。
            source = get_source(row.get("source_name", ""))
            params = source.get_pricing_params(
                sale_price=source_price,
                category=product_type,
            )
            result = calculate_pricing(params)

            # 予備フィルタ: 25% 利益率でも 5000 円に届かない商品は除外
            if result.profit_jpy < MIN_PROFIT_JPY:
                skipped_count["low_base_profit"] += 1
                skipped_count["total"] += 1
                continue

            market = get_market_stats(market_data, vendor, title, sku=row.get("sku", ""), source_name=row.get("source_name", ""))
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

            # Phase 2d: 期待値 (EV) スコア = 期待利益 × 成約確率
            try:
                disc = float(row.get("discount_rate") or 0)
            except (ValueError, TypeError):
                disc = 0.0
            signals = DemandSignals(
                market_sample_count=decision.market_sample_count,
                source_total_sizes=count_sizes(row.get("sizes", "")),
                source_available_sizes=count_sizes(row.get("available_sizes", "")),
                discount_rate=disc,
                market_wish_total=int(market_data.get(
                    f"{vendor}|{keyword_from_sku(row.get('sku', '')) or keyword_from_title(title)}",
                    {},
                ).get("wish_total", 0) or 0) if market_data else 0,
            )
            edge = price_edge_ratio(decision.market_median_jpy, decision.final_price_jpy)
            p_sale = estimate_sale_probability(
                decision.competition_level, price_edge_ratio=edge, signals=signals,
            )
            opp = opportunity_score(decision.expected_profit_jpy, p_sale)

            out_row = {
                "title": title,
                "vendor": vendor,
                "product_type": product_type,
                "sku": row.get("sku", ""),
                "color": row.get("color", ""),
                "sizes": row.get("sizes", ""),
                "available_sizes": row.get("available_sizes", ""),
                "season": row.get("season", ""),
                "sale_price_eur": source_price,  # 後方互換カラム名。実通貨は source_name/currency を参照。
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
                "source_name": source.name,
                "currency": source.currency,
                "landed_cost_basis": result.landed_cost_basis,
                "external_action": external_action,
                "external_reason": external_reason,
                "external_min_jpy": external_min,
                "external_url": external_url,
                # Phase 2d 追加: EV スコア
                "price_edge_ratio": round(edge, 4),
                "source_sellthrough": round(signals.sellthrough, 3),
                "sale_probability": round(p_sale, 4),
                "opportunity_score": opp,
            }
            rows_out.append(out_row)
            skipped_count["total"] += 1

    # listing 可能なもの (action=list) を期待値 (opportunity_score) 順にソート。
    # 利益額が大きくても売れにくい商品より、売れやすく十分儲かる商品を優先する。
    rows_out.sort(
        key=lambda x: (0 if x.get("action") == "list" else 1,
                       -int(x.get("opportunity_score") or 0),
                       -int(x.get("expected_profit_jpy") or x.get("profit_jpy") or 0)),
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}_{source_name}_profitable_products.csv")

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
        # Phase 2b/2c
        "source_name", "currency", "landed_cost_basis",
        "external_action", "external_reason", "external_min_jpy", "external_url",
        # Phase 2d
        "price_edge_ratio", "source_sellthrough",
        "sale_probability", "opportunity_score",
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
    print(f"   除外 (BUYMA未登録ブランド): {skipped_count['brand_unregistered']} 件")
    print(f"   保存先                    : {output_path}")

    if rows_out:
        listed = [r for r in rows_out if r.get("action") == "list"]
        if listed:
            top = listed[0]
            fp = int(top.get("final_price_jpy") or top.get("selling_price_jpy") or 0)
            ep = int(top.get("expected_profit_jpy") or top.get("profit_jpy") or 0)
            em = float(top.get("expected_margin_pct") or top.get("margin_pct") or 0)
            ps = float(top.get("sale_probability") or 0)
            opp = int(top.get("opportunity_score") or 0)
            print(f"\n🏆 最高期待値商品 (利益 × 成約確率):")
            print(f"   {top['title']} ({top['vendor']})")
            print(f"   仕入: {top.get('currency') or source_name} {top['sale_price_eur']:.0f} → 原価: ¥{top['total_cost_jpy']:,}")
            print(f"   最終売価: ¥{fp:,}  期待利益: ¥{ep:,} ({em:.1f}%)")
            print(f"   成約確率: {ps*100:.1f}%/月  期待値スコア: ¥{opp:,}")


if __name__ == "__main__":
    main()
