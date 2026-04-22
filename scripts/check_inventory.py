"""
check_inventory.py
-------------------
出品中の商品について baseblu 側の在庫を確認し、売り切れ商品を BUYMA で
出品停止にするためのフレームワーク。

Phase 2-2: BUYMA のキャンセル率は評価に直結するため、仕入れ元が売り切れた
商品を放置すると致命的。定期実行 (cron など) で検査 + 停止 する前提。

使い方:
    # ドライラン: 売切検出のみ、停止は実行しない
    python3 scripts/check_inventory.py --dry-run

    # 実際に BUYMA 停止まで行う
    python3 scripts/check_inventory.py --execute

    # Mac 上で定期実行する場合 (launchd / cron)
    0 */6 * * * cd ~/buyma_automation && python3 scripts/check_inventory.py --execute >> logs/inventory.log

データソース:
    出品記録 CSV: outputs/reports/*_auto_listing_results.csv
    (buyma_auto_listing.py の実行結果。item_id + product_url が残っている)

    商品ページ URL からハンドルを抽出し、baseblu JSON API で
    availability を確認する。

状態管理:
    data/inventory_status.json
    {
      "<buyma_item_id>": {
        "url": "https://www.baseblu.com/...",
        "last_check_at": "2026-04-22T..."
        "status": "in_stock" | "sold_out" | "stopped",
        "stopped_at": "..."
      }
    }

実装状態:
    - baseblu 在庫チェックは実装済み (Shopify API の /products/{handle}.json)
    - BUYMA 出品停止は現状 **スケルトン** (ログイン + 停止 UI 操作は TODO)
      初回運用では --dry-run で検出のみ → 手動停止 を推奨
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
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

STATUS_PATH = PROJECT_ROOT / "data" / "inventory_status.json"
RESULTS_GLOB = PROJECT_ROOT / "outputs" / "reports" / "*_auto_listing_results.csv"
BASEBLU_DETAIL_API = "https://www.baseblu.com/en-us/products/{handle}.json"


def load_status() -> dict:
    if STATUS_PATH.exists():
        try:
            return json.load(open(STATUS_PATH, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_status(data: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_all_listing_results() -> list[dict]:
    """過去の自動出品結果 CSV を全部マージして返す。"""
    all_rows = []
    for path in sorted(glob.glob(str(RESULTS_GLOB))):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("status") not in ("draft", "published"):
                    continue
                if not row.get("item_id"):
                    continue
                all_rows.append(row)
    return all_rows


def extract_handle(url: str) -> Optional[str]:
    """baseblu 商品 URL からハンドル (末尾 slug) を抽出。"""
    if not url:
        return None
    m = re.search(r"/products/([^/?#]+)", url)
    return m.group(1) if m else None


def check_baseblu_stock(handle: str) -> dict:
    """baseblu (Shopify) の個別商品 JSON で在庫を確認する。

    戻り値:
        {"available": bool, "available_sizes": [...], "raw": <dict>}
    """
    import requests
    url = BASEBLU_DETAIL_API.format(handle=handle)
    try:
        resp = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("product", {})
    except Exception as e:
        return {"error": str(e), "available": None, "available_sizes": []}

    variants = data.get("variants", []) or []
    available_sizes = [
        v.get("option1") for v in variants if v.get("available")
    ]
    any_available = bool(available_sizes)
    return {
        "available": any_available,
        "available_sizes": available_sizes,
        "variants_total": len(variants),
    }


def stop_buyma_listing(page, item_id: str) -> bool:
    """BUYMA で出品を停止する (スケルトン実装)。

    TODO: 実装
        - /my/sell/{item_id}/edit?tab=b に遷移
        - 「出品停止」または「この商品を削除」ボタンを特定
        - クリック → 確認モーダル → 停止確定

    実際の UI セレクタは BUYMA 管理画面を見て要調整。初期運用では
    --dry-run で sold_out の item_id を列挙 → ユーザが手動停止が安全。
    """
    # 現時点では未実装。False を返して「停止できなかった」扱いにする
    return False


def run(execute: bool, throttle_sec: float = 1.0, limit: Optional[int] = None):
    print("=" * 50)
    print(f"📦 在庫チェック {'(実行モード)' if execute else '(ドライラン)'}")
    print("=" * 50)

    results = load_all_listing_results()
    if not results:
        print("⚠️ 過去の出品記録 CSV が見つかりません。")
        return

    # item_id でユニーク化 (最新 CSV の status を優先)
    unique = {}
    for r in results:
        unique[r["item_id"]] = r
    listings = list(unique.values())
    if limit:
        listings = listings[:limit]
    print(f"  対象: {len(listings)} 件")

    status = load_status()
    summary = {"in_stock": 0, "sold_out": 0, "already_stopped": 0, "error": 0}
    sold_out_items = []

    for i, r in enumerate(listings, 1):
        item_id = r["item_id"]
        url = r.get("product_url") or ""
        handle = extract_handle(url)
        if not handle:
            summary["error"] += 1
            continue

        rec = status.get(item_id, {"url": url, "status": "in_stock"})
        if rec.get("status") == "stopped":
            summary["already_stopped"] += 1
            continue

        check = check_baseblu_stock(handle)
        now = datetime.now().isoformat()
        if check.get("available") is True:
            rec.update({"status": "in_stock", "last_check_at": now})
            summary["in_stock"] += 1
            print(f"  [{i}/{len(listings)}] {item_id} ✅ 在庫あり (sizes={check['available_sizes']})")
        elif check.get("available") is False:
            rec.update({"status": "sold_out", "last_check_at": now})
            summary["sold_out"] += 1
            sold_out_items.append((item_id, r.get("title"), url))
            print(f"  [{i}/{len(listings)}] {item_id} ⚠️ 売切 ({r.get('title','')[:30]})")
        else:
            summary["error"] += 1
            err = check.get("error", "unknown")
            print(f"  [{i}/{len(listings)}] {item_id} ❌ エラー: {err}")

        status[item_id] = rec
        time.sleep(throttle_sec)

    save_status(status)

    print()
    print("=" * 50)
    print("📊 集計")
    print("=" * 50)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not sold_out_items:
        print("\n🎉 売切はありません")
        return

    print(f"\n⚠️ 要停止リスト ({len(sold_out_items)} 件):")
    for item_id, title, url in sold_out_items:
        print(f"  - {item_id} | {title[:40]}")
        print(f"    → https://www.buyma.com/my/sell/{item_id}/edit?tab=b")

    if not execute:
        print("\n💡 --execute で実際の出品停止を試みます (現状はスケルトン、手動停止推奨)")
        return

    # 実行モード: BUYMA ログイン + 停止ループ
    print("\n🛑 停止処理を開始...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright 未インストール。停止処理はスキップ")
        return

    # 既存の login 関数を流用
    from buyma_auto_listing import login, load_config
    config = load_config()
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
        for item_id, title, _ in sold_out_items:
            ok = stop_buyma_listing(page, item_id)
            if ok:
                status[item_id]["status"] = "stopped"
                status[item_id]["stopped_at"] = datetime.now().isoformat()
                print(f"  ✅ 停止: {item_id}")
            else:
                print(f"  ⚠️ 未実装のため未処理: {item_id}")
            time.sleep(1.0)
        browser.close()
    save_status(status)


def main():
    parser = argparse.ArgumentParser(description="baseblu 在庫確認 + BUYMA 出品停止")
    parser.add_argument("--dry-run", action="store_true", help="検出のみ、停止しない (default)")
    parser.add_argument("--execute", action="store_true", help="実際に BUYMA で停止する (現状スケルトン)")
    parser.add_argument("--throttle", type=float, default=1.0, help="API 呼び出し間隔 (秒)")
    parser.add_argument("--limit", type=int, help="処理件数上限 (デバッグ用)")
    args = parser.parse_args()

    execute = bool(args.execute and not args.dry_run)
    run(execute=execute, throttle_sec=args.throttle, limit=args.limit)


if __name__ == "__main__":
    main()
