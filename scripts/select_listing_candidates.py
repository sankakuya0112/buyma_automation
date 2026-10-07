"""
select_listing_candidates.py
----------------------------
手入力で出品する最初の数件の候補を、利益商品 CSV (filter_baseblu_profitable.py の出力) から選ぶ。
BUYMA にはアクセスしない (競合価格は本人が検索 URL を開いて目視する)。

    # 原価 ≤ ¥80,000・見込み利益 ≥ ¥5,000・よく出るサイズの在庫あり、売れやすいブランド優先で 5 件
    python3 scripts/select_listing_candidates.py --source baseblu --limit 5

    # 上位だけ仕入先の公開商品ページで在庫・価格・詳細 (素材など) を取り直す (2 秒間隔)
    python3 scripts/select_listing_candidates.py --source baseblu --limit 5 --refresh

出力: outputs/reports/YYYY-MM-DD_<source>_listing_candidates.csv
  (利益商品 CSV と同じ列 + brand_tier / source_available_sizes / buyma_search_url ...)。
  available_sizes は「よく出るサイズのうち在庫があるもの」に絞ってある (出品するサイズ)。
  → scripts/generate_listing_sheet.py がこの CSV から出品シートを作る。

ブランドの優先度 (data/brand_demand_tiers.json) は実測ではなく暫定の推測。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core.candidate_select import (  # noqa: E402
    canonical_brand,
    common_sizes,
    dedupe_key,
    load_brand_tiers,
    search_urls,
    select_candidates,
)
from app.utils.reports import latest_report  # noqa: E402

REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
PRICE_TOLERANCE = 0.005
EXTRA_COLUMNS = ("rank", "brand_tier", "source_available_sizes", "buyma_search_url", "buyma_search_url_sku",
                 "stock_checked_at", "stock_status", "repriced_note")
# 仕入値が変わったら意味を失う列 (古い価格での相場比較・EV スコア)
STALE_AFTER_REPRICE = ("external_action", "external_reason", "external_min_jpy", "external_url",
                       "price_edge_ratio", "source_sellthrough", "sale_probability", "opportunity_score")


def reprice(row: dict, new_price: float) -> dict:
    """仕入値が変わった行の原価・売価・利益を計算し直す (相場データなし = target 価格)。

    相場・外部比較・EV スコアの列は古い仕入値に基づくので空にする (repriced_note に理由)。
    """
    from app.core.pricing import calculate_pricing, decide_final_price
    from app.core.sources import get_source

    source = get_source(row.get("source_name") or "")
    params = source.get_pricing_params(sale_price=new_price, category=row.get("product_type", ""),
                                       title=row.get("title", ""))
    r = calculate_pricing(params)
    d = decide_final_price(r, market=None, category=row.get("product_type", ""))
    out = dict(row)
    orig = float(row.get("original_price_eur") or 0)
    out.update({
        "sale_price_eur": new_price,
        "discount_rate": round((1 - new_price / orig) * 100, 1) if orig > 0 else row.get("discount_rate", ""),
        "exchange_rate": r.exchange_rate,
        "source_price_jpy": round(r.source_price_jpy),
        "vat_refund_jpy": round(r.vat_refund_jpy),
        "shipping_jpy": round(r.shipping_jpy),
        "customs_jpy": round(r.customs_jpy),
        "duty_rate": r.duty_rate,
        "consumption_tax_jpy": round(r.consumption_tax_jpy),
        "customs_handling_jpy": round(r.customs_handling_jpy),
        "total_cost_jpy": round(r.total_cost_jpy),
        "selling_price_jpy": r.selling_price_jpy,
        "buyma_commission_jpy": round(r.buyma_commission_jpy),
        "payment_commission_jpy": round(r.payment_commission_jpy),
        "profit_jpy": round(r.profit_jpy),
        "margin_pct": r.margin_pct,
        "market_median_jpy": "",
        "market_sample_count": 0,
        "floor_profit_jpy": d.floor_profit_jpy,
        "final_price_jpy": d.final_price_jpy or "",
        "action": d.action,
        "skip_reason": "" if d.action == "list" else d.reason,
        "decision_reason": d.reason,
        "competition_level": d.competition_level,
        "expected_profit_jpy": d.expected_profit_jpy,
        "expected_margin_pct": d.expected_margin_pct,
        "breakeven_price_jpy": d.breakeven_price_jpy,
        **{k: "" for k in STALE_AFTER_REPRICE},
        "repriced_note": f"仕入値 {row.get('sale_price_eur')} → {new_price} で再計算 (相場・EV 列は空)",
    })
    return out


def refresh_row(row: dict, delay: float) -> tuple[dict | None, str]:
    """仕入先の公開商品データ (.js) で在庫・価格を確認し、baseblu なら商品ページから詳細を足す。

    戻り値 (更新後の行 or None=除外, 状態メモ)。リクエストは 1 商品につき最大 2 回、間隔 delay 秒。
    """
    from app.utils.supplier_stock import evaluate_stock, fetch_product_snapshot, price_for_listing

    url = row.get("product_url", "")
    snap = fetch_product_snapshot(url)
    time.sleep(delay)
    if snap.get("error"):
        return row, f"在庫確認エラー ({snap['error'][:60]}) → CSV の値のまま"
    listed = row.get("available_sizes", "")
    color = (row.get("color") or "").strip() if snap.get("has_color") else None
    if snap.get("has_color") and not color:
        # 色違いがある商品で色が分からないと、別の色の在庫で「あり」と誤判定しうる
        return None, "仕入先に色違いがあり、出品する色が特定できない → 除外"
    st = evaluate_stock(snap, listed, listed_color=color)
    if st["status"] == "sold_out":
        return None, "売切 (出品予定サイズの在庫なし)"
    out = dict(row)
    if st["status"] == "partial":
        keep = [s for s in listed.split(",") if s.strip() and s.strip() not in st["missing_listed_sizes"]]
        out["available_sizes"] = ", ".join(s.strip() for s in keep)
    price = price_for_listing(snap, out["available_sizes"], listed_color=color)
    note = st["status"]
    old = float(row.get("sale_price_eur") or 0)
    if price and old and abs(price - old) / old > PRICE_TOLERANCE:
        out = reprice(out, price)
        note += f" / 価格変更 {old:.2f} → {price:.2f}"
    if (row.get("source_name") or "baseblu") == "baseblu":
        import baseblu_sales_to_csv as bb
        handle = url.rstrip("/").split("/products/")[-1]
        page = bb.fetch_product_html(handle)
        time.sleep(delay)
        if page:
            details = bb._extract_details_from_html(page)
            if details and details[:40] not in (out.get("description_en") or ""):
                out["description_en"] = ((out.get("description_en") or "") + "\n\n" + details).strip()
            if not out.get("color"):
                out["color"] = bb._extract_color_from_html(page)
            if not out.get("season"):
                out["season"] = bb._extract_season(out.get("description_en", ""))
    out["stock_status"] = note
    out["stock_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return out, note


def main(argv=None):
    from app.utils.env import load_project_env
    load_project_env()
    ap = argparse.ArgumentParser(description="手入力で出品する候補を選ぶ (BUYMA にはアクセスしない)")
    ap.add_argument("--csv", default="latest", help="利益商品 CSV。既定は --source の最新")
    ap.add_argument("--source", default="baseblu")
    ap.add_argument("--max-cost", type=float, default=80000, help="総仕入原価の上限 (円、既定 80,000)")
    ap.add_argument("--min-profit", type=float, default=5000, help="見込み利益の下限 (円、既定 5,000)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--max-per-brand", type=int, default=2, help="同じブランドの上限 (既定 2、0 = 無制限)")
    ap.add_argument("--refresh", action="store_true",
                    help="上位候補だけ仕入先の公開ページで在庫・価格・詳細を取り直す (匿名、間隔 --delay 秒)")
    ap.add_argument("--delay", type=float, default=2.0, help="仕入先へのリクエスト間隔 (秒、既定 2)")
    ap.add_argument("--max-requests", type=int, default=12,
                    help="--refresh で確認する商品数の上限 (1 商品 = 最大 2 リクエスト、既定 12)")
    ap.add_argument("--out", help="出力 CSV (既定 outputs/reports/<日付>_<source>_listing_candidates.csv)")
    args = ap.parse_args(argv)

    path = args.csv if args.csv != "latest" else latest_report("profitable_products.csv", source=args.source,
                                                                 reports_dir=str(REPORTS_DIR))
    if not path or not Path(path).exists():
        print("❌ 利益商品 CSV がありません (baseblu_sales_to_csv.py → filter_baseblu_profitable.py を先に)")
        sys.exit(1)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        base_fields = list(reader.fieldnames or [])
        rows = list(reader)
    print(f"📂 {Path(path).name}: {len(rows)} 行")
    tiers = load_brand_tiers()

    # 出品するサイズ = よく出るサイズのうち在庫があるもの (元の在庫サイズは source_available_sizes に残す)
    for r in rows:
        r["source_available_sizes"] = r.get("available_sizes", "")
        r["available_sizes"] = ", ".join(common_sizes(r.get("available_sizes"), r.get("product_type", ""),
                                                      r.get("title", "")))

    def pick(rs, limit):
        return select_candidates(rs, max_cost=args.max_cost, min_profit=args.min_profit, limit=limit,
                                 data=tiers, max_per_brand=args.max_per_brand)

    if args.refresh:
        # 重複除外・ブランド上限の前の順位付きリストから在庫を確認し、売切が出たら次点で埋める。
        # 既に枠が埋まったブランド・同じ商品は確認しない (無駄なリクエストをしない)。上限 args.max_requests 件
        pool, rejected = select_candidates(rows, max_cost=args.max_cost, min_profit=args.min_profit, limit=0,
                                           data=tiers, dedupe=False, max_per_brand=0)
        checked, tried = [], 0
        for r in pool:
            if (args.limit and len(pick(checked, args.limit)[0]) >= args.limit) or tried >= args.max_requests:
                break
            accepted = pick(checked, 0)[0]
            if dedupe_key(r, tiers) in {dedupe_key(a, tiers) for a in accepted}:
                continue
            brand = canonical_brand(r.get("vendor", ""), tiers)
            if args.max_per_brand and sum(canonical_brand(a.get("vendor", ""), tiers) == brand
                                          for a in accepted) >= args.max_per_brand:
                continue
            tried += 1
            new, note = refresh_row({k: v for k, v in r.items() if k != "_eval"}, args.delay)
            print(f"   🔄 {r.get('vendor')} {r.get('title', '')[:40]}: {note}")
            if new is not None:
                checked.append(new)
        picked, more_rej = pick(checked, args.limit)
        rejected += more_rej
    else:
        picked, rejected = pick(rows, args.limit)

    out_rows = []
    for i, r in enumerate(picked, 1):
        ev = r.pop("_eval")
        urls = search_urls(r.get("vendor", ""), r.get("title", ""), r.get("sku", ""), data=tiers)
        out_rows.append({**r, "rank": i, "brand_tier": ev["tier"], **urls})

    out = Path(args.out) if args.out else REPORTS_DIR / f"{datetime.now():%Y-%m-%d}_{args.source}_listing_candidates.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(EXTRA_COLUMNS[:2]) + base_fields + [c for c in EXTRA_COLUMNS[2:] if c not in base_fields]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n✅ 候補 {len(out_rows)} 件 → {out}")
    for r in out_rows:
        price = int(float(r.get("final_price_jpy") or r.get("selling_price_jpy") or 0))
        print(f"  #{r['rank']} [{r['brand_tier']}] {r.get('vendor')} {r.get('title')}"
              f"\n      原価 ¥{int(float(r['total_cost_jpy'])):,} / 提案 ¥{price:,} / 利益 ¥{int(float(r['expected_profit_jpy'])):,}"
              f" / サイズ {r.get('available_sizes')}\n      {r.get('product_url')}\n      {r['buyma_search_url']}")
    from collections import Counter
    why = Counter((reasons[0].split(" ")[0] if reasons else "?") for _, reasons in rejected)
    print(f"\n   除外 {len(rejected)} 件: " + ", ".join(f"{k} {v}" for k, v in why.most_common(6)))
    print("   次: python3 scripts/generate_listing_sheet.py --csv", out)


if __name__ == "__main__":
    main()
