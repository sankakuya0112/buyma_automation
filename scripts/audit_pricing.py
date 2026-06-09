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


LEGACY_COLUMN_MAP = {
    # legacy USD pipeline -> new pipeline equivalents
    "sale_price_jpy": "source_price_jpy",
    "suggested_buyma_price_jpy": "selling_price_jpy",
    "estimated_profit_jpy": "profit_jpy",
}


def _normalize_legacy_row(row: dict) -> dict:
    """旧 USD ベースの CSV を新スキーマに最低限揃える。

    audit_pricing.py は元々 Phase 2a 以降の filter_baseblu_profitable.py
    出力 (`sale_price_eur` / `selling_price_jpy` / `profit_jpy` 等) を
    想定しているが、サーバー上に残っている古い CSV (USD列のみ) でも
    集計が成立するようにする。
    """
    out = dict(row)
    for legacy_key, new_key in LEGACY_COLUMN_MAP.items():
        if not out.get(new_key) and out.get(legacy_key):
            out[new_key] = out[legacy_key]
    # マージン率を導出 (旧 CSV にはカラムなし)
    if not out.get("margin_pct"):
        try:
            profit = float(out.get("profit_jpy") or 0)
            sell = float(out.get("selling_price_jpy") or 0)
            if sell > 0:
                out["margin_pct"] = f"{(profit / sell) * 100:.2f}"
        except (TypeError, ValueError):
            pass
    return out


def load_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [_normalize_legacy_row(r) for r in rows]


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
    sell_target = _fmt_yen(row.get("selling_price_jpy"))
    profit_target = _fmt_yen(row.get("profit_jpy"))
    margin_target = float(row.get("margin_pct") or 0)
    comm = _fmt_yen(row.get("buyma_commission_jpy"))
    pay = _fmt_yen(row.get("payment_commission_jpy"))

    # Phase 2a 追加: 市場データ + 最終決定
    action = row.get("action") or "list"
    reason = row.get("decision_reason") or row.get("skip_reason") or ""
    market_median = row.get("market_median_jpy") or ""
    market_n = row.get("market_sample_count") or "0"
    breakeven = row.get("breakeven_price_jpy") or ""
    floor = row.get("floor_profit_jpy") or ""
    final_price = row.get("final_price_jpy") or ""
    exp_profit = row.get("expected_profit_jpy") or ""
    exp_margin = float(row.get("expected_margin_pct") or 0)

    # effective 利益率判定
    effective_margin = exp_margin if exp_profit else margin_target
    highlight = ""
    if min_margin is not None and effective_margin < min_margin:
        highlight = "  ⚠️ 低利益率"

    print("=" * 60)
    action_label = f"[{action.upper()}]" if action != "list" else ""
    print(f"[{idx}/{n_total}] {vendor} - {title} ({pt}) {action_label}{highlight}")
    print(f"  仕入: {eur} → {src_jpy} (rate={rate})")
    print(f"     VAT還付 -{vat}  関税({duty_rate}) +{customs}  送料 +{ship}  消費税 +{ctax}")
    print(f"     ──── 原価 {cost} ────")
    print(f"  目標売価 (25%): {sell_target}  |  利益 {profit_target} ({_fmt_pct(margin_target)})")

    comp = row.get("competition_level") or "unknown"
    if market_median:
        try:
            mm = int(float(market_median))
            n = int(float(market_n))
            print(f"  市場相場: 中央値 {_fmt_yen(mm)} (n={n}, 競合={comp})")
        except (ValueError, TypeError):
            pass
    elif comp and comp != "unknown":
        print(f"  競合密度: {comp}")

    if breakeven:
        print(f"  原価下限 (breakeven): {_fmt_yen(breakeven)}  |  最低利益 floor {_fmt_yen(floor)}")

    if action == "skip":
        print(f"  ⏭ SKIP: {reason}")
    elif final_price and str(final_price) != str(row.get("selling_price_jpy") or ""):
        print(f"  ✅ 最終売価: {_fmt_yen(final_price)} ({reason})")
        print(f"      期待利益 {_fmt_yen(exp_profit)} ({_fmt_pct(exp_margin)})  |  手数料 {comm} + {pay}")
    else:
        print(f"  ✅ 最終売価: {_fmt_yen(final_price or row.get('selling_price_jpy'))} ({reason or 'target'})  |  手数料 {comm} + {pay}")


def print_summary(rows):
    if not rows:
        print("⚠️ データなし")
        return

    # list と skip を分類
    listable = [r for r in rows if (r.get("action") or "list") == "list"]
    skipped = [r for r in rows if (r.get("action") or "list") == "skip"]

    # 出品対象での集計 (expected_* を優先し、無ければ target の値)
    def _profit(r):
        ep = r.get("expected_profit_jpy")
        if ep not in (None, "", "0"):
            try:
                return float(ep)
            except ValueError:
                pass
        return float(r.get("profit_jpy") or 0)

    def _margin(r):
        em = r.get("expected_margin_pct")
        if em not in (None, "", "0"):
            try:
                return float(em)
            except ValueError:
                pass
        return float(r.get("margin_pct") or 0)

    def _price(r):
        fp = r.get("final_price_jpy")
        if fp not in (None, "", "0"):
            try:
                return float(fp)
            except ValueError:
                pass
        return float(r.get("selling_price_jpy") or 0)

    profits = [_profit(r) for r in listable] or [0]
    margins = [_margin(r) for r in listable] or [0]
    sells = [_price(r) for r in listable] or [0]
    costs = [float(r.get("total_cost_jpy") or 0) for r in listable] or [0]

    market_n = sum(1 for r in rows if (r.get("market_median_jpy") or "").strip())

    print("=" * 60)
    print("📊 サマリ")
    print("=" * 60)
    print(f"  件数            : 合計 {len(rows)}  (出品可 {len(listable)} / スキップ {len(skipped)})")
    print(f"  市場データあり  : {market_n} / {len(rows)}")
    print(f"  利益額 中央値   : {_fmt_yen(statistics.median(profits))}")
    print(f"  利益額 平均値   : {_fmt_yen(statistics.mean(profits))}")
    print(f"  利益額 最小/最大: {_fmt_yen(min(profits))} / {_fmt_yen(max(profits))}")
    print(f"  利益率 中央値   : {_fmt_pct(statistics.median(margins))}")
    print(f"  利益率 最小/最大: {_fmt_pct(min(margins))} / {_fmt_pct(max(margins))}")
    print(f"  売価 中央値     : {_fmt_yen(statistics.median(sells))}")
    print(f"  売価 最小/最大  : {_fmt_yen(min(sells))} / {_fmt_yen(max(sells))}")
    print(f"  原価 中央値     : {_fmt_yen(statistics.median(costs))}")

    # スキップ理由内訳
    if skipped:
        reasons = {}
        for r in skipped:
            reason = r.get("skip_reason") or r.get("decision_reason") or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1
        print("\n  ⏭ スキップ理由:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count} 件")

    # カテゴリ別
    by_type = {}
    for r in listable:
        pt = r.get("product_type") or "?"
        by_type.setdefault(pt, []).append(r)
    if by_type:
        print("\n  カテゴリ別 (出品可のみ):")
        for pt in sorted(by_type):
            items = by_type[pt]
            p = [_profit(r) for r in items]
            m = [_margin(r) for r in items]
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
