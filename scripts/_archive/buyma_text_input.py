"""
buyma_text_input.py
--------------------
BUYMAの出品フォームに商品名・価格・説明文を自動入力するスクリプト。
※ 画像アップロードは手動で後から追加する想定でスキップします。

必要なもの:
    pip install playwright
    playwright install chromium

config.json に BUYMA のログイン情報を設定してから実行してください。
    {
        "buyma_email": "your@email.com",
        "buyma_password": "yourpassword"
    }

使い方:
    python3 scripts/buyma_text_input.py

    # 1件だけテスト実行する場合:
    python3 scripts/buyma_text_input.py --test

出力:
    outputs/reports/YYYY-MM-DD_buyma_listing_results.csv  （処理結果ログ）
"""

import csv
import glob
import json
import os
import random
import sys
import time
from datetime import datetime

# --- playwright のインポート確認 ---
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("❌ Playwright がインストールされていません。")
    print("   以下のコマンドでインストールしてください：")
    print("   pip install playwright")
    print("   playwright install chromium")
    sys.exit(1)

# ========== パス設定 ==========
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs", "reports")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ========== BUYMA URL ==========
BUYMA_LOGIN_URL = "https://www.buyma.com/buyer/signin/"
BUYMA_NEW_ITEM_URL = "https://www.buyma.com/my/sell/item_add.page"


def load_config():
    """config.json からログイン情報を読み込む"""
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ config.json が見つかりません: {CONFIG_PATH}")
        print("   config.json.template をコピーして作成してください。")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_latest_profitable_csv():
    """最新の profitable_products CSV を返す"""
    pattern = os.path.join(OUTPUT_DIR, "*_baseblu_profitable_products.csv")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def load_products(csv_path):
    """CSV から商品リストを読み込む"""
    products = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(row)
    return products


def human_delay(min_sec=0.5, max_sec=1.8):
    """人間らしいランダムな待機時間"""
    time.sleep(random.uniform(min_sec, max_sec))


def human_type(page, selector, text):
    """人間らしいタイピング（1文字ずつ、ランダムな間隔）"""
    page.click(selector)
    for char in text:
        page.keyboard.type(char)
        time.sleep(random.uniform(0.03, 0.12))


def generate_description(title, vendor, sale_price_usd, suggested_price_jpy):
    """商品説明文を自動生成する"""
    return (
        f"【{vendor}】{title}\n\n"
        f"海外正規店（BaseBlu）から直接お取り寄せします。\n"
        f"正規品・新品・タグ付きでお届けします。\n\n"
        f"■ ブランド: {vendor}\n"
        f"■ 商品名: {title}\n"
        f"■ 現地価格: ${float(sale_price_usd):.0f} USD\n\n"
        f"配送は通常7〜14営業日程度です。\n"
        f"関税・消費税は価格に含まれています。\n\n"
        f"ご不明な点はお気軽にご質問ください。"
    )


def login(page, email, password):
    """BUYMAにログインする"""
    print("  🔑 BUYMAにログイン中...")
    page.goto(BUYMA_LOGIN_URL, wait_until="networkidle")
    human_delay(1.0, 2.0)

    # メールアドレス入力
    page.fill('input[name="email"], input[type="email"], #email', email)
    human_delay(0.3, 0.8)

    # パスワード入力
    page.fill('input[name="password"], input[type="password"], #password', password)
    human_delay(0.5, 1.0)

    # ログインボタンクリック
    page.click('button[type="submit"], input[type="submit"], .login-btn, #login-button')
    page.wait_for_load_state("networkidle")
    human_delay(1.5, 2.5)

    # ログイン確認
    if "signin" in page.url or "login" in page.url:
        print("  ❌ ログイン失敗。メールアドレスとパスワードを確認してください。")
        return False

    print("  ✅ ログイン成功！")
    return True


