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

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))

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


EDIT_URL = "https://www.buyma.com/my/sell/{item_id}/edit?tab=b"


def _dump_edit_page_state(page, item_id: str, context: str) -> None:
    """編集ページの主要要素を診断ダンプする。

    Mac 実走の初回ログから「保存ボタンのテキスト」「価格 input の位置」を
    確定するために使う。set_region の `_dump_section_elements` と同じ思想。
    """
    info = page.evaluate("""(function(){
        function visible(el){
            if (!el) return false;
            var r = el.getBoundingClientRect();
            var s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0
                && s.display !== 'none' && s.visibility !== 'hidden';
        }
        var btns = Array.from(document.querySelectorAll('button'))
            .filter(visible)
            .map(function(b){
                return {
                    text: (b.textContent || '').trim().slice(0, 30),
                    disabled: b.disabled,
                    cls: b.className.slice(0, 60)
                };
            })
            .slice(0, 30);
        var priceInputs = [];
        document.querySelectorAll('input').forEach(function(el){
            if (el.type !== 'text' || !visible(el)) return;
            var anc = el;
            var path = '';
            for (var d = 0; d < 6; d++) {
                if (!anc.parentElement) break;
                anc = anc.parentElement;
                var t = (anc.textContent || '');
                if (t.includes('商品価格') || t.includes('販売価格') || t.includes('価格')) {
                    path = t.slice(0, 80);
                    break;
                }
            }
            if (path) priceInputs.push({value: el.value, placeholder: el.placeholder, near: path});
        });
        return {url: location.href, buttons: btns, priceInputs: priceInputs.slice(0, 5)};
    })()""")
    print(f"    🔬 [DUMP-{context}] item={item_id}")
    print(f"       url={info.get('url', '?')}")
    for b in info.get("buttons", []):
        print(f"       btn: '{b['text']}' disabled={b['disabled']}")
    for p in info.get("priceInputs", []):
        print(f"       price-input: value={p['value']!r} placeholder={p['placeholder']!r} near={p['near']!r}")


def update_listing_price(page, item_id: str, new_price: int, dump: bool = True) -> bool:
    """BUYMA 編集ページで販売価格を更新する。

    フロー:
        1. /my/sell/{item_id}/edit?tab=b に遷移
        2. ページ全体スクロールで lazy render を解除
        3. (初回 dump=True 時) 編集ページのボタン/価格 input を診断ダンプ
        4. 商品価格 input を 6 階層 ancestor 探索で特定 → 新価格を __si() でセット
        5. 「更新する」「保存する」「下書き保存する」のいずれかを Playwright native click
        6. 確認モーダル ("はい"/"OK"/"保存する") があれば突破
        7. 完了画面 or URL 変化で成否判定

    diagnostic dump は Mac 実走の初回でセレクタを確定する目的。確定後は dump=False
    で運用しても良いが、診断目的で常時 ON でも問題ない (1 商品あたり 50ms 程度)。
    """
    try:
        page.goto(EDIT_URL.format(item_id=item_id), wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"    ❌ 編集ページ遷移失敗: {e}")
        return False

    time.sleep(1.0)
    # 既存パターンに合わせて lazy render を解除
    try:
        for _ in range(8):
            page.mouse.wheel(0, 500)
            time.sleep(0.15)
        page.mouse.wheel(0, -8 * 500)
    except Exception:
        pass

    if dump:
        try:
            _dump_edit_page_state(page, item_id, "編集ページ")
        except Exception as e:
            print(f"    ⚠️ dump 失敗: {e}")

    # 1) 商品価格 input をセット (buyma_auto_listing.set_price と同じ ancestor 探索)
    set_result = page.evaluate(f"""(function(){{
        var inputs = document.querySelectorAll('input');
        for (var i = 0; i < inputs.length; i++) {{
            var el = inputs[i];
            if (el.type !== 'text') continue;
            var a = el;
            for (var d = 0; d < 6; d++) {{
                if (!a.parentElement) break;
                a = a.parentElement;
                if (a.textContent && (a.textContent.includes('商品価格')
                                       || a.textContent.includes('販売価格'))) {{
                    if (typeof window.__si === 'function') {{
                        window.__si(el, {json.dumps(str(int(new_price)))});
                    }} else {{
                        // フォールバック: native setter + input イベント
                        var setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, {json.dumps(str(int(new_price)))});
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                    return 'set';
                }}
            }}
        }}
        return 'not_found';
    }})()""")
    if set_result != "set":
        print(f"    ❌ 価格 input が見つからない (result={set_result})")
        return False

    # 2) 保存系ボタンを順次試す
    save_button_texts = ["更新する", "変更を保存", "保存する", "下書き保存する"]
    clicked_label = None
    for label in save_button_texts:
        btn = page.locator(f'button:has-text("{label}")').first
        try:
            if btn.is_visible(timeout=1500):
                try:
                    btn.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass
                btn.click(timeout=4000)
                clicked_label = label
                break
        except Exception:
            continue

    if not clicked_label:
        print(f"    ❌ 保存ボタンが見つからない (試行: {save_button_texts})")
        return False

    # 3) 確認モーダル突破
    for modal_text in ["保存する", "更新する", "はい", "OK"]:
        try:
            modal_btn = page.locator(f'button:has-text("{modal_text}")').nth(1)
            if modal_btn.is_visible(timeout=1000):
                modal_btn.click(timeout=2000)
                break
        except Exception:
            continue

    # 4) URL 変化 or トースト/完了表示で成否判定
    url_before = page.url
    for _ in range(20):
        time.sleep(0.5)
        if page.url != url_before:
            print(f"    ✅ 価格更新: ¥{new_price:,} ({clicked_label} → {page.url})")
            return True
        # 同一 URL のまま成功するパターン (toast 表示) を考慮
        try:
            ok = page.locator('text=保存しました').first.is_visible(timeout=500)
            if ok:
                print(f"    ✅ 価格更新: ¥{new_price:,} ({clicked_label}, toast)")
                return True
        except Exception:
            continue

    print(f"    ⚠️ 価格更新の応答未確認 ({clicked_label} クリック後 10s 経過)")
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
