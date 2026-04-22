"""
sales_report.py
----------------
BUYMA 自動出品の実績から簡易レポートを生成する。

Phase 3-3: 売上分析ダッシュボードの簡易版。UI は作らず CSV ベースで集計を
出力する。どのカテゴリ/ブランド/価格帯が売れているか (出品できているか) を
俯瞰し、運用判断の材料にする。

使い方:
    # 全期間の出品実績サマリ
    python3 scripts/sales_report.py

    # 期間指定
    python3 scripts/sales_report.py --from 2026-04-01 --to 2026-04-30

    # CSV 出力
    python3 scripts/sales_report.py --csv

データソース:
    1. outputs/reports/*_auto_listing_results.csv (出品結果)
    2. outputs/reports/*_baseblu_profitable_products.csv (利益カラム)
    3. data/price_history.json (価格更新履歴)
    4. data/inventory_status.json (在庫状況)

    本来は BUYMA 側の「販売実績」を取得して「売れた/売れていない」まで
    追いたいが、現状は「出品できた」までの集計に留める。実販売は後日
    BUYMA 管理画面スクレイピングで補強する。

レポート内容:
    - 期間別出品件数 (draft / published / error)
    - カテゴリ別・ブランド別の出品数 + 期待利益合計
    - 売価帯別の分布
    - 在庫切れ件数
    - 価格更新履歴
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"
INVENTORY_PATH = PROJECT_ROOT / "data" / "inventory_status.json"
PRICE_HISTORY_PATH = PROJECT_ROOT / "data" / "price_history.json"

RESULTS_GLOB = str(OUTPUT_DIR / "*_auto_listing_results.csv")
PROFITABLE_GLOB = str(OUTPUT_DIR / "*_baseblu_profitable_products.csv")


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d") if s else None


def load_results(from_date=None, to_date=None) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(RESULTS_GLOB)):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                dt_str = r.get("processed_at") or ""
                try:
                    dt = datetime.strptime(dt_str[:10], "%Y-%m-%d")
                except ValueError:
                    dt = None
                if from_date and dt and dt < from_date:
                    continue
                if to_date and dt and dt > to_date:
                    continue
                rows.append(r)
    return rows


def latest_profitable_rows() -> list[dict]:
    files = sorted(glob.glob(PROFITABLE_GLOB))
    if not files:
        return []
    with open(files[-1], encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def fmt_yen(v):
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return "¥?"


def main():
    parser = argparse.ArgumentParser(description="BUYMA 自動出品の実績レポート")
    parser.add_argument("--from", dest="from_date", help="開始日 YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="終了日 YYYY-MM-DD")
    parser.add_argument("--csv", action="store_true", help="CSV 出力")
    args = parser.parse_args()

    from_date = parse_date(args.from_date)
    to_date = parse_date(args.to_date)

    results = load_results(from_date=from_date, to_date=to_date)
    profitable = {r["title"]: r for r in latest_profitable_rows()}
    inventory = load_json(INVENTORY_PATH)
    price_hist = load_json(PRICE_HISTORY_PATH)

    print("=" * 60)
    period = ""
    if from_date or to_date:
        period = f"  [{args.from_date or '..'} 〜 {args.to_date or '..'}]"
    print(f"📊 BUYMA 自動出品レポート{period}")
    print("=" * 60)

    # 1. ステータス別件数
    by_status = Counter(r.get("status", "?") for r in results)
    print(f"\n【出品実績 (n={len(results)})】")
    for status, n in by_status.most_common():
        print(f"  {status:20s} : {n} 件")

    # 2. ブランド別
    by_vendor = Counter(r.get("vendor", "?") for r in results if r.get("status") in ("draft", "published"))
    if by_vendor:
        print(f"\n【ブランド別 出品数】")
        for v, n in by_vendor.most_common(10):
            print(f"  {v[:30]:30s} : {n} 件")

    # 3. 売価帯別
    price_bins = defaultdict(int)
    price_labels = [
        (0, 50000, "¥0-5万"),
        (50000, 100000, "¥5-10万"),
        (100000, 200000, "¥10-20万"),
        (200000, 500000, "¥20-50万"),
        (500000, 10_000_000, "¥50万+"),
    ]
    for r in results:
        if r.get("status") not in ("draft", "published"):
            continue
        try:
            p = int(float(r.get("price") or 0))
        except ValueError:
            continue
        for lo, hi, label in price_labels:
            if lo <= p < hi:
                price_bins[label] += 1
                break
    if price_bins:
        print(f"\n【売価帯別】")
        for _, _, label in price_labels:
            print(f"  {label:10s} : {price_bins.get(label, 0)} 件")

    # 4. カテゴリ別 + 期待利益合計 (latest profitable CSV とマッチして)
    matched = [p for p in profitable.values()]
    by_cat = defaultdict(lambda: {"n": 0, "profit_sum": 0})
    for p in matched:
        cat = p.get("product_type") or "?"
        by_cat[cat]["n"] += 1
        try:
            profit = int(float(p.get("expected_profit_jpy") or p.get("profit_jpy") or 0))
        except ValueError:
            profit = 0
        by_cat[cat]["profit_sum"] += profit
    if by_cat:
        print(f"\n【カテゴリ別 (最新 profitable CSV)】")
        for cat, info in sorted(by_cat.items(), key=lambda x: -x[1]["profit_sum"]):
            print(f"  {cat:15s} n={info['n']:3d}  利益合計 {fmt_yen(info['profit_sum'])}")

    # 5. 在庫状況
    if inventory:
        by_inv = Counter(v.get("status", "?") for v in inventory.values())
        print(f"\n【在庫状況 (n={len(inventory)})】")
        for s, n in by_inv.most_common():
            print(f"  {s:20s} : {n} 件")

    # 6. 価格更新履歴
    if price_hist:
        changes = [
            h for h in price_hist.values()
            if abs((h.get("final_price_jpy") or 0) - (h.get("current_listed_price_jpy") or 0)) >= 1000
        ]
        print(f"\n【価格追従履歴】")
        print(f"  更新候補あり: {len(changes)} / {len(price_hist)} 件")

    # 7. CSV 出力
    if args.csv:
        out = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_sales_report.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["section", "key", "value"])
            for s, n in by_status.most_common():
                w.writerow(["status", s, n])
            for v, n in by_vendor.most_common():
                w.writerow(["vendor", v, n])
            for _, _, label in price_labels:
                w.writerow(["price_band", label, price_bins.get(label, 0)])
            for cat, info in by_cat.items():
                w.writerow(["category", cat, f"n={info['n']} profit={info['profit_sum']}"])
        print(f"\n💾 CSV 保存: {out}")


if __name__ == "__main__":
    main()
