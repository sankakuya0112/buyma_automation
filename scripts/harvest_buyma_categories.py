"""
harvest_buyma_categories.py — BUYMA 出品フォームの実カテゴリツリーを採取する (Mac 専用)

方針: 実績のある B.set_category() を sentinel ラベルで呼び、その「候補なし」
診断 dump (set_category 内 line ~851) を stdout に吐かせて採取する。
  Pass A: [レディースファッション, ☆DUMP☆, z] → 第2階層の正式名一覧
  Pass B: [レディースファッション, ボトムス, ☆DUMP☆] → ボトムス配下の第3階層

使い方: /usr/bin/python3 scripts/harvest_buyma_categories.py
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import buyma_auto_listing as B
from playwright.sync_api import sync_playwright

SENT = "☆DUMP☆"  # 実在しないラベル → set_category が候補一覧を print する
OPTION_UNION = ", ".join((
    ".Select-menu-outer .Select-option", ".Select-menu .Select-option",
    ".Select--menu-outer .Select-option", "[role=\"listbox\"] [role=\"option\"]",
    ".bmm-c-select__option", ".bmm-c-select-menu__option",
))


def open_form(page):
    page.goto(B.BUYMA_LISTING_URL, wait_until="networkidle", timeout=30000)
    B._scroll_through_page(page)
    time.sleep(1.0)


def dump_select(page, idx):
    """category .Select[idx] を開いて全 option を読む (set_category 選択後の tier-3 採取用)。"""
    page.evaluate(f"""(function(){{
        var sels=document.querySelectorAll('.Select, .bmm-c-select');
        if(!sels[{idx}]) return;
        var ctrl=sels[{idx}].querySelector('.Select-control, .bmm-c-select__control')||sels[{idx}];
        ctrl.dispatchEvent(new MouseEvent('mousedown',{{bubbles:true}})); ctrl.click();
    }})()""")
    for _ in range(25):
        time.sleep(0.12)
        if page.evaluate(f"(function(){{return document.querySelectorAll({json.dumps(OPTION_UNION)}).length>0;}})()"):
            break
    vals = page.evaluate(f"""(function(){{
        var sels=document.querySelectorAll('.Select, .bmm-c-select');var root=sels[{idx}];
        var scoped=root?root.querySelectorAll({json.dumps(OPTION_UNION)}):[];
        var opts=scoped.length?scoped:document.querySelectorAll({json.dumps(OPTION_UNION)});
        var out=[];for(var i=0;i<opts.length;i++){{var t=(opts[i].textContent||'').trim();if(t)out.push(t);}}
        return out;}})()""")
    try: page.locator('body').click(timeout=1000)
    except Exception: pass
    return vals or []


def main():
    config = B.load_config()
    os.makedirs(B.STATE_DIR, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--no-sandbox", "--window-size=1400,900"])
        kw = dict(viewport=None, locale="ja-JP", timezone_id="Asia/Tokyo",
                  user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        if os.path.exists(B.STORAGE_STATE_PATH):
            kw["storage_state"] = B.STORAGE_STATE_PATH
        ctx = browser.new_context(**kw); page = ctx.new_page()
        if not B.login(page, config["buyma_email"], config["buyma_password"]):
            print("❌ login 失敗"); browser.close(); sys.exit(1)
        try: ctx.storage_state(path=B.STORAGE_STATE_PATH)
        except Exception: pass

        for parent in ("ワンピース・オールインワン", "財布・小物", "ファッション雑貨・小物", "バッグ・カバン"):
            print(f"\n################ 第3階層 ({parent} 配下) ################")
            open_form(page)
            # set_category で tier1=レディース, tier2=parent を選択 (tier3 は その他 に fallback)
            B.set_category(page, ["レディースファッション", parent, SENT])
            time.sleep(0.8)
            t3 = dump_select(page, 2)
            print(f"=== 第3階層 [{parent}] ({len(t3)}件) ===")
            for i, v in enumerate(t3):
                print(f"  {i:2}. {v}")

        print("\n✅ 採取完了")
        browser.close()


if __name__ == "__main__":
    main()
