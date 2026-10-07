"""
check_inventory.py
-------------------
出品済み商品について **仕入先ごと・出品したサイズごと** に在庫を確認し、
売切れ (全サイズ / 一部サイズ) を一覧にする。

BUYMA のキャンセル率は評価に直結するため、仕入先で売り切れた商品を放置しないこと。
BUYMA 側の停止・在庫変更は **本人が行う** (ブラウザ自動操作による停止は 2026-10 に廃止):
  - 1 件ずつなら BUYMA の出品リストで停止
  - まとめてなら一括出品編集 (colorsizes.csv の在庫ステータス=0) を本人がアップロード
    (一括出品編集の権限があるアカウントのみ)

使い方:
    python3 scripts/check_inventory.py            # 確認だけ (BUYMA には触れない)
    python3 scripts/check_inventory.py --limit 5

データソース:
    出品記録 CSV: outputs/reports/*_auto_listing_results.csv
    (item_id / product_url / source_name / listed_sizes が残っている)
    仕入先: product_url の Shopify 公開商品データ (/products/<handle>.js)。
    source_name 列が空なら URL のホスト名から仕入先を推定、不明なら確認しない。

状態管理:
    data/inventory_status.json
    {"<buyma_item_id>": {"url": ..., "source_name": ..., "status": "in_stock" | "partial" | "sold_out",
                         "missing_listed_sizes": [...], "last_check_at": ...}}
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.supplier_stock import (  # noqa: E402
    evaluate_stock,
    fetch_product_snapshot,
    known_source_hosts,
    resolve_record_source,
)

STATUS_PATH = PROJECT_ROOT / "data" / "inventory_status.json"
RESULTS_GLOB = PROJECT_ROOT / "outputs" / "reports" / "*_auto_listing_results.csv"


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
    """過去の自動出品結果 CSV を全部マージして返す。

    仕入先 URL (product_url) からハンドルを取れない行は在庫確認できないので除外し、
    件数だけ 1 回表示する (2026-09-24 以前の旧形式 CSV には product_url 列が無い)。
    """
    all_rows = []
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
                all_rows.append(row)
    if legacy:
        print(f"ℹ️ 仕入先 URL の無い旧形式の出品記録 {legacy} 件は対象外 (product_url 列が無い CSV)")
    return all_rows


def extract_handle(url: str) -> Optional[str]:
    """baseblu 商品 URL からハンドル (末尾 slug) を抽出。"""
    if not url:
        return None
    m = re.search(r"/products/([^/?#]+)", url)
    return m.group(1) if m else None


def run(throttle_sec: float = 1.0, limit: Optional[int] = None) -> dict:
    print("=" * 50)
    print("📦 在庫チェック (仕入先の公開データを読むだけ。BUYMA には触れません)")
    print("=" * 50)

    results = load_all_listing_results()
    if not results:
        print("⚠️ 過去の出品記録 CSV が見つかりません。")
        return {}

    # item_id でユニーク化 (新しい CSV の行を優先)
    unique = {}
    for r in results:
        unique[r["item_id"]] = r
    listings = list(unique.values())
    if limit:
        listings = listings[:limit]
    print(f"  対象: {len(listings)} 件")

    hosts = known_source_hosts()
    status = load_status()
    summary = {"in_stock": 0, "partial": 0, "sold_out": 0, "unknown_source": 0, "error": 0}
    action_items = []

    for i, r in enumerate(listings, 1):
        item_id = r["item_id"]
        url = r.get("product_url") or ""
        source_name = resolve_record_source(r, hosts)
        if not source_name:
            summary["unknown_source"] += 1
            print(f"  [{i}/{len(listings)}] {item_id} ❓ 仕入先が分からないため未確認 ({url[:60]})")
            continue

        snap = fetch_product_snapshot(url)
        check = evaluate_stock(snap, r.get("listed_sizes") or "", r.get("listed_color") or "")
        now = datetime.now().isoformat(timespec="seconds")
        rec = status.get(item_id, {})
        rec.update({
            "url": url, "source_name": source_name, "status": check["status"],
            "available_sizes": check.get("available_sizes", []),
            "missing_listed_sizes": check.get("missing_listed_sizes", []),
            "last_check_at": now,
        })
        st = check["status"]
        summary[st if st in summary else "error"] += 1
        label = {"in_stock": "✅ 在庫あり", "partial": "⚠️ 一部サイズ売切",
                 "sold_out": "⛔ 売切", "error": "❌ エラー"}.get(st, st)
        extra = ""
        if st == "partial":
            extra = f" 売切サイズ={check['missing_listed_sizes']}"
        elif st == "error":
            extra = f" {check.get('error', '')[:80]}"
        print(f"  [{i}/{len(listings)}] {item_id} [{source_name}] {label}{extra}")
        if st in ("partial", "sold_out"):
            action_items.append((item_id, r.get("title", ""), st, check.get("missing_listed_sizes", [])))
        status[item_id] = rec
        time.sleep(throttle_sec)

    save_status(status)

    print()
    print("=" * 50)
    print("📊 集計")
    print("=" * 50)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not action_items:
        print("\n🎉 対応が必要な商品はありません")
        return summary

    print(f"\n⚠️ BUYMA で本人が対応する商品 ({len(action_items)} 件):")
    for item_id, title, st, missing in action_items:
        what = "出品停止" if st == "sold_out" else f"サイズ {', '.join(missing)} を在庫なしに"
        print(f"  - {item_id} | {title[:40]} → {what}")
        print(f"    https://www.buyma.com/my/sell/{item_id}/edit?tab=b")
    return summary


def main(argv=None):
    from app.utils.env import load_project_env
    load_project_env()   # .env の為替・手数料・ガード設定を計算前に反映 (シェルの値が優先)
    parser = argparse.ArgumentParser(description="仕入先の在庫確認 (BUYMA 側の操作は本人が行う)")
    parser.add_argument("--dry-run", action="store_true", help="(互換用。常に確認のみ)")
    parser.add_argument("--execute", action="store_true",
                        help="廃止: BUYMA の自動停止は行いません")
    parser.add_argument("--throttle", type=float, default=1.0, help="問い合わせ間隔 (秒)")
    parser.add_argument("--limit", type=int, help="処理件数上限 (デバッグ用)")
    args = parser.parse_args(argv)

    if args.execute:
        from app.utils.automation_guard import refuse_buyma_write
        refuse_buyma_write("BUYMA の出品停止 (check_inventory --execute)")
    run(throttle_sec=args.throttle, limit=args.limit)


if __name__ == "__main__":
    main()
