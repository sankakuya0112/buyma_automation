"""
buyma_auto_listing.py (v4 — 2026-04 プロショッパー仕様)
=========================================================
BUYMAへの自動出品スクリプト（統合版）

【v4 の改善】
  - 商品説明: 仕入れ先名・現地価格を削除。仕入れ先の英語商品説明を和訳して掲載
  - 品番(SKU): 仕入れ先から取得し、説明文とタイトルに含める
  - 販売可否: 「買付可」に変更（手元在庫ではなく海外買付方式）
  - 購入期限: 90日（最大）
  - 買付地: イタリア
  - 発送地: 日本
  - 関税: 出品者負担チェック
  - 買付先メモ: 仕入れ先名・URL・仕入れ額・販売額・想定利益を記録
  - 複数画像: メイン+サブ画像（最大5枚）対応
  - SEO最適化: タイトルにブランド名・品番・カテゴリを含める

【使い方】
  python3 scripts/buyma_auto_listing.py              # 全件・直接公開
  python3 scripts/buyma_auto_listing.py --draft      # 下書き保存のみ
  python3 scripts/buyma_auto_listing.py --test       # 1件テスト
  python3 scripts/buyma_auto_listing.py --resume     # 前回の続きから
  python3 scripts/buyma_auto_listing.py --from 3     # 3件目から

必要なもの:
  pip install playwright requests --break-system-packages
  playwright install chromium
"""

import csv, glob, json, os, sys, time, random, tempfile, unicodedata
import requests as req_lib
from datetime import datetime, timedelta

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("pip install playwright requests --break-system-packages && playwright install chromium")
    sys.exit(1)

# ========== パス設定 ==========
BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR    = os.path.join(BASE_DIR, "outputs", "reports")
CONFIG_PATH   = os.path.join(BASE_DIR, "config.json")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "auto_listing_progress.json")
DATA_DIR      = os.path.join(BASE_DIR, "data")

BUYMA_LOGIN_URL   = "https://www.buyma.com/login/"
BUYMA_LISTING_URL = "https://www.buyma.com/my/sell/new?tab=b"

# ========== React操作用JSヘルパー ==========
JS_HELPERS = """
window.__gf=function(e){var k=Object.keys(e).find(function(k){return k.startsWith('__reactFiber')||k.startsWith('__reactInternalInstance')});return k?e[k]:null};
window.__si=function(e,v){Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))};
window.__sta=function(e,v){Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))};
window.__srs=function(s,v,l){var f=window.__gf(s),c=f;for(var d=0;d<20;d++){if(!c)break;if(c.memoizedProps&&typeof c.memoizedProps.onChange==='function'){c.memoizedProps.onChange({value:v,label:l||String(v)});return 'ok d='+d}c=c.return}return 'not found'};
'helpers ok';
"""

# ========== 簡易英日翻訳マップ ==========
# よく出るファッション用語の簡易翻訳（完全な翻訳APIなしで対応）
FASHION_TERMS = {
    "composition": "素材", "material": "素材", "fabric": "生地",
    "cotton": "コットン", "silk": "シルク", "wool": "ウール",
    "polyester": "ポリエステル", "linen": "リネン", "cashmere": "カシミヤ",
    "leather": "レザー", "suede": "スエード", "nylon": "ナイロン",
    "viscose": "ビスコース", "elastane": "エラスタン", "lycra": "ライクラ",
    "made in italy": "イタリア製", "made in france": "フランス製",
    "made in spain": "スペイン製", "made in portugal": "ポルトガル製",
    "dry clean only": "ドライクリーニングのみ", "hand wash": "手洗い",
    "machine wash": "洗濯機可",
    "slim fit": "スリムフィット", "regular fit": "レギュラーフィット",
    "oversized": "オーバーサイズ", "relaxed fit": "リラックスフィット",
    "midi": "ミディ丈", "maxi": "マキシ丈", "mini": "ミニ丈",
    "long sleeve": "長袖", "short sleeve": "半袖", "sleeveless": "ノースリーブ",
    "round neck": "ラウンドネック", "v-neck": "Vネック", "crew neck": "クルーネック",
    "high waist": "ハイウエスト", "low rise": "ローライズ",
    "zip closure": "ジップ開閉", "button closure": "ボタン開閉",
    "lining": "裏地", "unlined": "裏地なし",
    "shoulder bag": "ショルダーバッグ", "tote bag": "トートバッグ",
    "crossbody": "クロスボディ", "clutch": "クラッチ",
}

