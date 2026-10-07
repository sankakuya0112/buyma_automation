"""
update_listed_prices.py
------------------------
出品中商品の価格を、最新の仕入値 + 為替 + 相場 に基づいて再評価し、
大きく乖離していれば BUYMA 側で価格を更新するフレームワーク。

Phase 2-3: 「価格追従」。仕入先 (baseblu) の値下げに追従できないと売れ逃し、
値上げに追従できないと赤字、為替変動に追従できないと機会損失。
定期実行 (日次) 想定。

使い方:
    # ドライラン: 価格差分を表示するだけ
    python3 scripts/update_listed_prices.py --dry-run

    # 変動幅 X 円以上の商品だけレビュー用にレポート
    python3 scripts/update_listed_prices.py --threshold 5000

    # BUYMA で本人が価格を更新したら、その価格を記録 (次回の比較基準になる)
    python3 scripts/update_listed_prices.py --confirm 123456789=98000

    ※ BUYMA 上の価格をブラウザ自動操作で書き換える --execute は 2026-10 に廃止。

データソース:
    1. 出品記録: outputs/reports/*_auto_listing_results.csv (item_id, product_url)
    2. 最新仕入値: 出品記録の仕入先 (source_name、無ければ URL から推定) の
       Shopify 公開データ /products/<handle>.js。出品したサイズのうち在庫ありの最高値
    3. (任意) 市場相場: outputs/reports/*_market_prices.json
       (--market で指定。省略時は最新を自動選択、無ければ相場なしで判定)

    1 から handle を抽出 → 2 で最新価格取得 → pricing.calculate_pricing で
    最新原価を計算 → decide_final_price(market, category=product_type) で
    新売価を算出 → 現売価との差分を表示。

状態管理:
    data/price_history.json - 過去の価格更新履歴

実装状態:
    - 差分検出: 実装済み (仕入先ごと・サイズごと)
    - BUYMA 上の価格更新: 本人が BUYMA の画面 (権限があれば一括出品編集) で行い、--confirm で記録する
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import (
    PricingParams, calculate_pricing,
    MarketStats, decide_final_price,
)
from app.core.sources import get_source
from app.utils.reports import latest_report
from app.utils.supplier_stock import (
    fetch_product_snapshot,
    known_source_hosts,
    price_for_listing,
    resolve_record_source,
)
# scripts/ は上で sys.path に入れてあるので、filter の相場 lookup をそのまま再利用する
from filter_baseblu_profitable import get_market_stats, load_market_data

HISTORY_PATH = PROJECT_ROOT / "data" / "price_history.json"
RESULTS_GLOB = PROJECT_ROOT / "outputs" / "reports" / "*_auto_listing_results.csv"
def extract_handle(url: str):
    if not url:
        return None
    m = re.search(r"/products/([^/?#]+)", url)
    return m.group(1) if m else None


def fetch_current_source_price(record: dict, source_name: str) -> dict:
    """出品記録の仕入先から現在価格を取る (出品したサイズのうち在庫ありの最高値)。

    戻り値: {"price": 現地通貨 or None, "product_type", "title", "source_name", "error"?}
    """
    snap = fetch_product_snapshot(record.get("product_url") or "")
    if snap.get("error"):
        return {"error": snap["error"], "price": None, "source_name": source_name}
    price = price_for_listing(snap, record.get("listed_sizes") or "", record.get("listed_color") or "")
    return {
        "price": price,
        "product_type": snap.get("product_type", "") or record.get("product_type", ""),
        "title": snap.get("title", "") or record.get("title", ""),
        "source_name": source_name,
        **({"error": "出品したサイズの在庫がありません"} if price is None else {}),
    }


def build_pricing_params(latest: dict) -> PricingParams:
    """最新の仕入値から、**その商品の仕入先** の原価体系で PricingParams を組み立てる。

    カード手数料・国内送料・通関手数料・固定国際送料・為替は get_pricing_params() でしか
    入らないので、PricingParams を直接作らないこと。
    latest["source_name"] が空なら baseblu (旧形式の記録)。未登録の仕入先は ValueError。
    価格のキーは "price" (旧 "price_eur" も可)。title は英語タイトル (靴の革/布判定用)。
    """
    price = latest.get("price")
    if price is None:
        price = latest.get("price_eur")
    return get_source(latest.get("source_name") or "").get_pricing_params(
        sale_price=float(price),
        category=latest.get("product_type", "") or "",
        title=latest.get("title", "") or "",
    )


def decide_for_record(record: dict, latest: dict, market_data: dict | None = None):
    """出品記録 1 件を「最新仕入値 + 相場 + カテゴリ別の最低利益」で再評価する (Playwright 非依存)。

    filter_baseblu_profitable.py と同じ形で decide_final_price を呼ぶ。
    2026-09-24 以前は相場もカテゴリも渡しておらず、競合が多い商品を高いまま、
    靴・服の最低利益 (¥10,000) を無視して判定していた。

    market_data は fetch_buyma_market_prices.py の JSON ({} なら no_market_data)。
    旧形式の出品記録には sku / source_name 列が無いので、その場合は vendor|title で相場を引く。
    戻り値は (PricingResult, FinalPriceDecision)。
    """
    result = calculate_pricing(build_pricing_params(latest))
    market = get_market_stats(
        market_data or {},
        record.get("vendor", ""),
        record.get("title", ""),
        sku=record.get("sku", ""),
        source_name=record.get("source_name", ""),
    )
    category = latest.get("product_type", "") or record.get("product_type", "") or ""
    decision = decide_final_price(result, market=market, category=category)
    return result, decision


def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(data: dict):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_listing_records() -> list[dict]:
    """出品記録 CSV を全部読み、item_id でユニーク化して返す (最新 CSV の行を優先)。

    仕入先 URL (product_url) からハンドルを取れない行は価格追従できないので除外し、
    件数だけ 1 回表示する (2026-09-24 以前の旧形式 CSV には product_url 列が無い)。
    """
    recs = {}
    legacy = 0
    for path in sorted(glob.glob(str(RESULTS_GLOB))):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("status") not in ("draft", "published"):
                    continue
                # 旧版は公開時に item_id="published" という文字列を記録していた (実 ID ではない)
                if not str(row.get("item_id") or "").strip().isdigit():
                    continue
                if not extract_handle(row.get("product_url") or ""):
                    legacy += 1
                    continue
                recs[row["item_id"]] = row
    if legacy:
        print(f"ℹ️ 仕入先 URL の無い旧形式の出品記録 {legacy} 件は対象外 (product_url 列が無い CSV)")
    return list(recs.values())


def current_listed_price(record: dict, history: dict) -> int:
    """比較基準の現売価。本人が --confirm で記録した価格を優先、無ければ出品時の CSV の価格。"""
    confirmed = (history.get(record.get("item_id", "")) or {}).get("confirmed_listed_price_jpy")
    if confirmed:
        return int(confirmed)
    try:
        return int(float(record.get("price") or 0))
    except ValueError:
        return 0


def confirm_prices(pairs: list[str]) -> int:
    """--confirm ITEM_ID=PRICE を data/price_history.json に記録する。"""
    history = load_history()
    n = 0
    for pair in pairs:
        item_id, _, price = pair.partition("=")
        item_id = item_id.strip()
        if not item_id.isdigit() or not price.strip().isdigit():
            print(f"❌ 形式は ITEM_ID=PRICE (数字のみ): {pair!r}")
            continue
        rec = history.setdefault(item_id, {})
        rec["confirmed_listed_price_jpy"] = int(price)
        rec["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
        n += 1
        print(f"✅ {item_id}: 現売価 ¥{int(price):,} を記録")
    save_history(history)
    return n


def run(threshold: int, throttle: float, limit, market_data: dict | None = None):
    print("=" * 50)
    print("💰 価格追従 (差分の表示のみ。BUYMA の価格は本人が更新)")
    print("=" * 50)
    if not market_data:
        print("  ℹ️ 相場データなし: 競合を見ずに目標価格で判定します (--market で指定可)")

    records = load_listing_records()
    if limit:
        records = records[:limit]
    print(f"  対象: {len(records)} 件")
    if not records:
        return

    hosts = known_source_hosts()
    history = load_history()
    differs = []   # (item_id, old_price, new_price, diff, title)
    summary = {"unchanged": 0, "changed": 0, "skip": 0, "unknown_source": 0, "error": 0}

    for i, r in enumerate(records, 1):
        item_id = r["item_id"]
        source_name = resolve_record_source(r, hosts)
        if not source_name:
            summary["unknown_source"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ❓ 仕入先が分からないため未確認")
            continue

        old_price = current_listed_price(r, history)
        latest = fetch_current_source_price(r, source_name)
        if latest.get("error") or latest.get("price") is None:
            summary["error"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ❌ 取得失敗 ({latest.get('error', '')[:60]})")
            time.sleep(throttle)
            continue

        try:
            result, decision = decide_for_record(r, latest, market_data)
        except ValueError as exc:   # 未登録の仕入先など
            summary["error"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ❌ {exc}")
            continue

        if decision.action == "skip":
            summary["skip"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ⚠️ 出品継続が難しい判定、要停止検討 (reason={decision.reason})")
            time.sleep(throttle)
            continue

        new_price = decision.final_price_jpy
        diff = new_price - old_price
        if abs(diff) < threshold:
            summary["unchanged"] += 1
        else:
            summary["changed"] += 1
            differs.append((item_id, old_price, new_price, diff, r.get("title", "")))
            print(f"  [{i}/{len(records)}] {item_id} 💱 ¥{old_price:,} → ¥{new_price:,} ({diff:+,})")

        rec = history.setdefault(item_id, {})
        rec.update({
            "last_check_at": datetime.now().isoformat(timespec="seconds"),
            "source_name": source_name,
            "source_price_local": latest["price"],
            "exchange_rate": result.exchange_rate,
            "target_price_jpy": result.selling_price_jpy,
            "final_price_jpy": new_price,
            "compared_listed_price_jpy": old_price,
            "decision_reason": decision.reason,
            "market_median_jpy": decision.market_median_jpy,
            "market_sample_count": decision.market_sample_count,
        })
        time.sleep(throttle)

    save_history(history)

    print()
    print("=" * 50)
    print("📊 集計")
    print("=" * 50)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not differs:
        print("\n✅ 閾値以上の変動なし")
        return

    print(f"\n💡 更新候補 ({len(differs)} 件, 閾値 ±¥{threshold:,}) — BUYMA で本人が更新し、--confirm で記録:")
    for item_id, old, new, d, title in differs:
        print(f"  {item_id} | {title[:35]}")
        print(f"    ¥{old:,} → ¥{new:,} ({d:+,})")
        print(f"    → https://www.buyma.com/my/sell/{item_id}/edit?tab=b")
        print(f"    記録: python3 scripts/update_listed_prices.py --confirm {item_id}={new}")


def resolve_market_path(market_arg: str | None) -> str | None:
    """--market の解決。省略時は最新の *_market_prices.json、'' や存在しないパスなら None (相場なし)。"""
    if market_arg is None:
        return latest_report("market_prices.json")
    if market_arg and os.path.exists(market_arg):
        return market_arg
    return None


def main(argv=None):
    from app.utils.env import load_project_env
    load_project_env()   # .env の為替・手数料・ガード設定を計算前に反映 (シェルの値が優先)
    parser = argparse.ArgumentParser(description="出品中商品の価格追従")
    parser.add_argument("--dry-run", action="store_true", help="(互換用。常に差分の表示のみ)")
    parser.add_argument("--execute", action="store_true", help="廃止: BUYMA の価格は自動更新しません")
    parser.add_argument("--confirm", nargs="+", metavar="ITEM_ID=PRICE",
                        help="BUYMA で本人が更新した現売価を記録 (次回の比較基準)")
    parser.add_argument("--threshold", type=int, default=3000,
                        help="更新候補とする価格差分 (円、default 3000)")
    parser.add_argument("--throttle", type=float, default=0.8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--market", help="相場 JSON (fetch_buyma_market_prices.py の出力)。"
                        "省略時は outputs/reports の最新 *_market_prices.json、'' で相場なし")
    args = parser.parse_args(argv)
    if args.execute:
        from app.utils.automation_guard import refuse_buyma_write
        refuse_buyma_write("BUYMA の価格更新 (update_listed_prices --execute)")
    if args.confirm:
        confirm_prices(args.confirm)
        return
    market_path = resolve_market_path(args.market)
    if market_path:
        print(f"📈 相場: {market_path}")
    run(threshold=args.threshold, throttle=args.throttle, limit=args.limit,
        market_data=load_market_data(market_path))


if __name__ == "__main__":
    main()
