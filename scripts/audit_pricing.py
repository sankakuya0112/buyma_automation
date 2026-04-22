"""
audit_pricing.py — 既存 *_baseblu_profitable_products.csv の価格内訳を可視化する。

目的:
  Phase 2 (本公開) 前に、各商品の「仕入値 → 売価 → 利益」の計算内訳をユーザが
  目視で妥当性確認できるようにする。パラメータ (為替 163 円/EUR, VAT 還付
  16.7%, 国際送料 3,000 円/kg, 目標利益率 25% 等) の見直し根拠にも使う。

使い方:
  python3 scripts/audit_pricing.py                # 全件を 1 行ずつ表示
  python3 scripts/audit_pricing.py --top 5        # 利益順上位 5 件のみ
  python3 scripts/audit_pricing.py --summary      # 集計サマリのみ
  python3 scripts/audit_pricing.py --csv          # 監査用 CSV を別ファイルに出力
  python3 scripts/audit_pricing.py --min-margin 10  # 利益率 10% 未満をハイライト
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import statistics
import sys
from datetime import datetime

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs", "reports")


def _fmt_yen(n):
    try:
        return f"¥{int(float(n)):,}"
    except (TypeError, ValueError):
        return "¥?"


def _fmt_eur(n):
    try:
        return f"€{float(n):,.2f}"
    except (TypeError, ValueError):
        return "€?"


def _fmt_pct(n):
    try:
        return f"{float(n):.1f}%"
    except (TypeError, ValueError):
        return "?"


def _latest_profitable_csv():
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_profitable_products.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    return files[-1]


def load_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def print_item(idx, n_total, row, min_margin=None):
    title = (row.get("title") or "")[:40]
    vendor = row.get("vendor") or "?"
    pt = row.get("product_type") or "?"
    eur = _fmt_eur(row.get("sale_price_eur"))
    rate = row.get("exchange_rate") or "?"
    src_jpy = _fmt_yen(row.get("source_price_jpy"))
    vat = _fmt_yen(row.get("vat_refund_jpy"))
    customs = _fmt_yen(row.get("customs_jpy"))
    duty_rate = _fmt_pct(float(row.get("duty_rate") or 0) * 100) if row.get("duty_rate") else "?"
    ship = _fmt_yen(row.get("shipping_jpy"))
    ctax = _fmt_yen(row.get("consumption_tax_jpy"))
    cost = _fmt_yen(row.get("total_cost_jpy"))
    sell = _fmt_yen(row.get("selling_price_jpy"))
    profit = _fmt_yen(row.get("profit_jpy"))
    margin = float(row.get("margin_pct") or 0)
    comm = _fmt_yen(row.get("buyma_commission_jpy"))
    pay = _fmt_yen(row.get("payment_commission_jpy"))

    highlight = ""
    if min_margin is not None and margin < min_margin:
        highlight = "  ⚠️ 低利益率"

    print("=" * 60)
    print(f"[{idx}/{n_total}] {vendor} - {title} ({pt}){highlight}")
    print(f"  仕入: {eur} → {src_jpy} (rate={rate})")
    print(f"     VAT還付 -{vat}  関税({duty_rate}) +{customs}  送料 +{ship}  消費税 +{ctax}")
    print(f"     ──── 原価 {cost} ────")
    print(f"  売価 {sell}  |  手数料 {comm} + {pay}  |  利益 {profit}  |  利益率 {_fmt_pct(margin)}")


def print_summary(rows):
    if not rows:
        print("⚠️ データなし")
        return

    profits = [float(r.get("profit_jpy") or 0) for r in rows]
    margins = [float(r.get("margin_pct") or 0) for r in rows]
    sells = [float(r.get("selling_price_jpy") or 0) for r in rows]
    costs = [float(r.get("total_cost_jpy") or 0) for r in rows]

    print("=" * 60)
    print("📊 サマリ")
    print("=" * 60)
    print(f"  件数            : {len(rows)}")
    print(f"  利益額 中央値   : {_fmt_yen(statistics.median(profits))}")
    print(f"  利益額 平均値   : {_fmt_yen(statistics.mean(profits))}")
    print(f"  利益額 最小/最大: {_fmt_yen(min(profits))} / {_fmt_yen(max(profits))}")
    print(f"  利益率 中央値   : {_fmt_pct(statistics.median(margins))}")
    print(f"  利益率 最小/最大: {_fmt_pct(min(margins))} / {_fmt_pct(max(margins))}")
    print(f"  売価 中央値     : {_fmt_yen(statistics.median(sells))}")
    print(f"  売価 最小/最大  : {_fmt_yen(min(sells))} / {_fmt_yen(max(sells))}")
    print(f"  原価 中央値     : {_fmt_yen(statistics.median(costs))}")

    # カテゴリ別
    by_type = {}
    for r in rows:
        pt = r.get("product_type") or "?"
        by_type.setdefault(pt, []).append(r)
    print("\n  カテゴリ別:")
    for pt in sorted(by_type):
        items = by_type[pt]
        p = [float(r.get("profit_jpy") or 0) for r in items]
        m = [float(r.get("margin_pct") or 0) for r in items]
        print(
            f"    {pt:15s} n={len(items):3d}  "
            f"利益中央値 {_fmt_yen(statistics.median(p)):>10s}  "
            f"利益率中央値 {_fmt_pct(statistics.median(m)):>7s}"
        )


def save_audit_csv(rows, out_path):
    fieldnames = [
        "title", "vendor", "product_type",
        "sale_price_eur", "exchange_rate",
        "source_price_jpy", "vat_refund_jpy", "customs_jpy", "duty_rate",
        "shipping_jpy", "consumption_tax_jpy", "total_cost_jpy",
        "buyma_commission_jpy", "payment_commission_jpy",
        "selling_price_jpy", "profit_jpy", "margin_pct",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    parser = argparse.ArgumentParser(description="baseblu profitable CSV の価格内訳監査")
    parser.add_argument("--csv-path", help="対象 CSV (省略時は最新を自動選択)")
    parser.add_argument("--top", type=int, help="利益順上位 N 件のみ表示")
    parser.add_argument("--summary", action="store_true", help="サマリのみ表示")
    parser.add_argument("--csv", action="store_true", help="監査 CSV を別ファイルに出力")
    parser.add_argument("--min-margin", type=float, default=10.0,
                        help="この利益率未満を警告表示 (default: 10%%)")
    args = parser.parse_args()

    csv_path = args.csv_path or _latest_profitable_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("❌ profitable CSV が見つかりません。先に filter_baseblu_profitable.py を実行してください。")
        sys.exit(1)

    print(f"📂 対象 CSV: {csv_path}")
    rows = load_rows(csv_path)
    # 利益順降順
    rows.sort(key=lambda r: float(r.get("profit_jpy") or 0), reverse=True)
    print(f"✅ {len(rows)} 件読込")

    if args.summary:
        print_summary(rows)
        return

    target = rows[: args.top] if args.top else rows
    for i, r in enumerate(target, 1):
        print_item(i, len(target), r, min_margin=args.min_margin)

    print()
    print_summary(rows)

    if args.csv:
        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = os.path.join(OUTPUT_DIR, f"{date_str}_pricing_audit.csv")
        save_audit_csv(rows, out_path)
        print(f"\n💾 監査 CSV 出力: {out_path}")


if __name__ == "__main__":
    main()