def translate_description(desc_en):
    """英語商品説明を簡易和訳する"""
    if not desc_en:
        return ""
    lines = desc_en.strip().split('\n')
    translated = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        tl = line.lower()
        # よくあるパターンを和訳
        for en, ja in FASHION_TERMS.items():
            if en in tl:
                line = line.replace(en, ja).replace(en.title(), ja).replace(en.upper(), ja)
        translated.append(line)
    return '\n'.join(translated)


# ========== データ読み込み ==========

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_categories():
    path = os.path.join(DATA_DIR, "categories.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_brands():
    path = os.path.join(DATA_DIR, "brands.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"brands": {}, "unregistered": []}

def load_progress():
    """
    進捗ファイルを読み込む。
    v4.1: status 別に保持するように変更。過去バージョンの形式（processed_titles のみ）
    からも移行できる後方互換を持つ。
    """
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # スキーマ移行: 新形式に揃える
        data.setdefault("succeeded_titles", [])
        data.setdefault("failed_titles", [])
        data.setdefault("processed_titles", [])  # 後方互換
        return data
    return {"succeeded_titles": [], "failed_titles": [], "processed_titles": []}


def save_progress(data):
    """進捗ファイルを原子的に保存する（tmp → rename）。"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmp_path = PROGRESS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, PROGRESS_FILE)


# status 分類: resume で「再試行すべき」扱いにする status
#   これらの status は進捗に「失敗」として記録し、--resume で再処理する。
RETRIABLE_STATUSES = {"error", "timeout", "save_failed", "publish_failed"}
# status 分類: スキップすべき status（一時的失敗でない恒久的スキップ）
PERMANENT_SKIP_STATUSES = {"brand_not_found"}
# status 分類: 成功
SUCCESS_STATUSES = {"published", "draft"}

# ========== ユーティリティ ==========

def human_delay(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))

def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    result = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", result)

def get_category_id(title: str, cat_data: dict) -> tuple:
    t = title.lower()
    for rule in cat_data.get("rules", []):
        if any(kw in t for kw in rule["keywords"]):
            return rule["category_id"], rule.get("label", "")
    return cat_data.get("default_category_id", 3501), cat_data.get("default_label", "")

def resolve_brand(vendor: str, brands_data: dict) -> tuple:
    safe = normalize_text(vendor)
    known = brands_data.get("brands", {})
    unreg = brands_data.get("unregistered", [])
    if safe in known:
        info = known[safe]
        return info["brand_id"], info.get("phonetic", safe)
    if safe in unreg:
        return 0, ""
    return -1, safe


def generate_description(title, vendor, sku, description_en, cat_label):
    """プロショッパー仕様の商品説明を生成
    - 仕入れ先名・現地価格は一切含めない
    - 仕入れ先の商品説明を和訳して掲載
    - 品番・素材・サイズ感などの情報を充実させる
    """
    st = normalize_text(title)
    sv = normalize_text(vendor)

    # 商品説明の和訳
    desc_ja = translate_description(description_en)

    lines = []
    lines.append(f"◆ {sv} / {st}")
    if sku:
        lines.append(f"◆ 品番: {sku}")
    lines.append("")

    # 仕入れ先の商品説明（和訳版）
    if desc_ja:
        lines.append("━━━ 商品詳細 ━━━")
        lines.append(desc_ja)
        lines.append("")

    # 安心ポイント（売れるショッパーは必ず記載）
    lines.append("━━━ 安心の正規品保証 ━━━")
    lines.append("・ヨーロッパ正規取扱店からの直接買付")
    lines.append("・100%正規品・新品未使用・タグ付き")
    lines.append("・ご希望の方にはレシート画像をお見せできます")
    lines.append("")

    # 配送・関税
    lines.append("━━━ 配送について ━━━")
    lines.append("・買付地: イタリア → 発送地: 日本")
    lines.append("・お届けまで: ご注文確定後 10〜21日程度")
    lines.append("・関税/消費税は当方で負担いたします（追加費用なし）")
    lines.append("・追跡番号付きの安心配送でお届けします")
    lines.append("")

    # 注意事項（クレーム防止）
    lines.append("━━━ ご注意事項 ━━━")
    lines.append("・海外買付のため、ご注文後のキャンセルはお受けできません")
    lines.append("・モニター環境により実物と色味が異なる場合がございます")
    lines.append("・海外製品のため、日本製品と検品基準が異なります")
    lines.append("・在庫は常に変動します。ご購入前に在庫確認をお願いいたします")
    lines.append("")
    lines.append("ご不明な点はお気軽にお問い合わせください。")

    return '\n'.join(lines)


def generate_buyma_title(title, vendor, sku, cat_label):
    """BUYMA用SEO最適化タイトル
    形式: 【ブランド名】商品名 品番 カテゴリ 正規品 関税送料込
    ※BUYMAタイトル上限は60文字程度
    """
    sv = normalize_text(vendor)
    st = normalize_text(title)
    parts = [f"{sv}", st]
    if sku:
        parts.append(sku)
    # SEOキーワード追加
    parts.append("正規品")
    parts.append("関税送料込")

    full = " ".join(parts)
    # 60文字超えたらSEOキーワードを削る
    if len(full) > 60:
        full = " ".join(parts[:-1])  # 「関税送料込」を削除
    if len(full) > 60:
        full = " ".join(parts[:-2])  # 「正規品」も削除
    if len(full) > 60:
        full = full[:57] + "..."

    return full


def download_image(url, dest):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    r = req_lib.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)


def load_products():
    pricing_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*_pricing_analysis.csv")), reverse=True)
    profitable_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*_baseblu_profitable_products.csv")), reverse=True)
    if not pricing_files:
        print("❌ 価格分析CSVが見つかりません"); sys.exit(1)
    if not profitable_files:
        print("❌ 利益商品CSVが見つかりません"); sys.exit(1)

    detail_map = {}
    with open(profitable_files[0], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["title"].strip(), row["vendor"].strip())
            detail_map[key] = row

    products = []
    with open(pricing_files[0], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row.get("商品名", "").strip()
            vendor = row.get("ブランド", "").strip()
            price = row.get("推奨出品価格(円)", "0").replace(",", "").strip()
            detail = detail_map.get((title, vendor), {})
            products.append({
                "title": title, "vendor": vendor,
                "recommended_price": price,
                "sale_price_usd": detail.get("sale_price_usd", "0"),
                "total_cost_jpy": detail.get("total_cost_jpy", "0"),
                "estimated_profit_jpy": detail.get("estimated_profit_jpy", "0"),
                "sku": detail.get("sku", ""),
                "description_en": detail.get("description_en", ""),
                "image_url": detail.get("image_url", ""),
                "sub_images": detail.get("sub_images", ""),
                "product_url": detail.get("product_url", ""),
            })
    print(f"✅ 商品データ: {len(products)}件")
    return products


# ========== Playwright操作関数 ==========

def login(page, email, password):
    print("  🔑 ログイン中...")
    page.goto(BUYMA_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    human_delay(2.0, 3.0)
    page.wait_for_selector('input[name="txtLoginId"]', timeout=15000)
    page.fill('input[name="txtLoginId"]', email)
    human_delay(0.3, 0.7)
    page.fill('input[name="txtLoginPass"]', password)
    human_delay(0.5, 1.0)
    page.click('input[id="login_do"]')
    page.wait_for_load_state("networkidle", timeout=30000)
    human_delay(1.5, 2.5)
    if "signin" in page.url or "login" in page.url:
        print("  ❌ ログイン失敗"); return False
    print("  ✅ ログイン成功"); return True


def upload_image(page, image_url, max_retries=2):
    """画像アップロード（リトライ付き）。ページ遷移直後に呼ぶこと。"""
    if not image_url:
        print("    ⚠️ 画像URLなし"); return False

    for attempt in range(max_retries + 1):
        if attempt > 0:
            print(f"    🔄 リトライ {attempt}/{max_retries}...")
            human_delay(2.0, 3.0)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            download_image(image_url, tmp_path)
        except Exception as e:
            print(f"    ❌ 画像DLエラー: {e}")
            try: os.unlink(tmp_path)
            except: pass
            continue

        upload_result = {"status": None}
        def on_response(response):
            if "item_image" in response.url:
                upload_result["status"] = response.status
                try: upload_result["body"] = response.json()
                except: pass

        page.on("response", on_response)
        try:
            page.locator('input[type="file"]').set_input_files(tmp_path)
        except Exception as e:
            print(f"    ❌ ファイルセット失敗: {e}")
            page.remove_listener("response", on_response)
            try: os.unlink(tmp_path)
            except: pass
            continue
        finally:
            try: os.unlink(tmp_path)
            except: pass

        for _ in range(40):
            if upload_result["status"] is not None: break
            time.sleep(0.5)
        page.remove_listener("response", on_response)

        if upload_result["status"] == 200:
            body = upload_result.get("body", {})
            if str(body.get("status", "")) == "0":
                print("    ✅ 画像アップロード成功"); return True
            print(f"    ❌ アップロード失敗 (body={body})")
        elif upload_result["status"] is not None:
            print(f"    ❌ HTTP {upload_result['status']}")
        else:
            print("    ⚠️ タイムアウト")
    return False


def upload_sub_images(page, sub_images_str):
    """サブ画像をアップロード（メイン画像の後に呼ぶ）"""
    if not sub_images_str:
        return 0
    urls = [u.strip() for u in sub_images_str.split("|") if u.strip()]
    uploaded = 0
    for url in urls[:4]:  # 最大4枚（メイン含めて5枚）
        human_delay(1.0, 2.0)
        if upload_image(page, url, max_retries=1):
            uploaded += 1
    if uploaded:
        print(f"    📷 サブ画像: {uploaded}枚アップロード")
    return uploaded


def set_title(page, title):
    page.evaluate(f"var el=document.querySelectorAll('input[type=\"text\"]')[0];if(el)window.__si(el,{json.dumps(title)});")

def set_description(page, desc):
    page.evaluate(f"var ta=document.querySelector('textarea');if(ta)window.__sta(ta,{json.dumps(desc)});")

def set_category(page, category_id):
    result = page.evaluate(f"var s=document.querySelectorAll('.Select');s[0]?window.__srs(s[0],{category_id},'カテゴリ'):'not found';")
    print(f"    📁 カテゴリ={category_id} → {result}")

def set_price(page, price_jpy):
    result = page.evaluate(f"""(function(){{
        var inputs=document.querySelectorAll('input');
        for(var i=0;i<inputs.length;i++){{
            var el=inputs[i];if(el.type!=='text')continue;
            var a=el;for(var d=0;d<6;d++){{if(!a.parentElement)break;a=a.parentElement;
                if(a.textContent&&a.textContent.includes('商品価格')){{
                    window.__si(el,{json.dumps(str(int(price_jpy)))});return 'ok'}}}}}}
        return 'not found'}})()""")
    print(f"    💴 ¥{int(price_jpy):,} → {result}")


def select_brand(page, brand_name, brand_phonetic, brand_id):
    if brand_id == 0:
        print(f"    ⚠️ ブランド未登録: {brand_name}"); return False

    if brand_id > 0:
        result = page.evaluate(f"""(function(){{
            var bi=document.querySelectorAll('input')[7];if(!bi)return 'no input';
            var f=window.__gf(bi),c=f;
            for(var d=0;d<8;d++){{if(!c)break;c=c.return}}
            if(c&&c.memoizedProps&&c.memoizedProps.onChangeText)
                c.memoizedProps.onChangeText({{target:{{value:{json.dumps(brand_name)}}}}});
            var f2=window.__gf(bi),c2=f2;
            for(var d=0;d<30;d++){{if(!c2)break;
                if(c2.memoizedProps&&c2.memoizedProps.onClickBrand){{
                    c2.memoizedProps.onClickBrand({{text:{json.dumps(brand_name)},phonetic:{json.dumps(brand_phonetic)},brand_id:{brand_id}}});
                    return 'ok d='+d}}c2=c2.return}}
            return 'onClickBrand not found'}})()""")
        time.sleep(0.5)
        val = page.evaluate("document.querySelectorAll('input')[7]?.value||''")
        ok = brand_phonetic in val or brand_name.lower() in val.lower()
        print(f"    🏷️ ブランド: {val} → {'✅' if ok else '⚠️'} ({result})")
        return ok

    # brand_id == -1: サジェスト経由
    page.evaluate(f"var bi=document.querySelectorAll('input')[7];if(bi)window.__si(bi,{json.dumps(brand_name)});")
    for _ in range(10):
        time.sleep(0.5)
        if page.evaluate("document.querySelectorAll('.bmm-c-suggest__option--selectable').length>0"):
            break
    clicked = page.evaluate(f"""(function(){{
        var opts=document.querySelectorAll('.bmm-c-suggest__option--selectable');
        if(!opts.length)return false;
        var f=window.__gf(opts[0]),c=f;
        for(var d=0;d<8;d++){{if(!c)break;
            if(c.memoizedProps&&typeof c.memoizedProps.onClick==='function'){{
                c.memoizedProps.onClick({{text:{json.dumps(brand_name)}}});return true}}c=c.return}}
        return false}})()""")
    if not clicked:
        print(f"    ⚠️ ブランド未登録: {brand_name}"); return False
    print(f"    🏷️ ブランド選択: {brand_name}"); return True


def set_shipping(page, price_jpy):
    """配送チェックボックス。¥50,000以上は追跡あり3種のみ。"""
    indices = [7, 8, 9] if price_jpy >= 50000 else [6, 7, 8, 9]
    page.evaluate(f"""var cbs=document.querySelectorAll('input[type="checkbox"]');
        {json.dumps(indices)}.forEach(function(i){{if(cbs[i]&&!cbs[i].checked)cbs[i].click()}});""")
    print(f"    🚚 配送: インデックス{indices}")


def set_region(page):
    """買付地をイタリア、発送地を日本に設定"""
    # 買付地域・発送地域の.Selectを特定して設定
    result = page.evaluate("""
        (function(){
            var summaries = document.querySelectorAll('.bmm-c-summary__ttl');
            var results = [];
            for(var i=0; i<summaries.length; i++){
                var text = summaries[i].textContent.trim();
                if(text.includes('買付地')){
                    // 買付地の親要素内の.Selectを探す
                    var parent = summaries[i].closest('.bmm-c-summary') || summaries[i].parentElement.parentElement;
                    var selects = parent.querySelectorAll('.Select');
                    for(var j=0; j<selects.length; j++){
                        // ヨーロッパ（2003）を選択してからイタリア（20039）を選択
                        window.__srs(selects[j], '2003', 'ヨーロッパ');
                    }
                    results.push('買付地=ヨーロッパ');
                }
                if(text.includes('発送地')){
                    var parent = summaries[i].closest('.bmm-c-summary') || summaries[i].parentElement.parentElement;
                    var selects = parent.querySelectorAll('.Select');
                    for(var j=0; j<selects.length; j++){
                        window.__srs(selects[j], '1001', '日本');
                    }
                    results.push('発送地=日本');
                }
            }
            // フォールバック: summary要素が見つからない場合
            if(results.length === 0){
                var allSelects = document.querySelectorAll('.Select');
                for(var k=0; k<allSelects.length; k++){
                    var html = allSelects[k].innerHTML;
                    if(html.includes('2003') || html.includes('ヨーロッパ')){
                        window.__srs(allSelects[k], '2003', 'ヨーロッパ');
                        results.push('fallback_ヨーロッパ idx='+k);
                    }
                }
            }
            return results;
        })()
    """)
    print(f"    🌍 地域: {result}")


def set_purchase_deadline(page):
    """購入期限を90日後に設定"""
    deadline = (datetime.now() + timedelta(days=90)).strftime("%Y/%m/%d")
    result = page.evaluate(f"""(function(){{
        var inputs = document.querySelectorAll('input');
        for(var i=0; i<inputs.length; i++){{
            var el = inputs[i];
            // 購入期限の入力欄を探す（placeholder or 親要素テキストで判定）
            var a = el;
            for(var d=0; d<6; d++){{
                if(!a.parentElement) break;
                a = a.parentElement;
                if(a.textContent && (a.textContent.includes('購入期限') || a.textContent.includes('購入・届け期限'))){{
                    window.__si(el, {json.dumps(deadline)});
                    return 'ok: ' + {json.dumps(deadline)};
                }}
            }}
            // date型のinputも確認
            if(el.type === 'date' || (el.placeholder && el.placeholder.includes('/'))){{
                var ancestor = el;
                for(var dd=0; dd<4; dd++){{
                    if(!ancestor.parentElement) break;
                    ancestor = ancestor.parentElement;
                    if(ancestor.textContent && ancestor.textContent.includes('期限')){{
                        window.__si(el, {json.dumps(deadline)});
                        return 'ok date: ' + {json.dumps(deadline)};
                    }}
                }}
            }}
        }}
        return 'not found';
    }})()""")
    print(f"    📅 購入期限: {deadline} → {result}")


def set_customs_checkbox(page):
    """関税負担の項目にチェック"""
    result = page.evaluate("""(function(){
        var labels = document.querySelectorAll('label');
        for(var i=0; i<labels.length; i++){
            var text = labels[i].textContent;
            if(text.includes('関税') && (text.includes('負担') || text.includes('込み'))){
                var cb = labels[i].querySelector('input[type="checkbox"]');
                if(!cb) cb = document.getElementById(labels[i].getAttribute('for'));
                if(cb && !cb.checked){ cb.click(); return 'checked'; }
                if(cb && cb.checked){ return 'already checked'; }
            }
        }
        // フォールバック: チェックボックスのテキストで探す
        var cbs = document.querySelectorAll('input[type="checkbox"]');
        for(var j=0; j<cbs.length; j++){
            var parent = cbs[j].parentElement;
            if(parent && parent.textContent && parent.textContent.includes('関税')){
                if(!cbs[j].checked) cbs[j].click();
                return 'checked (fallback idx='+j+')';
            }
        }
        return 'not found';
    })()""")
    print(f"    🏛️ 関税負担: {result}")


def set_color(page):
    page.evaluate("""var tabs=document.querySelectorAll('[role="tab"]');
        var t=Array.from(tabs).find(function(t){return t.textContent.trim()==='色'});if(t)t.click();""")
    time.sleep(0.8)
    page.evaluate("""var p=document.querySelector('#react-tabs-1');
        var s=p?p.querySelector('.Select'):null;var inp=p?p.querySelector('input[type="text"]'):null;
        if(s)window.__srs(s,99,'マルチカラー');if(inp)window.__si(inp,'マルチカラー');""")
    print("    🎨 色: マルチカラー")


def set_size_and_stock(page):
    """サイズ=バリエーションなし、在庫=買付可、数量=1"""
    page.evaluate("""var tabs=document.querySelectorAll('[role="tab"]');
        var t=Array.from(tabs).find(function(t){return t.textContent.trim()==='サイズ'});if(t)t.click();""")
    time.sleep(0.8)
    page.evaluate("""var p=document.querySelector('#react-tabs-3');
        var s=p?p.querySelector('.Select'):null;if(s)window.__srs(s,'none','バリエーションなし');""")
    time.sleep(0.5)

    # 在庫設定: 「買付可」(value=1) に変更（v3までは「手元に在庫あり」=2だった）
    page.evaluate("var ss=document.querySelectorAll('.Select');if(ss[7])window.__srs(ss[7],1,'買付可');")
    time.sleep(0.6)

    # 数量
    page.evaluate("""var q=document.querySelector('input[placeholder="数量"]');if(q)window.__si(q,'1');""")
    print("    📦 サイズ/在庫: バリエーションなし / 買付可 / 数量1")


def set_purchase_memo(page, product):
    """買付先メモを設定（出品者の内部メモ。購入者には見えない）"""
    vendor = normalize_text(product.get("vendor", ""))
    product_url = product.get("product_url", "")
    sale_price_usd = product.get("sale_price_usd", "0")
    recommended_price = product.get("recommended_price", "0")
    total_cost = product.get("total_cost_jpy", "0")
    profit = product.get("estimated_profit_jpy", "0")

    memo_source = "BaseBlu"
    memo_url = product_url
    memo_desc = (
        f"仕入れ元: BaseBlu (${sale_price_usd} USD)\n"
        f"総仕入れコスト: ¥{total_cost}\n"
        f"販売価格: ¥{recommended_price}\n"
        f"想定利益: ¥{profit}"
    )

    # 買付先メモのフォーム要素を探して入力
    result = page.evaluate(f"""(function(){{
        var results = [];
        // 買付先メモセクションを探す
        var sections = document.querySelectorAll('.bmm-c-summary__ttl, h3, h4, label');
        for(var i=0; i<sections.length; i++){{
            if(sections[i].textContent.includes('買付先')){{
                results.push('section found');
                break;
            }}
        }}

        // 買付先名の入力欄
        var allInputs = document.querySelectorAll('input[type="text"]');
        for(var i=0; i<allInputs.length; i++){{
            var el = allInputs[i];
            var a = el;
            for(var d=0; d<6; d++){{
                if(!a.parentElement) break;
                a = a.parentElement;
                if(a.textContent && a.textContent.includes('買付先名')){{
                    window.__si(el, {json.dumps(memo_source)});
                    results.push('買付先名=ok');
                    break;
                }}
            }}
        }}

        // 買付先URL
        for(var i=0; i<allInputs.length; i++){{
            var el = allInputs[i];
            var a = el;
            for(var d=0; d<6; d++){{
                if(!a.parentElement) break;
                a = a.parentElement;
                if(a.textContent && (a.textContent.includes('買付先URL') || a.textContent.includes('URL'))){{
                    window.__si(el, {json.dumps(memo_url)});
                    results.push('URL=ok');
                    break;
                }}
            }}
        }}

        // 買付先メモ（説明テキストエリア）
        var textareas = document.querySelectorAll('textarea');
        for(var i=0; i<textareas.length; i++){{
            var ta = textareas[i];
            var a = ta;
            for(var d=0; d<6; d++){{
                if(!a.parentElement) break;
                a = a.parentElement;
                if(a.textContent && a.textContent.includes('買付先')){{
                    window.__sta(ta, {json.dumps(memo_desc)});
                    results.push('メモ=ok');
                    break;
                }}
            }}
        }}

        return results.length ? results : 'not found';
    }})()""")
    print(f"    📝 買付先メモ: {result}")


def publish_product(page):
    vr = {"status": None}
    def on_resp(r):
        if "validation" in r.url: vr["status"] = r.status
    page.on("response", on_resp)

    clicked = page.evaluate("""var b=Array.from(document.querySelectorAll('button'))
        .find(function(b){return b.textContent.includes('入力内容を確認する')});
        if(b){b.click();true}else{false}""")
    if not clicked:
        page.remove_listener("response", on_resp)
        print("    ❌ 確認ボタンなし"); return False

    for _ in range(30):
        time.sleep(0.5)
        if vr["status"] is not None: break
    page.remove_listener("response", on_resp)

    if vr["status"] != 200:
        print(f"    ❌ バリデーション失敗 (status={vr['status']})"); return False
    print("    ✅ バリデーションOK")
    human_delay(0.5, 1.0)

    page.evaluate("""var b=Array.from(document.querySelectorAll('button'))
        .find(function(b){return b.textContent.includes('公開する')});if(b)b.click();""")
    for _ in range(30):
        time.sleep(0.5)
        if "completed" in page.url: break

    if "completed" not in page.url:
        print(f"    ⚠️ リダイレクト未確認"); return False
    print("    🎉 出品公開完了！"); return True


def save_draft(page):
    page.evaluate("""var b=Array.from(document.querySelectorAll('button'))
        .find(function(b){return b.textContent.trim().includes('下書き保存する')});if(b)b.click();""")
    time.sleep(2.5)
    url = page.url
    if "/my/sell/" in url and "/edit" in url:
        item_id = url.split("/my/sell/")[1].replace("/edit", "").split("?")[0]
        print(f"    💾 下書き保存: ID={item_id}"); return item_id
    print(f"    ⚠️ 保存未確認"); return None


# ========== 1商品の処理 ==========

def process_product(page, product, draft_mode, brands_data, cat_data):
    title   = product["title"]
    vendor  = product["vendor"]
    price   = int(product["recommended_price"])
    sku     = product.get("sku", "")
    desc_en = product.get("description_en", "")
    img_url = product.get("image_url", "")
    sub_imgs = product.get("sub_images", "")

    cat_id, cat_label = get_category_id(title, cat_data)
    safe_vendor = normalize_text(vendor)
    b_id, b_phonetic = resolve_brand(vendor, brands_data)

    # v4: SEO最適化タイトル & プロ仕様商品説明
    display_title = generate_buyma_title(title, vendor, sku, cat_label)
    desc = generate_description(title, vendor, sku, desc_en, cat_label)

    print(f"  📦 {display_title[:50]}")
    print(f"     ブランド={safe_vendor}(id={b_id}) カテゴリ={cat_label}({cat_id}) ¥{price:,}")
    if sku:
        print(f"     品番={sku}")

    # ページ遷移
    try:
        page.goto(BUYMA_LISTING_URL, wait_until="networkidle", timeout=30000)
        human_delay(2.0, 3.0)
    except PWTimeout:
        print("  ❌ タイムアウト"); return "timeout", None

    # 1. 画像（最優先。後回しにすると403）
    img_ok = upload_image(page, img_url)
    if not img_ok:
        print("  ⚠️ メイン画像なしで続行")

    # サブ画像
    if img_ok and sub_imgs:
        upload_sub_images(page, sub_imgs)

    # JSヘルパー注入
    page.evaluate(JS_HELPERS)
    human_delay(0.3, 0.6)

    # 2-5. テキスト・カテゴリ・価格
    set_title(page, display_title); human_delay(0.3, 0.6)
    set_description(page, desc); human_delay(0.3, 0.6)
    set_category(page, cat_id); human_delay(0.5, 1.0)
    set_price(page, price); human_delay(0.3, 0.6)

    # 6. ブランド
    brand_ok = select_brand(page, safe_vendor, b_phonetic, b_id)
    if not brand_ok:
        return "brand_not_found", None
    human_delay(0.5, 1.0)

    if draft_mode:
        item_id = save_draft(page)
        return ("draft", item_id) if item_id else ("save_failed", None)

    # 7. 配送・地域
    set_shipping(page, price); human_delay(0.3, 0.6)
    set_region(page); human_delay(0.3, 0.6)

    # 8. 購入期限（90日）
    set_purchase_deadline(page); human_delay(0.3, 0.6)

    # 9. 関税チェック
    set_customs_checkbox(page); human_delay(0.3, 0.6)

    # 10. 色
    set_color(page); human_delay(0.3, 0.6)

    # 11. サイズ・在庫（買付可）
    set_size_and_stock(page); human_delay(0.5, 1.0)

    # 12. 買付先メモ
    set_purchase_memo(page, product); human_delay(0.3, 0.6)

    # 公開
    ok = publish_product(page)
    return ("published", "published") if ok else ("publish_failed", None)


# ========== メイン ==========

def main():
    args = sys.argv[1:]
    test_mode   = "--test"   in args
    resume_mode = "--resume" in args
    draft_mode  = "--draft"  in args
    start_from  = 1
    if "--from" in args:
        idx = args.index("--from")
        try: start_from = int(args[idx + 1])
        except: print("❌ --from の後に数字を指定"); sys.exit(1)

    print("=" * 50)
    print(f"🛒 BUYMA自動出品 v4 ({'下書き' if draft_mode else '公開'}{'・テスト' if test_mode else ''})")
    print("=" * 50)

    config = load_config()
    cat_data = load_categories()
    brands_data = load_brands()
    products = load_products()
    if not products:
        print("❌ 商品なし"); sys.exit(1)

    target = products[start_from - 1:]
    if test_mode:
        target = target[:1]
    print(f"📦 対象: {len(target)}件（{start_from}番〜）")

    progress = load_progress()
    if resume_mode:
        # v4.1: --resume は「成功済み」と「恒久的スキップ」のみ除外する。
        # 過去に error / timeout / publish_failed だった商品は再試行対象に戻す。
        succeeded = set(progress.get("succeeded_titles", []))
        # 後方互換: 旧スキーマでは processed_titles に全件が入っていたが、
        # エラー履歴と成功履歴の区別ができないため、--resume 時は無視する。
        # （必要なら --resume-legacy で旧挙動を復元可能）
        skipped_titles = succeeded
        target = [p for p in target if p["title"] not in skipped_titles]
        print(f"↩️ 再開: 成功済み {len(succeeded)} 件を除外 → 残り {len(target)} 件")

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP", timezone_id="Asia/Tokyo")
        page = ctx.new_page()

        if not login(page, config["buyma_email"], config["buyma_password"]):
            browser.close(); sys.exit(1)

        total = len(target)
        for i, product in enumerate(target, 1):
            print(f"\n{'─'*40} [{i}/{total}] {'─'*5}")
            try:
                status, item_id = process_product(page, product, draft_mode, brands_data, cat_data)
            except Exception as e:
                import traceback; traceback.print_exc()
                status, item_id = "error", None

            results.append({
                "status": status, "item_id": item_id or "",
                "title": product["title"], "vendor": product["vendor"],
                "price": product["recommended_price"],
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            # v4.1: status 別に進捗を記録する。重複登録は避ける。
            title = product["title"]
            if status in SUCCESS_STATUSES:
                if title not in progress["succeeded_titles"]:
                    progress["succeeded_titles"].append(title)
                # 過去に失敗していた履歴からは外す
                progress["failed_titles"] = [t for t in progress["failed_titles"] if t != title]
            elif status in PERMANENT_SKIP_STATUSES:
                # brand_not_found などは再試行しても無駄なので「成功扱い」でスキップ対象にする
                if title not in progress["succeeded_titles"]:
                    progress["succeeded_titles"].append(title)
            else:  # RETRIABLE_STATUSES またはその他
                if title not in progress["failed_titles"]:
                    progress["failed_titles"].append(title)
            save_progress(progress)

            print(f"  → {status}" + (f" (ID: {item_id})" if item_id and item_id != "published" else ""))
            if i < total:
                wait = random.uniform(8, 15)
                print(f"  ⏳ {wait:.0f}秒待機...")
                time.sleep(wait)

        browser.close()

    # 結果CSV
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    result_path = os.path.join(OUTPUT_DIR, f"{datetime.now():%Y-%m-%d}_auto_listing_results.csv")
    with open(result_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["status","item_id","title","vendor","price","processed_at"])
        w.writeheader(); w.writerows(results)

    pub = sum(1 for r in results if r["status"]=="published")
    dra = sum(1 for r in results if r["status"]=="draft")
    skip = sum(1 for r in results if r["status"]=="brand_not_found")
    fail = len(results) - pub - dra - skip
    print(f"\n{'='*50}")
    print(f"✅ 公開:{pub} 下書き:{dra} スキップ:{skip} 失敗:{fail}")
    print(f"📄 {result_path}")

if __name__ == "__main__":
    main()
