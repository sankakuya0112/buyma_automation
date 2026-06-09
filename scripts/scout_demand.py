"""
scout_demand.py — 需要起点の仕入れスカウト (Phase 2d)
------------------------------------------------------
従来のパイプラインは「baseblu のセール品 (供給) → BUYMA 相場確認」の
供給起点だった。本スクリプトはこれを逆転し、

    BUYMA の需要データ → 「どのブランド/商品を仕入れに行くべきか」

を出す需要起点のスカウトを行う。「相場より安く・需要のある商品」は
供給側を眺めていても見つからない。需要側から逆引きする。

## モード 1: 需要インデックス構築 (オフライン、サーバーで実行可)

これまでの market fetch で蓄積した data/market_cache/*.json を
ブランド単位に集計し、ブランドを 4 区分に分類する:

    proven_high_demand : 平均 n >= 10。需要実証済み。
                         → 原価優位があれば price_leader で勝てる。
                           仕入先横断で「最安値を下回れる仕入値」を探す価値大
    sweet_spot         : 平均 n 2-9 + 中央値が高い。需要があり競合が薄い。
                         → 最優先の仕入れターゲット
    exclusive          : 平均 n <= 1。独占可能だが需要未検証。
                         → 少量出品で反応を見る (ロングテール戦略)
    unreliable         : brand_match_confidence が低い等、データ品質不足

    python3 scripts/scout_demand.py                    # 集計 + ランキング表示
    python3 scripts/scout_demand.py --out data/demand_index.json

## モード 2: 仕入元との突き合わせ (オフライン)

需要インデックスと最新の baseblu セール CSV を突き合わせ、
「需要実証済みブランドのセール品が今 baseblu に出ているか」を出す:

    python3 scripts/scout_demand.py --match-source latest

## モード 3: ブランド需要の能動調査 (Mac で実行)

仕入候補ブランドの BUYMA 需要を能動的に取得する (market_cache に蓄積され、
次回のモード 1 集計に反映される):

    python3 scripts/scout_demand.py --probe "JACQUEMUS" "GANNI" "ALAÏA"

vendor リストは baseblu CSV から自動取得も可能:

    python3 scripts/scout_demand.py --probe-from-csv latest

運用サイクル:
    1. (Mac) fetch_buyma_market_prices.py --csv latest   ← 出品候補の相場取得
    2. (Mac) scout_demand.py --probe-from-csv latest     ← 全 vendor の需要調査
    3. (どこでも) scout_demand.py --match-source latest  ← 需要×供給の交点を出す
    4. 交点の商品を filter → 出品 (price_leader / sweet_spot 優先)
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "data" / "market_cache"
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "demand_index.json"

# ブランド分類の閾値
HIGH_DEMAND_MIN_N = 10        # 平均サンプル数がこれ以上 → 需要実証済み
SWEET_SPOT_MIN_N = 2          # sweet_spot の下限
MIN_CONFIDENCE = 0.5          # brand_match_confidence がこれ未満 → unreliable


def load_cache_entries(cache_dir: Path = CACHE_DIR) -> list[dict]:
    """market_cache の全 JSON を読み込む (鮮度は問わない: 需要傾向は変化が遅い)。"""
    entries = []
    for path in sorted(glob.glob(str(cache_dir / "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict) and "brand" in data:
            entries.append(data)
    return entries


def build_demand_index(entries: list[dict]) -> dict:
    """キャッシュエントリをブランド単位に集計して需要インデックスを返す。

    Returns:
        {
          "BRAND": {
            "classification": "sweet_spot" | "proven_high_demand" | "exclusive" | "unreliable",
            "n_queries": クエリ数,
            "avg_sample_count": 平均出品数,
            "max_sample_count": 最大出品数,
            "median_price_jpy": 相場中央値の中央値,
            "wish_total": お気に入り合計 (取得済みの場合),
            "min_confidence": 最低 brand_match_confidence,
          }, ...
        }
    """
    by_brand: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        brand = (e.get("brand") or "").strip()
        if brand:
            by_brand[brand].append(e)

    index: dict[str, dict] = {}
    for brand, brand_entries in by_brand.items():
        counts = [int(e.get("sample_count") or 0) for e in brand_entries]
        medians = [e.get("median_jpy") for e in brand_entries if e.get("median_jpy")]
        confidences = [
            float(e.get("brand_match_confidence", 1.0)) for e in brand_entries
        ]
        wishes = [int(e.get("wish_total") or 0) for e in brand_entries]

        avg_n = statistics.mean(counts) if counts else 0
        max_n = max(counts) if counts else 0
        med_price = int(statistics.median(medians)) if medians else None
        min_conf = min(confidences) if confidences else 1.0
        wish_total = sum(wishes)

        if min_conf < MIN_CONFIDENCE:
            cls = "unreliable"
        elif avg_n >= HIGH_DEMAND_MIN_N:
            cls = "proven_high_demand"
        elif avg_n >= SWEET_SPOT_MIN_N:
            cls = "sweet_spot"
        else:
            cls = "exclusive"

        index[brand] = {
            "classification": cls,
            "n_queries": len(brand_entries),
            "avg_sample_count": round(avg_n, 1),
            "max_sample_count": max_n,
            "median_price_jpy": med_price,
            "wish_total": wish_total,
            "min_confidence": round(min_conf, 2),
        }
    return index


def print_index_report(index: dict) -> None:
    """需要インデックスのランキングを表示する。"""
    order = {"sweet_spot": 0, "proven_high_demand": 1, "exclusive": 2, "unreliable": 3}
    label = {
        "sweet_spot": "🎯 SWEET SPOT (需要あり×競合薄 → 最優先仕入れ)",
        "proven_high_demand": "🔥 需要実証済み (原価優位なら price_leader で勝負)",
        "exclusive": "🌱 独占可能 (需要未検証 → 少量で反応観察)",
        "unreliable": "❓ データ品質不足 (再 fetch 推奨)",
    }
    groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for brand, stats in index.items():
        groups[stats["classification"]].append((brand, stats))

    print("=" * 70)
    print("📊 ブランド需要インデックス")
    print("=" * 70)
    for cls in sorted(groups, key=lambda c: order.get(c, 9)):
        items = groups[cls]
        # 相場中央値が高い順 (単価が高い = 1 成約あたりの利益余地が大きい)
        items.sort(key=lambda kv: -(kv[1]["median_price_jpy"] or 0))
        print(f"\n{label.get(cls, cls)} — {len(items)} ブランド")
        for brand, s in items:
            med = f"¥{s['median_price_jpy']:,}" if s["median_price_jpy"] else "n/a"
            wish = f" wish={s['wish_total']}" if s["wish_total"] else ""
            print(
                f"   {brand[:28]:28s} 平均n={s['avg_sample_count']:5.1f} "
                f"相場中央値={med:>12s} (クエリ{s['n_queries']}件{wish})"
            )


def latest_sales_csv() -> str | None:
    pattern = str(PROJECT_ROOT / "outputs" / "reports" / "*_baseblu_sales_products_sorted.csv")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def match_source(index: dict, csv_path: str) -> list[dict]:
    """需要インデックスと仕入元セール CSV を突き合わせる。

    需要が確認できているブランド (sweet_spot / proven_high_demand) の
    在庫ありセール品を返す。
    """
    target_brands = {
        b.upper(): s for b, s in index.items()
        if s["classification"] in ("sweet_spot", "proven_high_demand")
    }
    matches = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if str(row.get("available", "")).strip().lower() not in ("true", "1", "yes"):
                continue
            vendor = (row.get("vendor") or "").strip().upper()
            if vendor in target_brands:
                stats = target_brands[vendor]
                matches.append({
                    "vendor": row.get("vendor"),
                    "title": row.get("title"),
                    "sale_price": row.get("sale_price"),
                    "discount_rate": row.get("discount_rate"),
                    "classification": stats["classification"],
                    "market_median_jpy": stats["median_price_jpy"],
                    "product_url": row.get("product_url"),
                })
    return matches


def print_matches(matches: list[dict]) -> None:
    if not matches:
        print("\n⚠️ 需要確認済みブランドのセール在庫なし。")
        print("   --probe で調査ブランドを増やすか、新しいセール CSV を取得してください。")
        return
    print("\n" + "=" * 70)
    print(f"💎 需要 × 供給の交点: {len(matches)} 件 (仕入れ候補)")
    print("=" * 70)
    for m in sorted(matches, key=lambda x: 0 if x["classification"] == "sweet_spot" else 1):
        tag = "🎯" if m["classification"] == "sweet_spot" else "🔥"
        med = f"¥{m['market_median_jpy']:,}" if m["market_median_jpy"] else "n/a"
        print(f" {tag} {m['vendor'][:24]:24s} {str(m['title'])[:38]:38s}")
        print(f"     仕入 €{m['sale_price']} (-{m['discount_rate']}%)  BUYMA相場 {med}")
        print(f"     {m['product_url']}")


def probe_brands(brands: list[str]) -> None:
    """ブランド単位で BUYMA 需要を能動取得する (Mac 専用、要ネットワーク)。

    fetch_buyma_market_prices.fetch_market_for を keyword なし (ブランド名のみ)
    で呼び、結果をキャッシュに保存する。次回の build_demand_index に反映される。
    """
    import random
    import time as _time

    from fetch_buyma_market_prices import (
        REQUEST_DELAY_RANGE, fetch_market_for, load_cached, save_cache,
    )
    from playwright.sync_api import sync_playwright

    print(f"🔍 {len(brands)} ブランドの BUYMA 需要を調査...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()
        for i, brand in enumerate(brands, 1):
            brand = brand.strip()
            if not brand:
                continue
            cached = load_cached(brand, "")
            if cached:
                print(f"  [{i}/{len(brands)}] {brand[:30]} → cache (n={cached.get('sample_count', 0)})")
                continue
            result = fetch_market_for(brand, "", page=page)
            save_cache(brand, "", result)
            print(
                f"  [{i}/{len(brands)}] {brand[:30]} → n={result.get('sample_count', 0)} "
                f"median=¥{result.get('median_jpy') or 0:,} wish={result.get('wish_total', 0)}"
            )
            _time.sleep(random.uniform(*REQUEST_DELAY_RANGE))
        browser.close()
    print("✅ 調査完了。scout_demand.py (引数なし) で集計に反映されます。")


def vendors_from_csv(csv_path: str) -> list[str]:
    seen: dict[str, None] = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            v = (row.get("vendor") or "").strip()
            if v:
                seen.setdefault(v, None)
    return list(seen)


def main():
    parser = argparse.ArgumentParser(description="需要起点の仕入れスカウト")
    parser.add_argument("--out", help="需要インデックス JSON の出力先 "
                        f"(default: {DEFAULT_INDEX_PATH})")
    parser.add_argument("--match-source", metavar="CSV",
                        help="仕入元セール CSV と突き合わせ ('latest' で最新自動選択)")
    parser.add_argument("--probe", nargs="+", metavar="BRAND",
                        help="ブランドの BUYMA 需要を能動調査 (Mac 専用)")
    parser.add_argument("--probe-from-csv", metavar="CSV",
                        help="CSV の全 vendor を需要調査 (Mac 専用、'latest' 可)")
    args = parser.parse_args()

    # モード 3: 能動調査 (Mac)
    if args.probe or args.probe_from_csv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        if args.probe_from_csv:
            csv_path = args.probe_from_csv
            if csv_path.lower() == "latest":
                csv_path = latest_sales_csv()
                if not csv_path:
                    print("❌ セール CSV が見つかりません")
                    sys.exit(1)
            brands = vendors_from_csv(csv_path)
        else:
            brands = args.probe
        probe_brands(brands)
        return

    # モード 1: インデックス構築
    entries = load_cache_entries()
    if not entries:
        print("⚠️ data/market_cache/ にキャッシュがありません。")
        print("   先に Mac で fetch_buyma_market_prices.py --csv latest または")
        print("   scout_demand.py --probe-from-csv latest を実行してください。")
        sys.exit(0)

    index = build_demand_index(entries)
    print_index_report(index)

    out_path = Path(args.out) if args.out else DEFAULT_INDEX_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "built_at": datetime.now().isoformat(),
            "n_cache_entries": len(entries),
            "brands": index,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 需要インデックス保存: {out_path}")

    # モード 2: 仕入元突き合わせ
    if args.match_source:
        csv_path = args.match_source
        if csv_path.lower() == "latest":
            csv_path = latest_sales_csv()
        if not csv_path or not Path(csv_path).exists():
            print(f"❌ セール CSV が見つかりません: {args.match_source}")
            sys.exit(1)
        matches = match_source(index, csv_path)
        print_matches(matches)


if __name__ == "__main__":
    main()
