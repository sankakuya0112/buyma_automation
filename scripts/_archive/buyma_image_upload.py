"""
buyma_image_upload.py
----------------------
BUYMAの出品フォームに画像を自動アップロードするスクリプト。

【解析済みのAPI仕様】
  エンドポイント: POST https://www.buyma.com/rorapi/item_image.json
  FormDataフィールド:
    - index    : 画像の番号（0始まり）
    - image_key: 空文字でOK（既存画像の更新時に使用）
    - item_id  : 空文字でOK（新規出品時）
    - updfile  : 画像ファイル本体
  必須ヘッダー:
    - X-CSRF-TOKEN  : ページの <meta name="csrf-token"> から取得
    - X-REQUESTED-WITH: XMLHttpRequest

【動作原理】
  Playwrightでログイン→出品ページを開く→
  DataTransfer APIでファイルをセット→changeイベントを発火→
  BUYMAのJSが上記APIに自動アップロード→img_keyを取得

使い方:
    python3 scripts/buyma_image_upload.py           # 全件処理
    python3 scripts/buyma_image_upload.py --test    # 最初の1件だけテスト

必要なもの:
    pip install playwright requests
    playwright install chromium
"""

import csv
import glob
import json
import os
import sys
import time
import random
import tempfile
import requests as req_lib
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("❌ Playwright が必要です: pip install playwright && playwright install chromium")
    sys.exit(1)

# ========== パス設定 ==========
BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "reports")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

BUYMA_LOGIN_URL   = "https://www.buyma.com/login/"
BUYMA_LISTING_URL = "https://www.buyma.com/my/sell/new?tab=b"
UPLOAD_API_URL    = "https://www.buyma.com/rorapi/item_image.json"

# ========== ユーティリティ ==========

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def get_latest_csv(pattern_suffix):
    pattern = os.path.join(OUTPUT_DIR, f"*{pattern_suffix}")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None

def human_delay(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))

def download_image(url, dest_path):
    """BaseBluの画像URLを一時ファイルにダウンロード"""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    r = req_lib.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)
    return dest_path

# ========== ログイン ==========

def login(page, email, password):
    print("  🔑 ログイン中...")
    page.goto(BUYMA_LOGIN_URL, wait_until="networkidle")
    human_delay(1.0, 2.0)

    page.fill('input[type="email"], input[name="email"], #email', email)
    human_delay(0.3, 0.7)
    page.fill('input[type="password"], input[name="password"]', password)
    human_delay(0.5, 1.0)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")
    human_delay(1.5, 2.5)

    if "signin" in page.url or "login" in page.url:
        print("  ❌ ログイン失敗")
        return False
    print("  ✅ ログイン成功")
    return True

# ========== 画像アップロード ==========

def upload_image_to_listing(page, image_path, index=0):
    """
    出品ページのfile inputにDataTransferでファイルをセットし、
    BUYMAのJSにアップロードさせて img_key を受け取る。
    """

    # インターセプターを設置（アップロード結果を捕捉）
    page.evaluate("""
    window.__imgUploadResult = null;
    const origOpen  = XMLHttpRequest.prototype.open;
    const origSend  = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u, ...a) {
        this.__u = u; this.__m = m;
        return origOpen.apply(this, [m, u, ...a]);
    };
    XMLHttpRequest.prototype.send = function(body) {
        if (this.__u && this.__u.includes('item_image')) {
            this.addEventListener('load', function() {
                try { window.__imgUploadResult = JSON.parse(this.responseText); }
                catch(e) {}
            });
        }
        return origSend.apply(this, [body]);
    };
    """)

    # Playwrightの set_input_files でファイルをセット（UIを経由しないのでBot検知を回避）
    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(image_path)
    print(f"    📂 ファイルセット完了: {os.path.basename(image_path)}")

    # アップロード完了を待つ（最大15秒）
    for _ in range(30):
        result = page.evaluate("window.__imgUploadResult")
        if result:
            break
        time.sleep(0.5)

    if not result:
        print("    ⚠️  アップロードタイムアウト")
        return None

    if str(result.get("status")) != "0":
        print(f"    ❌ アップロード失敗: {result}")
        return None

    img_key = result.get("img_key", "")
    img_url = result.get("img_url", "")
    print(f"    ✅ アップロード成功 img_key={img_key[:30]}...")
    return {"img_key": img_key, "img_url": img_url}

# ========== メイン処理 ==========

def main():
    test_mode = "--test" in sys.argv

    config = load_config()
    email    = config["buyma_email"]
    password = config["buyma_password"]

    # 利益商品CSVを読み込む
    csv_path = get_latest_csv("_baseblu_profitable_products.csv")
    if not csv_path:
        print("❌ 利益商品CSVが見つかりません。先に filter_baseblu_profitable.py を実行してください。")
        sys.exit(1)

    products = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        products = list(csv.DictReader(f))

    if test_mode:
        products = products[:1]
        print(f"🧪 テストモード: {len(products)} 件")
    else:
        print(f"📦 処理対象: {len(products)} 件")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()

        if not login(page, email, password):
            browser.close()
            sys.exit(1)

        for i, product in enumerate(products, 1):
            title     = product.get("title", "")
            image_url = product.get("image_url", "")

            print(f"\n[{i}/{len(products)}] {title[:50]}")

            if not image_url:
                print("  ⚠️  image_url が空のためスキップ")
                results.append({**product, "upload_status": "skipped_no_url", "img_key": ""})
                continue

            # 出品ページを開く（毎回新しく開く）
            try:
                page.goto(BUYMA_LISTING_URL, wait_until="networkidle", timeout=30000)
                human_delay(2.0, 3.5)
            except PWTimeout:
                print("  ⚠️  ページ読み込みタイムアウト")
                results.append({**product, "upload_status": "page_timeout", "img_key": ""})
                continue

            # 画像をダウンロード
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                download_image(image_url, tmp_path)
                print(f"  ⬇️  画像DL完了: {os.path.getsize(tmp_path):,} bytes")
            except Exception as e:
                print(f"  ❌ 画像DL失敗: {e}")
                results.append({**product, "upload_status": "download_failed", "img_key": ""})
                os.unlink(tmp_path)
                continue

            # アップロード実行
            upload_result = upload_image_to_listing(page, tmp_path, index=0)
            os.unlink(tmp_path)

            if upload_result:
                results.append({
                    **product,
                    "upload_status": "success",
                    "img_key": upload_result["img_key"],
                    "uploaded_img_url": upload_result["img_url"],
                    "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            else:
                results.append({**product, "upload_status": "upload_failed", "img_key": ""})

            # 次の商品まで待機
            if i < len(products):
                wait = random.uniform(6, 12)
                print(f"  ⏳ {wait:.1f}秒 待機...")
                time.sleep(wait)

        browser.close()

    # 結果CSV保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(OUTPUT_DIR, f"{date_str}_buyma_image_upload_results.csv")

    base_fields = list(products[0].keys()) if products else []
    extra_fields = ["upload_status", "img_key", "uploaded_img_url", "uploaded_at"]
    all_fields = base_fields + [f for f in extra_fields if f not in base_fields]

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    success = sum(1 for r in results if r.get("upload_status") == "success")
    print(f"\n{'='*50}")
    print(f"✅ 完了！  成功: {success}/{len(results)} 件")
    print(f"📄 結果: {out_path}")


if __name__ == "__main__":
    main()