def fill_listing_form(page, product):
    """
    出品フォームに商品情報を入力する。
    ※ BUYMAのフォーム構造に合わせてセレクタを調整してください。
    """
    title = product.get("title", "")
    vendor = product.get("vendor", "")
    sale_price_usd = product.get("sale_price_usd", "0")
    suggested_price = product.get("suggested_buyma_price_jpy", "0")
    description = generate_description(title, vendor, sale_price_usd, suggested_price)

    print(f"  ✏️  入力中: {title[:40]}...")

    try:
        # 新規出品ページを開く
        page.goto(BUYMA_NEW_ITEM_URL, wait_until="networkidle")
        human_delay(2.0, 3.0)

        # --- 商品名 ---
        # ※ セレクタはBUYMAのフォームに合わせて調整が必要な場合があります
        name_selectors = [
            'input[name="item[name]"]',
            '#item_name',
            'input[placeholder*="商品名"]',
            'input[placeholder*="商品"]',
        ]
        for sel in name_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.click(sel)
                    page.fill(sel, "")
                    human_type(page, sel, title)
                    human_delay(0.5, 1.0)
                    break
            except Exception:
                continue

        # --- 出品価格 ---
        price_str = str(int(float(suggested_price)))
        price_selectors = [
            'input[name="item[price]"]',
            '#item_price',
            'input[placeholder*="価格"]',
            'input[placeholder*="円"]',
        ]
        for sel in price_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.click(sel)
                    page.fill(sel, "")
                    human_type(page, sel, price_str)
                    human_delay(0.5, 1.0)
                    break
            except Exception:
                continue

        # --- 商品説明 ---
        desc_selectors = [
            'textarea[name="item[description]"]',
            '#item_description',
            'textarea[placeholder*="説明"]',
            'textarea[placeholder*="商品"]',
        ]
        for sel in desc_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.click(sel)
                    page.fill(sel, description)
                    human_delay(0.5, 1.0)
                    break
            except Exception:
                continue

        # --- 画像アップロードはスキップ ---
        # （手動で後から追加してください）

        # --- 下書き保存 ---
        draft_selectors = [
            'button:has-text("下書き")',
            'input[value="下書き保存"]',
            '.draft-save-btn',
            'button[name="draft"]',
        ]
        saved_as_draft = False
        for sel in draft_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.click(sel)
                    page.wait_for_load_state("networkidle")
                    human_delay(1.5, 2.5)
                    saved_as_draft = True
                    break
            except Exception:
                continue

        if not saved_as_draft:
            print("  ⚠️  下書き保存ボタンが見つかりません。手動で保存してください。")

        return "draft_saved" if saved_as_draft else "form_filled"

    except PlaywrightTimeoutError:
        print(f"  ⚠️  タイムアウト: {title[:30]}")
        return "timeout"
    except Exception as e:
        print(f"  ❌ エラー: {e}")
        return "error"


def save_results(results, output_path):
    """処理結果をCSVに保存する"""
    fieldnames = [
        "status", "title", "vendor",
        "suggested_buyma_price_jpy", "estimated_profit_jpy",
        "image_url", "product_url", "processed_at"
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n📄 処理結果を保存: {output_path}")


def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        print("🧪 テストモード: 最初の1件のみ処理します")

    # 設定読み込み
    config = load_config()
    email = config.get("buyma_email", "")
    password = config.get("buyma_password", "")

    if not email or not password:
        print("❌ config.json に buyma_email と buyma_password を設定してください。")
        sys.exit(1)

    # 商品リスト読み込み
    csv_path = get_latest_profitable_csv()
    if not csv_path:
        print("❌ 利益商品CSVが見つかりません。先に filter_baseblu_profitable.py を実行してください。")
        sys.exit(1)

    products = load_products(csv_path)
    if not products:
        print("❌ 商品データが空です。")
        sys.exit(1)

    if test_mode:
        products = products[:1]

    print(f"📦 処理対象: {len(products)} 件")
    print("=" * 50)

    results = []
    success_count = 0
    error_count = 0

    with sync_playwright() as p:
        # Chromiumを起動（headless=False で画面表示、bot検知対策）
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()

        # ログイン
        if not login(page, email, password):
            browser.close()
            sys.exit(1)

        # 各商品を処理
        for i, product in enumerate(products, 1):
            title = product.get("title", "")
            print(f"\n[{i}/{len(products)}] {title[:50]}")

            status = fill_listing_form(page, product)

            result = {
                "status": status,
                "title": title,
                "vendor": product.get("vendor", ""),
                "suggested_buyma_price_jpy": product.get("suggested_buyma_price_jpy", ""),
                "estimated_profit_jpy": product.get("estimated_profit_jpy", ""),
                "image_url": product.get("image_url", ""),
                "product_url": product.get("product_url", ""),
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            results.append(result)

            if status in ("draft_saved", "form_filled"):
                success_count += 1
            else:
                error_count += 1

            # 商品間のランダム待機（連続操作防止）
            if i < len(products):
                wait = random.uniform(5, 10)
                print(f"  ⏳ 次の商品まで {wait:.1f}秒 待機...")
                time.sleep(wait)

        browser.close()

    # 結果保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    result_path = os.path.join(OUTPUT_DIR, f"{date_str}_buyma_listing_results.csv")
    save_results(results, result_path)

    print("\n" + "=" * 50)
    print(f"✅ 完了！  成功: {success_count}件  エラー: {error_count}件")
    print(f"📌 画像は手動でBUYMAの下書き一覧から追加してください。")


if __name__ == "__main__":
    main()
