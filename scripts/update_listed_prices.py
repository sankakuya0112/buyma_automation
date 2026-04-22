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

    # BUYMA 上で実際に価格更新する (スケルトン、手動推奨)
    python3 scripts/update_listed_prices.py --execute

データソース:
    1. 出品記録: outputs/reports/*_auto_listing_results.csv (item_id, product_url)
    2. 最新仕入値: baseblu Shopify API の /products/{handle}.json 現在価格
    3. (任意) 市場相場: data/market_cache/*.json

    1 から handle を抽出 → 2 で最新価格取得 → pricing.calculate_pricing で
    最新原価を計算 → decide_final_price で新売価を算出 → 現売価との差分を表示。

状態管理:
    data/price_history.json - 過去の価格更新履歴

実装状態:
    - 差分検出ロジック: 実装済み
    - BUYMA 上の価格更新: スケルトン (Playwright 自動操作を TODO として残す)
      初回運用では差分レポートのみ → ユーザが手動で更新が安全。
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import (
    PricingParams, calculate_pricing,
    MarketStats, decide_final_price,
)

HISTORY_PATH = PROJECT_ROOT / "data" / "price_history.json"
RESULTS_GLOB = PROJECT_ROOT / "outputs" / "reports" / "*_auto_listing_results.csv"
BASEBLU_DETAIL_API = "https://www.baseblu.com/en-us/products/{handle}.json"


def extract_handle(url: str):
    if not url:
        return None
    m = re.search(r"/products/([^/?#]+)", url)
    return m.group(1) if m else None


def fetch_current_source_price(handle: str) -> dict:
    """baseblu 個別商品 JSON から最新価格を取得。"""
    import requests
    try:
        resp = requests.get(
            BASEBLU_DETAIL_API.format(handle=handle),
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        product = resp.json().get("product", {}) or {}
    except Exception as e:
        return {"error": str(e), "price_eur": None}

    variants = product.get("variants", []) or []
    # 最初の available variant の price を使う
    price = None
    for v in variants:
        if v.get("available") and v.get("price"):
            try:
                price = float(v["price"])
                break
            except (ValueError, TypeError):
                continue
    if price is None and variants:
        try:
            price = float(variants[0].get("price", 0))
        except (ValueError, TypeError):
            price = None

    return {
        "price_eur": price,
        "product_type": product.get("product_type", ""),
        "title": product.get("title", ""),
    }


def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.load(open(HISTORY_PATH, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_history(data: dict):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_listing_records() -> list[dict]:
    recs = {}
    for path in sorted(glob.glob(str(RESULTS_GLOB))):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("status") not in ("draft", "published"):
                    continue
                if not row.get("item_id"):
                    continue
                recs[row["item_id"]] = row
    return list(recs.values())


def update_listing_price(page, item_id: str, new_price: int) -> bool:
    """BUYMA 上で価格を更新する (スケルトン)。

    TODO: 実装
        1. /my/sell/{item_id}/edit?tab=b に遷移
        2. 「販売価格」input を特定
        3. 値をクリア → 新価格をタイプ
        4. 「保存」ボタンクリック → 確認モーダル対応
        5. URL 遷移で成否判定
    """
    return False


def run(dry_run: bool, threshold: int, throttle: float, limit):
    print("=" * 50)
    print(f"💰 価格追従 {'(ドライラン)' if dry_run else '(実行モード)'}")
    print("=" * 50)

    records = load_listing_records()
    if limit:
        records = records[:limit]
    print(f"  対象: {len(records)} 件")
    if not records:
        return

    history = load_history()
    differs = []   # (item_id, old_price, new_price, diff, title)
    errors = 0
    summary = {"unchanged": 0, "changed": 0, "skip": 0, "error": 0}

    for i, r in enumerate(records, 1):
        item_id = r["item_id"]
        url = r.get("product_url", "")
        handle = extract_handle(url)
        if not handle:
            errors += 1
            summary["error"] += 1
            continue

        old_price = 0
        try:
            old_price = int(float(r.get("price") or 0))
        except ValueError:
            pass

        latest = fetch_current_source_price(handle)
        if latest.get("error") or latest.get("price_eur") is None:
            summary["error"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ❌ 取得失敗")
            time.sleep(throttle)
            continue

        params = PricingParams(
            source_price=latest["price_eur"],
            currency="EUR",
            category=latest.get("product_type", ""),
        )
        result = calculate_pricing(params)
        decision = decide_final_price(result)

        if decision.action == "skip":
            summary["skip"] += 1
            print(f"  [{i}/{len(records)}] {item_id} ⚠️ 赤字化、要停止検討 (reason={decision.reason})")
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

        # history 更新
        history[item_id] = {
            "last_check_at": datetime.now().isoformat(),
            "source_price_eur": latest["price_eur"],
            "target_price_jpy": result.selling_price_jpy,
            "final_price_jpy": new_price,
            "current_listed_price_jpy": old_price,
        }
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

    print(f"\n💡 更新候補 ({len(differs)} 件, 閾値 ±¥{threshold:,}):")
    for item_id, old, new, d, title in differs:
        print(f"  {item_id} | {title[:35]}")
        print(f"    ¥{old:,} → ¥{new:,} ({d:+,})")
        print(f"    → https://www.buyma.com/my/sell/{item_id}/edit?tab=b")

    if dry_run:
        print("\n💡 --execute で実際の更新を試みます (現状スケルトン、手動更新推奨)")
        return

    # execute モード: 価格更新ループ (現状スケルトン)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright 未インストール、更新処理スキップ")
        return

    from buyma_auto_listing import login, load_config
    config = load_config()
    print("\n🛠 価格更新を開始...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        if not login(page, config["buyma_email"], config["buyma_password"]):
            print("❌ ログイン失敗")
            browser.close()
            return
        for item_id, _, new_price, _, _ in differs:
            if update_listing_price(page, item_id, new_price):
                print(f"  ✅ 更新: {item_id} → ¥{new_price:,}")
            else:
                print(f"  ⚠️ スケルトン未実装: {item_id}")
            time.sleep(1.0)
        browser.close()


def main():
    parser = argparse.ArgumentParser(description="出品中商品の価格追従")
    parser.add_argument("--dry-run", action="store_true", help="差分検出のみ (default)")
    parser.add_argument("--execute", action="store_true", help="BUYMA で価格を実際に更新")
    parser.add_argument("--threshold", type=int, default=3000,
                        help="更新候補とする価格差分 (円、default 3000)")
    parser.add_argument("--throttle", type=float, default=0.8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    run(dry_run=not args.execute, threshold=args.threshold, throttle=args.throttle, limit=args.limit)


if __name__ == "__main__":
    main()
