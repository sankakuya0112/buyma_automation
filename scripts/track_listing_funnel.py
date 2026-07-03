"""
track_listing_funnel.py  (Mac 専用 — buyma.com へのアクセスが必要)
------------------------
自社出品のファネル実測: BUYMA 出品リストから商品ごとの
アクセス数 / ほしいもの数 / (取れれば) カート数 / ステータス を採取し、
data/funnel_history.json にスナップショットとして追記する。

これが closed-loop の観測レイヤ。成約 (遅い) を待たずに
「見られているか (露出)」「欲しがられているか (関心)」の先行指標が
2〜3 日おきに貯まり、decision_gate.py が消費する。

使い方 (Mac):
    python3 scripts/track_listing_funnel.py                # 採取 + 差分表示
    python3 scripts/track_listing_funnel.py --debug-html   # 初回: DOM ダンプ採取
    python3 scripts/track_listing_funnel.py --max-pages 3

⚠️ 初回実走の注意 (update_listed_prices と同じ運用):
    出品リストの実 DOM は未確認のため、初回は --debug-html で
    /tmp/buyma_funnel_debug.html を保存し、抽出件数が実際の出品数と
    合っているかを確認する。合わなければダンプをチャットに貼れば
    app/core/funnel.py の正規表現を 1 ターンで調整できる。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import funnel  # noqa: E402

HISTORY_PATH = PROJECT_ROOT / "data" / "funnel_history.json"
SELL_LIST_URL = "https://www.buyma.com/my/sell/"
DEBUG_HTML_PATH = "/tmp/buyma_funnel_debug.html"


def load_history() -> dict:
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def collect_pages(page, max_pages: int, debug_html: bool) -> list[dict]:
    """出品リストをページ送りしながら全出品を採取する。"""
    all_items: list[dict] = []
    seen_ids: set[str] = set()
    for page_no in range(1, max_pages + 1):
        url = SELL_LIST_URL if page_no == 1 else f"{SELL_LIST_URL}?page={page_no}"
        print(f"📄 取得: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # lazy render 対策 (CLAUDE.md §1): 実ホイールで全行を描画させる
        for _ in range(8):
            page.mouse.wheel(0, 600)
            time.sleep(0.25)
        html = page.content()

        if debug_html and page_no == 1:
            with open(DEBUG_HTML_PATH, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"🔬 [DUMP-ファネル] {DEBUG_HTML_PATH} に保存 "
                  "(抽出が合わなければこれをチャットへ)")

        items = funnel.extract_seller_items(html)
        new_items = [it for it in items if it["item_id"] not in seen_ids]
        if not new_items:
            print(f"   → 新規 0 件、ページ送り終了")
            break
        for it in new_items:
            seen_ids.add(it["item_id"])
        all_items.extend(new_items)
        print(f"   → {len(new_items)} 件 (累計 {len(all_items)})")
    return all_items


def print_report(history: dict, snapshot: dict) -> None:
    snaps = history.get("snapshots", [])
    prev = snaps[-1] if snaps else None
    diff = funnel.diff_snapshots(prev, snapshot)
    t = diff["totals"]
    print("\n📊 ファネル実測サマリ")
    print(f"   出品数: {len(snapshot['items'])} / 累計アクセス {t['access']:,}"
          f" (Δ{t['d_access']:+,}) / ほしいもの {t['wish']:,} (Δ{t['d_wish']:+,})")
    if t["new_sold"] > 0:
        print(f"   🎉 新規成約検出: {t['new_sold']} 件 — decision_gate.py を実行してください")
    movers = sorted(diff["per_item"], key=lambda x: -(x["d_access"] + x["d_wish"] * 10))
    if movers:
        print("   動きのある出品 (上位 5):")
        for m in movers[:5]:
            print(f"     {m['item_id']} {m['title'][:32]:<32} "
                  f"access {m['access']:>4} ({m['d_access']:+}) "
                  f"wish {m['wish']:>3} ({m['d_wish']:+}) {m['status']}")


def run(max_pages: int, debug_html: bool, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright 未インストール (pip3 install playwright)")
        sys.exit(1)

    from buyma_auto_listing import load_config, login  # Mac 上で解決

    config = load_config()
    with sync_playwright() as pw:
        launch_kwargs = {"headless": headless}
        exe = config.get("chromium_executable_path")
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**launch_kwargs)
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
            sys.exit(1)

        items = collect_pages(page, max_pages, debug_html)
        browser.close()

    if not items:
        print("⚠️ 出品が 1 件も抽出できませんでした。")
        print("   --debug-html で DOM を採取し、チャットに貼ってください "
              "(funnel.py の抽出パターンを調整します)")
        sys.exit(1)

    snapshot = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    history = load_history()
    print_report(history, snapshot)
    history["snapshots"].append(snapshot)
    save_history(history)
    print(f"\n💾 スナップショット追記: {HISTORY_PATH} "
          f"(累計 {len(history['snapshots'])} 回)")
    print("次: python3 scripts/decision_gate.py で判定")


def main() -> None:
    parser = argparse.ArgumentParser(description="自社出品ファネルの実測採取")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--debug-html", action="store_true",
                        help=f"1 ページ目の HTML を {DEBUG_HTML_PATH} に保存")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    run(max_pages=args.max_pages, debug_html=args.debug_html, headless=args.headless)


if __name__ == "__main__":
    main()
