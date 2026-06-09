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


EDIT_URL = "https://www.buyma.com/my/sell/{item_id}/edit?tab=b"


def _dump_stop_page_state(page, item_id: str) -> None:
    """編集ページの停止/取り下げ候補ボタンをダンプ。

    Mac 実走の初回ログから「停止ボタンのテキスト」「ラジオ/トグルの位置」を
    確定するためのもの。`set_region` の `_dump_section_elements` と同じ思想で、
    DOM 構造を一度知れば本体の処理を最終調整できる。
    """
    info = page.evaluate("""(function(){
        function visible(el){
            if (!el) return false;
            var r = el.getBoundingClientRect();
            var s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0
                && s.display !== 'none' && s.visibility !== 'hidden';
        }
        var keywords = ['停止', '取り下げ', '削除', '公開停止', '出品停止'];
        var candidates = [];
        document.querySelectorAll('button, a, label, input[type=radio]').forEach(function(el){
            if (!visible(el)) return;
            var t = (el.textContent || el.value || '').trim();
            if (!t) return;
            if (keywords.some(function(k){return t.indexOf(k) !== -1})) {
                candidates.push({
                    tag: el.tagName,
                    text: t.slice(0, 40),
                    cls: (el.className || '').slice(0, 60)
                });
            }
        });
        return {url: location.href, candidates: candidates.slice(0, 20)};
    })()""")
    print(f"    🔬 [DUMP-停止] item={item_id}")
    print(f"       url={info.get('url', '?')}")
    if not info.get("candidates"):
        print(f"       (停止/取下げ系の visible 要素なし — 別 URL の可能性)")
    for c in info.get("candidates", []):
        print(f"       {c['tag']}: '{c['text']}'  cls={c['cls']!r}")


def stop_buyma_listing(page, item_id: str, dump: bool = True) -> bool:
    """BUYMA で出品を停止する。

    フロー:
        1. 編集ページに遷移
        2. lazy render 解除のためスクロール
        3. (初回 dump=True) 停止候補要素を診断ダンプ
        4. 「出品停止」ボタン / ラジオを Playwright native click
        5. 「更新する」「保存する」「下書き保存する」のいずれかをクリック
        6. 確認モーダル ("はい"/"OK") 突破
        7. URL 変化または toast で成否判定

    BUYMA 編集画面は「販売中 / 停止 / 取り下げ」のラジオ + 保存ボタンの構造
    が定説。初回 Mac 実走で正確なテキスト/構造を dump → 必要なら微調整。
    """
    try:
        page.goto(EDIT_URL.format(item_id=item_id), wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"    ❌ 編集ページ遷移失敗: {e}")
        return False

    time.sleep(1.0)
    # lazy render 解除
    try:
        for _ in range(8):
            page.mouse.wheel(0, 500)
            time.sleep(0.15)
        page.mouse.wheel(0, -8 * 500)
    except Exception:
        pass

    if dump:
        try:
            _dump_stop_page_state(page, item_id)
        except Exception as e:
            print(f"    ⚠️ dump 失敗: {e}")

    # 1) 停止系ラジオ/ボタンを順次クリック (Playwright native)
    stop_labels = ["出品停止", "停止する", "公開停止", "停止"]
    clicked_stop = None
    for label in stop_labels:
        # まず label/button タグを優先
        for selector in [f'label:has-text("{label}")', f'button:has-text("{label}")']:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1500):
                    try:
                        el.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    el.click(timeout=3000)
                    clicked_stop = label
                    break
            except Exception:
                continue
        if clicked_stop:
            break

    if not clicked_stop:
        print(f"    ⚠️ 停止系要素が見つからない (試行: {stop_labels})")
        return False

    time.sleep(0.5)

    # 2) 保存系ボタン
    save_labels = ["更新する", "変更を保存", "保存する", "下書き保存する"]
    clicked_save = None
    for label in save_labels:
        try:
            btn = page.locator(f'button:has-text("{label}")').first
            if btn.is_visible(timeout=1500):
                try:
                    btn.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass
                btn.click(timeout=4000)
                clicked_save = label
                break
        except Exception:
            continue

    if not clicked_save:
        print(f"    ⚠️ 保存ボタンが見つからない (試行: {save_labels})")
        return False

    # 3) 確認モーダル突破
    for modal_text in ["保存する", "更新する", "はい", "OK", "停止する"]:
        try:
            modal_btn = page.locator(f'button:has-text("{modal_text}")').nth(1)
            if modal_btn.is_visible(timeout=1000):
                modal_btn.click(timeout=2000)
                break
        except Exception:
            continue

    # 4) URL 変化 or toast で成否判定
    url_before = page.url
    for _ in range(20):
        time.sleep(0.5)
        if page.url != url_before:
            print(f"    ✅ 停止: {item_id} ({clicked_stop} + {clicked_save})")
            return True
        try:
            ok = page.locator('text=保存しました').first.is_visible(timeout=500)
            if ok:
                print(f"    ✅ 停止: {item_id} ({clicked_stop} + {clicked_save}, toast)")
                return True
        except Exception:
            continue

    print(f"    ⚠️ 停止応答未確認: {item_id} ({clicked_stop} + {clicked_save} 後 10s)")
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
