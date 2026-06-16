"""
buyma_auto_listing.py (v4.2 — 2026-04 プロショッパー仕様)
==========================================================
BUYMAへの自動出品スクリプト（統合版）

【v4.2 の変更】
  - pricing.py 統合: filter_baseblu_profitable.py の新カラム名（selling_price_jpy /
    profit_jpy / sale_price_eur）に対応。*_pricing_analysis.csv への依存を削除。
  - --max-price / --min-profit オプション追加（コマンドラインで価格帯を絞り込み）

【v4.1 の変更】
  - 進捗ファイル v4.1 スキーマ対応（succeeded_titles / failed_titles）
  - --resume は「成功済み」のみ除外し、過去 error は再試行

【v4 の改善】
  - 商品説明: 仕入れ先名・現地価格を削除。仕入れ先の英語商品説明を和訳して掲載
  - 品番(SKU): 仕入れ先から取得し、説明文とタイトルに含める
  - 販売可否: 「買付可」に変更（手元在庫ではなく海外買付方式）
  - 購入期限: 90日（最大）
  - 買付地: イタリア / 発送地: 日本
  - 関税: 出品者負担チェック
  - 買付先メモ: 仕入れ先名・URL・仕入れ額・販売額・想定利益を記録
  - 複数画像: メイン+サブ画像（最大5枚）対応
  - SEO最適化: タイトルにブランド名・品番・カテゴリを含める

【使い方】
  python3 scripts/buyma_auto_listing.py                       # 全件・直接公開
  python3 scripts/buyma_auto_listing.py --draft               # 下書き保存のみ
  python3 scripts/buyma_auto_listing.py --test                # 1件テスト
  python3 scripts/buyma_auto_listing.py --limit 5             # 先頭5件だけ処理
  python3 scripts/buyma_auto_listing.py --from 3 --limit 5    # 3番目から5件
  python3 scripts/buyma_auto_listing.py --hold                # 終了時にブラウザ保持（Enter待機）
  python3 scripts/buyma_auto_listing.py --resume              # 前回の続きから
  python3 scripts/buyma_auto_listing.py --from 3              # 3件目から
  python3 scripts/buyma_auto_listing.py --max-price 30000     # ¥30,000以下のみ
  python3 scripts/buyma_auto_listing.py --min-profit 5000     # 利益¥5,000以上のみ
  python3 scripts/buyma_auto_listing.py --window-x 1800 --window-y 0 --window-w 1400 --window-h 900
                                                        # 出品ブラウザを別モニタ座標で起動

必要なもの:
  pip install playwright requests --break-system-packages
  playwright install chromium
"""

import csv, glob, json, os, re, sys, time, random, tempfile, unicodedata
import requests as req_lib
from datetime import datetime, timedelta
from pathlib import Path

# app.utils.text を使えるようプロジェクトルートを sys.path に追加
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# .env から DEEPL_API_KEY 等を読み込む (存在しなければ silent skip)
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    pass

try:
    from app.utils.text import translate_description as _translate_description_advanced
except Exception:
    _translate_description_advanced = None

# 純粋関数は app.utils.listing_helpers に切り出し済み (Phase 2c+)
from app.utils.listing_helpers import (
    COLOR_JA_MAP,
    _ALPHA_SIZE_TO_JP,
    _EU_SHOE_TO_JP_CM,
    _IT_SIZE_RANGES,
    _buyma_title_width,
    _map_footwear_to_jp_cm,
    _strip_accents,
    _trim_buyma_title,
    classify_size_category,
    clean_source_description,
    evaluate_listing_readiness,
    format_size_name_for_listing,
    map_size_to_jp_reference,
    normalize_size_for_buyma,
    translate_color_to_jp,
)

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
STATE_DIR     = os.path.join(BASE_DIR, "state")
STORAGE_STATE_PATH = os.path.join(STATE_DIR, "buyma_storage_state.json")

BUYMA_LOGIN_URL   = "https://www.buyma.com/login/"
BUYMA_LISTING_URL = "https://www.buyma.com/my/sell/new?tab=b"
BRAND_SUGGEST_URL = "https://cdn-suggest.buyma.com/brand_suggest"

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



# clean_source_description は app.utils.listing_helpers に移設 (Phase 2d)


def translate_description(desc_en):
    """英語商品説明を和訳する。

    優先順位:
      1. app.utils.text.translate_description (DEEPL_API_KEY があれば DeepL 経由)
      2. FASHION_TERMS を使ったヒューリスティック置換

    いずれの場合も末尾でアクセント文字を ASCII に正規化する
    （BUYMA が è 等の文字を validation で弾くため）。
    """
    desc_en = clean_source_description(desc_en)
    if not desc_en:
        return ""
    try:
        if _translate_description_advanced is not None:
            return _strip_accents(_translate_description_advanced(desc_en))
    except Exception as e:
        print(f"    ⚠️ DeepL翻訳失敗、ヒューリスティック置換に切替: {e}")

    lines = desc_en.strip().split('\n')
    translated = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        tl = line.lower()
        for en, ja in FASHION_TERMS.items():
            if en in tl:
                line = line.replace(en, ja).replace(en.title(), ja).replace(en.upper(), ja)
        translated.append(line)
    return _strip_accents('\n'.join(translated))


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
            data = json.load(f)
        data.setdefault("brands", {})
        data.setdefault("unregistered", [])
        data.setdefault("auto_lookup_enabled", True)
        return data
    return {"brands": {}, "unregistered": [], "auto_lookup_enabled": True}


def load_tags():
    """data/tags.json からタグ付与ルールを読み込む。無ければ空ルール。"""
    path = os.path.join(DATA_DIR, "tags.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("rules", [])
        return data
    return {"rules": []}


def determine_tags(product, tag_rules):
    """商品情報から付与すべき BUYMA タグのリストを返す。

    ルール形式: `tag_rules["rules"]` の各要素が
      - product_types (任意): 対象カテゴリ (大文字、空なら全カテゴリ)
      - match_any: これらのキーワードのいずれかが含まれること (必須)
      - exclude_any (任意): これらのキーワードが含まれていたら除外
    を持ち、条件を満たせば tag を付ける。

    誤タグで出品取り下げのリスクがあるため、保守的に「明確な根拠がある」
    ケースのみ付与する Phase A 設計。
    """
    pt_upper = (product.get("product_type") or "").strip().upper()
    haystack = " ".join([
        product.get("title") or "",
        product.get("description_en") or "",
    ]).lower()

    selected = []
    for rule in tag_rules.get("rules", []):
        allowed = [t.upper() for t in rule.get("product_types", [])]
        if allowed and pt_upper not in allowed:
            continue
        incl = [kw.lower() for kw in rule.get("match_any", [])]
        if not incl:
            continue  # 保険: include 指定が無ければ付けない
        if not any(kw in haystack for kw in incl):
            continue
        excl = [kw.lower() for kw in rule.get("exclude_any", [])]
        if any(kw in haystack for kw in excl):
            continue
        tag = rule.get("tag")
        if tag and tag not in selected:
            selected.append(tag)
    return selected


def save_brands(data):
    path = os.path.join(DATA_DIR, "brands.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def lookup_brand_api(brand_name: str):
    """BUYMAのCDNサジェストAPIでブランドIDを取得する。見つからなければ None。"""
    try:
        resp = req_lib.get(
            BRAND_SUGGEST_URL,
            params={"keyword": brand_name},
            headers={
                "Accept": "application/json",
                "Origin": "https://www.buyma.com",
                "Referer": "https://www.buyma.com/",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json() or []
    except Exception as e:
        print(f"    ⚠️ ブランドAPIエラー: {e}")
        return None
    if not results:
        return None
    safe = normalize_text(brand_name).upper()
    # 完全一致優先
    for item in results:
        if normalize_text(item.get("text", "")).upper() == safe:
            return item
    # 部分一致フォールバック
    for item in results:
        itext = normalize_text(item.get("text", "")).upper()
        if safe in itext or itext in safe:
            return item
    return None

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

def get_category_path(title: str, product_type: str, cat_data: dict) -> list:
    """
    タイトル + product_type → BUYMA 3階層カテゴリパス [parent, middle, leaf] を返す。
    例: ("GIVENCHY Shoulder Bag", "BAGS") → ["レディースファッション", "バッグ・カバン", "ショルダーバッグ"]
    """
    t = (title or "").lower()
    pt = (product_type or "").strip().upper()

    for mapping in cat_data.get("mappings", []):
        if mapping.get("product_type", "").upper() != pt:
            continue
        # title から最もマッチするキーワードを探す
        for rule in mapping.get("keywords", []):
            for kw in rule.get("match", []):
                if kw.lower() in t:
                    return rule["path"]
        # product_type は一致したが keyword に当たらない → product_type のデフォルト
        return mapping.get("default", cat_data.get("default", []))

    # product_type も当たらない → グローバルデフォルト
    return cat_data.get("default", ["レディースファッション", "小物", "その他"])


def get_category_id(title: str, cat_data: dict) -> tuple:
    """
    旧API: get_category_path を返す形に変更。cat_label はパスをスラッシュで結合した表示用。
    戻り値: (path_list, label_string)
    """
    # 呼び出し元が product_type を渡せる構造になった後も、title だけで呼ばれるケースに備える
    path = get_category_path(title, "", cat_data)
    return path, " > ".join(path)

def resolve_brand(vendor: str, brands_data: dict) -> tuple:
    """
    ブランド名 → (brand_id, phonetic) を返す。
      brand_id >  0: 既知ブランド（onClickBrand経由で登録）
      brand_id == 0: 未登録確定（スキップ）
      brand_id == -1: 未知（DOMサジェスト経由で登録試行）

    brands.json の brand_id が null の場合は CDN APIで自動lookup。
    """
    safe = normalize_text(vendor)
    key_lc = safe.lower()
    known = brands_data.get("brands", {})
    unreg = brands_data.get("unregistered", [])

    # 大文字小文字を無視して既知ブランドを検索
    known_lc = {k.lower(): k for k in known.keys()}
    if key_lc in known_lc:
        orig_key = known_lc[key_lc]
        info = known[orig_key]
        bid = info.get("brand_id")
        phonetic = info.get("phonetic") or safe
        if bid:
            return bid, phonetic
        # brand_id が null ならAPIでlookup
        if brands_data.get("auto_lookup_enabled", True):
            api_result = lookup_brand_api(safe)
            if api_result:
                bid = api_result.get("brand_id")
                phonetic = api_result.get("phonetic") or phonetic
                known[orig_key] = {"brand_id": bid, "phonetic": phonetic}
                save_brands(brands_data)
                return bid, phonetic
        return -1, phonetic

    if safe in unreg or safe.lower() in [u.lower() for u in unreg]:
        return 0, ""

    # 未知: APIでlookup
    if brands_data.get("auto_lookup_enabled", True):
        api_result = lookup_brand_api(safe)
        if api_result:
            bid = api_result.get("brand_id")
            phonetic = api_result.get("phonetic") or safe
            known[key_lc] = {"brand_id": bid, "phonetic": phonetic}
            save_brands(brands_data)
            return bid, phonetic
        # CDN API で見つからなくても BUYMA 本体の DOM サジェストには出ることが
        # ある(CDN は recall 不完全)。ここで unregistered に自動登録すると
        # 取り返しがつかないので、-1 を返して select_brand() の DOM フォール
        # バックに委ねる。確定的に除外したいブランドはユーザが brands.json
        # の unregistered に手動追加する。

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
    lines.append("・ご注文後に丁寧に検品してから発送いたします")
    lines.append("")

    # 配送・関税
    lines.append("━━━ 配送について ━━━")
    lines.append("・買付地: イタリア / 発送地: 神奈川県")
    lines.append("・お届けまで: ご注文確定後 10〜21日程度")
    lines.append("・海外買付後、国内で検品してから発送いたします")
    lines.append("・関税等の表示はBUYMAの商品ページ上の記載に準じます")
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


# evaluate_listing_readiness / _buyma_title_width / _trim_buyma_title は
# app.utils.listing_helpers に移設 (Phase 2d)


def generate_buyma_title(title, vendor, sku, cat_label):
    """BUYMA用 タイトル生成

    形式: 【BRAND】 Title   （品番・正規品などは他フィールドに入るのでタイトルには含めない）
    BUYMA のタイトル上限（全角30文字・半角60文字）に合わせて幅ベースで切る。
    """
    sv = normalize_text(vendor).strip()
    st = normalize_text(title).strip()
    # 元タイトルに BRAND 名が含まれている場合は重複を避ける
    if sv and st.upper().startswith(sv.upper()):
        st = st[len(sv):].lstrip(" -:")

    base = f"【{sv}】 {st}" if sv else st
    return _trim_buyma_title(base, 60)


def download_image(url, dest):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    r = req_lib.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)


def load_products(max_price=None, min_profit=None):
    """
    利益商品 CSV から商品データを読み込む。

    v4.2: `*_pricing_analysis.csv`（手動編集の競合調査ファイル）への依存を削除。
    `*_profitable_products.csv`（Baseblu/Italist など）から読む。
    これは filter_baseblu_profitable.py が pricing.py 統合済みで、
    全ての必要情報（selling_price_jpy / profit_jpy / total_cost_jpy / ...）を
    含むため。

    Args:
        max_price: 販売価格上限（円）。指定時はこの価格以下の商品のみ。
        min_profit: 最低利益（円）。指定時はこの利益以上の商品のみ。
    """
    profitable_files = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "*_profitable_products.csv")),
        reverse=True,
    )
    if not profitable_files:
        print("❌ 利益商品 CSV が見つかりません。先に sales_to_csv → filter_baseblu_profitable.py を実行してください。")
        sys.exit(1)

    latest_csv = profitable_files[0]
    print(f"📂 読込: {os.path.basename(latest_csv)}")

    products = []
    skipped_price = 0
    skipped_profit = 0

    skipped_action = 0
    with open(latest_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            vendor = (row.get("vendor") or "").strip()
            if not title or not vendor:
                continue

            # Phase 2a: action='skip' の商品は出品対象外
            action = (row.get("action") or "list").strip().lower()
            if action == "skip":
                skipped_action += 1
                continue

            # 最終売価: final_price_jpy があれば優先、無ければ selling_price_jpy (従来 target)
            try:
                final_price = row.get("final_price_jpy") or ""
                final_price = int(float(final_price)) if final_price else 0
                target_price = int(float(row.get("selling_price_jpy") or 0))
                selling_price = final_price or target_price
                expected_profit = row.get("expected_profit_jpy") or ""
                expected_profit = int(float(expected_profit)) if expected_profit else 0
                profit = expected_profit or int(float(row.get("profit_jpy") or 0))
                total_cost = int(float(row.get("total_cost_jpy") or 0))
                sale_price_eur = row.get("sale_price_eur") or row.get("sale_price") or "0"
            except (ValueError, TypeError):
                continue

            # CLI フィルタ
            if max_price is not None and selling_price > max_price:
                skipped_price += 1
                continue
            if min_profit is not None and profit < min_profit:
                skipped_profit += 1
                continue

            products.append({
                "title": title,
                "vendor": vendor,
                "recommended_price": str(selling_price),
                "target_price_jpy": str(target_price),
                "final_price_jpy": str(final_price) if final_price else "",
                "sale_price_eur": str(sale_price_eur),
                "source_name": (row.get("source_name") or "").strip(),
                "currency": (row.get("currency") or "").strip(),
                "landed_cost_basis": (row.get("landed_cost_basis") or "").strip(),
                "total_cost_jpy": str(total_cost),
                "estimated_profit_jpy": str(profit),
                "profit_jpy": str(profit),
                "expected_margin_pct": row.get("expected_margin_pct") or row.get("margin_pct") or "",
                "market_median_jpy": row.get("market_median_jpy") or "",
                "market_sample_count": row.get("market_sample_count") or "",
                "decision_reason": row.get("decision_reason") or "no_market_data",
                "sku": (row.get("sku") or "").strip(),
                "product_type": (row.get("product_type") or "").strip(),
                "color": (row.get("color") or "").strip(),
                "sizes": (row.get("sizes") or "").strip(),
                "available_sizes": (row.get("available_sizes") or "").strip(),
                "season": (row.get("season") or "").strip(),
                "description_en": (row.get("description_en") or "").strip(),
                "image_url": (row.get("image_url") or "").strip(),
                "sub_images": (row.get("sub_images") or "").strip(),
                "product_url": (row.get("product_url") or "").strip(),
            })

    # 利益降順ソート
    products.sort(key=lambda p: int(p.get("profit_jpy", 0) or 0), reverse=True)

    print(f"✅ 商品データ: {len(products)} 件")
    if skipped_action:
        print(f"   ⏭ 市場判定 skip: {skipped_action} 件 (赤字回避等)")
    if skipped_price or skipped_profit:
        print(f"   スキップ: 価格上限超過 {skipped_price} 件 / 利益不足 {skipped_profit} 件")
    return products


# ========== Playwright操作関数 ==========

def login(page, email, password):
    # まず出品ページへ。storage_state が有効ならここでログイン済み判定できる。
    page.goto(BUYMA_LISTING_URL, wait_until="domcontentloaded", timeout=60000)
    human_delay(1.2, 2.0)
    if "signin" not in page.url and "login" not in page.url:
        print("  ✅ ログイン済みセッション再利用")
        return True

    print("  🔑 ログイン中...")
    page.goto(BUYMA_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    human_delay(2.0, 3.0)
    page.wait_for_selector('input[name="txtLoginId"]', timeout=15000)
    page.fill('input[name="txtLoginId"]', email)
    human_delay(0.3, 0.7)
    page.fill('input[name="txtLoginPass"]', password)
    human_delay(0.5, 1.0)
    page.click('input[id="login_do"]')
    # BUYMA はログイン後 WebSocket/polling で常時通信があり networkidle に
    # 到達しないことがある。signin URL から離れることをもって成功とみなす。
    try:
        page.wait_for_url(
            lambda url: ("signin" not in url) and ("login" not in url),
            timeout=30000,
        )
    except Exception:
        pass
    human_delay(1.0, 2.0)
    if "signin" in page.url or "login" in page.url:
        print(f"  ❌ ログイン失敗 (URL={page.url})"); return False
    print("  ✅ ログイン成功"); return True


def upload_image(page, image_url, max_retries=2):
    """画像アップロード（リトライ付き）。ページ遷移直後に呼ぶこと。

    BUYMA の画像アップロードAPI:
      POST https://www.buyma.com/rorapi/item_image.json
      Response: {status:"0", img_key, img_url, image_index, zoom_url, authenticity_token}

    page.expect_response() を使い、POSTメソッドのレスポンスを確実に待機する。
    """
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

        response = None
        try:
            with page.expect_response(
                lambda r: "item_image" in r.url and r.request.method == "POST",
                timeout=30000,
            ) as resp_info:
                page.locator('input[type="file"]').set_input_files(tmp_path)
            response = resp_info.value
        except PWTimeout:
            print("    ⚠️ タイムアウト（POST item_image.json が飛ばなかった）")
            try: os.unlink(tmp_path)
            except: pass
            continue
        except Exception as e:
            print(f"    ❌ アップロード例外: {e}")
            try: os.unlink(tmp_path)
            except: pass
            continue
        finally:
            try: os.unlink(tmp_path)
            except: pass

        if response.status != 200:
            print(f"    ❌ HTTP {response.status}")
            continue
        try:
            body = response.json()
        except Exception:
            body = {}
        if str(body.get("status", "")) == "0":
            img_key = body.get("img_key", "")[:12] + "..." if body.get("img_key") else ""
            print(f"    ✅ 画像アップロード成功 {img_key}")
            return True
        print(f"    ❌ アップロード失敗 (body={body})")
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

def set_category(page, path):
    """
    3階層のカテゴリドロップダウンを path の順に選択する。
    path: [親カテゴリ, 中カテゴリ, 小カテゴリ] のラベル文字列リスト。

    BUYMA は react-select v1 系を使用しており、オプションクリックは
    mousedown イベントで発火させる必要がある。
    """
    if not path or len(path) < 3:
        print(f"    ⚠️ カテゴリパス不正: {path}")
        return False

    # 候補セレクタ（BUYMA が独自クラスで包む可能性に備えて複数候補を試す）
    OPTION_SELECTORS = (
        ".Select-menu-outer .Select-option",
        ".Select-menu .Select-option",
        ".Select--menu-outer .Select-option",
        "[role=\"listbox\"] [role=\"option\"]",
        ".bmm-c-select__option",
        ".bmm-c-select-menu__option",
    )
    selector_union = ", ".join(OPTION_SELECTORS)

    def _pick_option(idx, label):
        """sels[idx] を開いて label の option をクリックする。

        option の探索は開いた select 自身のサブツリーを優先する。
        2026-06-10 実走の「パンツ > パンツ」422 のように親階層と子階層が
        同名の場合、ページ全域検索だと別階層のメニューに誤爆し得るため。
        """
        opened = page.evaluate(f"""(function(){{
            var sels = document.querySelectorAll('.Select, .bmm-c-select');
            if (!sels[{idx}]) return 'no_select';
            var ctrl = sels[{idx}].querySelector('.Select-control, .bmm-c-select__control');
            if (!ctrl) ctrl = sels[{idx}];
            ctrl.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
            ctrl.click();
            return 'opened';
        }})()""")
        if opened == "no_select":
            return "no_select"

        # メニュー描画待ち (sels[idx] 配下を優先して確認)
        for _ in range(25):
            time.sleep(0.12)
            ready = page.evaluate(f"""(function(){{
                var sels = document.querySelectorAll('.Select, .bmm-c-select');
                var root = sels[{idx}];
                if (root && root.querySelectorAll({json.dumps(selector_union)}).length > 0) return true;
                return document.querySelectorAll({json.dumps(selector_union)}).length > 0;
            }})()""")
            if ready:
                break

        return page.evaluate(f"""(function(){{
            var sels = document.querySelectorAll('.Select, .bmm-c-select');
            var root = sels[{idx}];
            var scoped = root ? root.querySelectorAll({json.dumps(selector_union)}) : [];
            var opts = scoped.length ? scoped : document.querySelectorAll({json.dumps(selector_union)});
            var target = {json.dumps(label)};
            for (var i = 0; i < opts.length; i++) {{
                if (opts[i].textContent.trim() === target) {{
                    opts[i].dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                    return 'exact';
                }}
            }}
            for (var i = 0; i < opts.length; i++) {{
                if (opts[i].textContent.trim().indexOf(target) !== -1) {{
                    opts[i].dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                    return 'partial';
                }}
            }}
            return 'no_match';
        }})()""")

    def _read_level_values():
        """カテゴリ 3 階層の現在の表示値を返す (未選択は '')。"""
        return page.evaluate("""(function(){
            var sels = document.querySelectorAll('.Select, .bmm-c-select');
            var vals = [];
            for (var i = 0; i < 3; i++) {
                if (!sels[i]) { vals.push(''); continue; }
                var v = sels[i].querySelector('.Select-value-label, .bmm-c-select__value');
                var t = v ? (v.textContent || '').trim() : '';
                if (t === '選択してください') t = '';
                vals.push(t);
            }
            return vals;
        })()""")

    for idx, label in enumerate(path):
        clicked = _pick_option(idx, label)
        if clicked == "no_select":
            print(f"    ⚠️ カテゴリ{idx+1}: .Select[{idx}] 見つからず")
            return False
        if clicked == "no_match":
            # 3階層目のみ: 区切り文字で分割してトークン単位で再検索する
            #    例 "シャツ・ブラウス" → "シャツ" / "ブラウス" を順番に試し、
            #        それでもダメなら "その他" にフォールバック
            alt_labels = []
            if idx == len(path) - 1:
                tokens = [t for t in label.replace("/", "・").split("・") if t.strip()]
                alt_labels.extend(tokens)
                alt_labels.append("その他")
            retry_success = False
            for alt in alt_labels:
                if _pick_option(idx, alt) != "no_match":
                    retry_success = True
                    label = alt
                    break
            if not retry_success:
                dump = page.evaluate(f"""(function(){{
                    var opts = document.querySelectorAll({json.dumps(selector_union)});
                    var rows = [];
                    for (var i = 0; i < Math.min(opts.length, 20); i++) rows.push(opts[i].textContent.trim());
                    if (rows.length === 0) {{
                        var sels = document.querySelectorAll('.Select, .bmm-c-select');
                        var meta = [];
                        for (var j = 0; j < sels.length && j < 10; j++) {{
                            meta.push(j + ':' + sels[j].className + ' | ' + (sels[j].textContent || '').slice(0,40));
                        }}
                        return 'SELECTS: ' + meta.join(' || ');
                    }}
                    return rows;
                }})()""")
                print(f"    ⚠️ カテゴリ{idx+1} '{label}' 候補なし: {dump}")
                return False
        time.sleep(0.6)

    # 選択後の検証 & リペア (2026-06-10 の「パンツ > パンツ」422 対策)。
    # 同名階層やメニュー誤爆で一部階層が placeholder のまま残るケースがあるため、
    # 表示値を読み取り、未選択の階層だけ再選択する (最大 2 周)。
    for repair_pass in range(2):
        time.sleep(0.4)
        values = _read_level_values()
        unset = [i for i in range(len(path)) if not values[i]]
        if not unset:
            break
        print(f"    🔧 カテゴリ未選択の階層をリペア (pass {repair_pass + 1}): "
              f"levels={[i + 1 for i in unset]} 現在値={values}")
        for i in unset:
            _pick_option(i, path[i])
            time.sleep(0.6)
    else:
        values = _read_level_values()
        if any(not values[i] for i in range(len(path))):
            print(f"    ⚠️ カテゴリ選択が不完全のまま: {values} (期待: {path})")
            return False

    print(f"    📁 カテゴリ: {' > '.join(path)} → ✅")
    return True

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


BRAND_INPUT_SELECTOR = 'input.bmm-c-text-field[placeholder*="ブランド名"]'
BRAND_OPTION_SELECTOR = '.bmm-c-suggest__option--selectable'


def select_brand(page, brand_name, brand_phonetic, brand_id):
    """
    ブランド選択: カテゴリ同様に
      ① ブランド入力欄に名前を入力 → サジェスト展開
      ② サジェスト候補を Playwright の native click で選択
    の流れで行う。React prop (onClickBrand) を直接呼び出す方式は内部 state が
    完全に更新されず「未登録」警告が残り、保存が validation で弾かれる。

    brand_id:
      > 0: 既知ブランド。完全一致 → 部分一致 の順でサジェスト候補を選ぶ
      == 0: ユーザが brands.json.unregistered に明示追加した除外ブランド。
            即座に False を返しスキップ
      == -1: CDN API では見つからなかった未検証ブランド。DOM サジェストで
             試行するが、誤登録防止のため完全一致のみ許可
    """
    if brand_id == 0:
        print(f"    ⚠️ ブランド手動除外: {brand_name} (unregistered リスト)")
        return False

    strict_match_only = (brand_id is not None and brand_id < 0)
    if strict_match_only:
        print(f"    🔎 CDN 未ヒット → DOM サジェストで試行(完全一致のみ): {brand_name}")

    # 1) 入力欄にブランド名を入れてサジェストを開く
    typed = page.evaluate(f"""(function(){{
        var bi = document.querySelector({json.dumps(BRAND_INPUT_SELECTOR)});
        if (!bi) return 'no_input';
        bi.focus();
        window.__si(bi, {json.dumps(brand_name)});
        return 'typed';
    }})()""")
    if typed == "no_input":
        print(f"    ⚠️ ブランド入力欄が見つからない")
        return False

    # 2) サジェスト候補を最大 5 秒待つ
    try:
        page.wait_for_selector(BRAND_OPTION_SELECTOR, timeout=5000, state="visible")
    except Exception:
        print(f"    ⚠️ サジェスト候補が出ない: {brand_name}")
        return False

    # 3) Playwright の native click で候補をクリック
    options = page.locator(BRAND_OPTION_SELECTOR)
    count = options.count()
    name_upper = brand_name.upper()

    def _pick_index():
        # 完全一致優先（候補textContentは "NAME(phonetic)" 形式を想定）
        for i in range(count):
            try:
                t = (options.nth(i).text_content() or "").strip().upper()
            except Exception:
                continue
            if (t == name_upper
                    or t.startswith(name_upper + "(")
                    or t.startswith(name_upper + "(")
                    or t.startswith(name_upper + " ")):
                return i, "exact"
        if strict_match_only:
            # 未検証ブランドは誤登録防止のため完全一致以外は受け付けない
            return -1, "no_exact_match_strict"
        # 部分一致フォールバック（既知ブランドのみ）
        for i in range(count):
            try:
                t = (options.nth(i).text_content() or "").strip().upper()
            except Exception:
                continue
            if name_upper in t:
                return i, "partial"
        return -1, "no_match"

    idx, match_type = _pick_index()
    if idx < 0:
        all_opts = page.evaluate(f"""
            Array.from(document.querySelectorAll({json.dumps(BRAND_OPTION_SELECTOR)}))
                .slice(0, 10).map(function(o){{return o.textContent.trim().slice(0, 50)}})
        """)
        print(f"    ⚠️ ブランド候補に該当なし: {brand_name} / 候補: {all_opts}")
        return False

    try:
        options.nth(idx).click(timeout=3000)
    except Exception as e:
        print(f"    ⚠️ ブランド候補クリック失敗: {e}")
        return False

    time.sleep(0.8)

    # 4) 検証: 入力欄の value と「未登録」警告の visible 判定
    val = page.evaluate(f"document.querySelector({json.dumps(BRAND_INPUT_SELECTOR)})?.value || ''")
    warning_visible = page.evaluate("""(function(){
        var warns = document.querySelectorAll('.bmm-c-error-msg, .bmm-c-error');
        for (var i = 0; i < warns.length; i++) {
            var w = warns[i];
            if ((w.textContent || '').indexOf('BUYMAに登録されていない') === -1) continue;
            var rect = w.getBoundingClientRect();
            var style = window.getComputedStyle(w);
            if (rect.width > 0 && rect.height > 0
                && style.display !== 'none' && style.visibility !== 'hidden') {
                return true;
            }
        }
        return false;
    })()""")

    if warning_visible:
        print(f"    ⚠️ ブランド警告残存: {val} (match={match_type})")
        return False
    ok = bool(val) and (brand_phonetic in val or brand_name.lower() in val.lower())
    print(f"    🏷️ ブランド: {val} → {'✅' if ok else '⚠️'} ({match_type})")
    return ok


def set_shipping(page, price_jpy):
    """配送方法にチェックを入れる。

    ラベル文字列で判定することで DOM 順番の変更に耐える。
    デフォルト: ヤマト運輸「宅急便コンパクト」と「宅急便」。
    """
    # チェックしたい配送方法のラベル（部分一致）。
    # 完全一致を優先するため、より具体的な "宅急便コンパクト" を先にしておく。
    targets = ["宅急便コンパクト", "宅急便"]

    result = page.evaluate(f"""(function(){{
        var targets = {json.dumps(targets)};
        var results = [];
        // checkbox をすべて拾い、その近傍（label / 親要素）のテキストから配送方法を特定する
        var cbs = document.querySelectorAll('input[type="checkbox"]');
        var matched = {{}};
        for (var j = 0; j < targets.length; j++) matched[targets[j]] = false;
        for (var i = 0; i < cbs.length; i++) {{
            var cb = cbs[i];
            // 近傍テキストを拾う（親 label / 親の親 / 隣接 span）
            var near = '';
            var p = cb.parentElement;
            for (var d = 0; d < 3 && p; d++) {{ near += ' ' + (p.textContent || ''); p = p.parentElement; }}
            for (var j = 0; j < targets.length; j++) {{
                if (matched[targets[j]]) continue;
                if (near.indexOf(targets[j]) !== -1) {{
                    if (!cb.checked) cb.click();
                    matched[targets[j]] = true;
                    results.push(targets[j] + '=on');
                    break;
                }}
            }}
        }}
        // 見つからないターゲットはデバッグ情報を出す
        var missing = targets.filter(function(t){{ return !matched[t]; }});
        if (missing.length) {{
            // label / 近傍テキストの候補を列挙
            var labels = document.querySelectorAll('label');
            var dump = [];
            for (var k = 0; k < labels.length && dump.length < 15; k++) {{
                var t = labels[k].textContent.trim();
                if (t && t.length < 50) dump.push(t);
            }}
            results.push('未検出=' + missing.join(',') + ' | label候補=' + JSON.stringify(dump));
        }}
        return results;
    }})()""")
    print(f"    🚚 配送: {result}")


def _select_by_label(page, dropdown_selector_js, label, debug_name=""):
    """任意のドロップダウン要素を開いて label のオプションを mousedown で選択する。

    dropdown_selector_js: JavaScript 式で .Select 要素を返すもの（例: 'sels[3]'）。
    debug_name: 失敗時ログ用の識別子。
    成功時 True, 失敗時 False。失敗時は option 候補を print する。
    """
    OPT = ".Select-menu-outer .Select-option, .Select-menu .Select-option, [role=\"listbox\"] [role=\"option\"], .bmm-c-select__option, .bmm-c-select-menu__option"
    opened = page.evaluate(f"""(function(){{
        var s = {dropdown_selector_js};
        if (!s) return 'no_select';
        var ctrl = s.querySelector('.Select-control, .bmm-c-select__control') || s;
        ctrl.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
        ctrl.click();
        return 'opened';
    }})()""")
    if opened != "opened":
        print(f"       [_select_by_label:{debug_name}] ドロップダウン未オープン: {opened}")
        return False
    for _ in range(25):
        time.sleep(0.12)
        ready = page.evaluate(f"document.querySelectorAll({json.dumps(OPT)}).length > 0")
        if ready:
            break
    clicked = page.evaluate(f"""(function(){{
        var opts = document.querySelectorAll({json.dumps(OPT)});
        var target = {json.dumps(label)};
        for (var i = 0; i < opts.length; i++) {{
            if (opts[i].textContent.trim() === target) {{
                opts[i].dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                return 'exact';
            }}
        }}
        for (var i = 0; i < opts.length; i++) {{
            if (opts[i].textContent.trim().indexOf(target) !== -1) {{
                opts[i].dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                return 'partial';
            }}
        }}
        return 'no_match';
    }})()""")
    if clicked == "no_match":
        dump = page.evaluate(f"""
            Array.from(document.querySelectorAll({json.dumps(OPT)}))
                .slice(0, 20)
                .map(function(o){{ return o.textContent.trim().slice(0, 40); }})
        """)
        print(f"       [_select_by_label:{debug_name}] '{label}' 候補なし。option dump: {dump}")
        # ドロップダウンを閉じる（次の操作のため）
        page.evaluate("document.body.click()")
        return False
    time.sleep(0.6)
    return True


# BUYMA 内部での react-select / カスタムドロップダウンを拾うための拡張セレクタ。
# 旧クラス (.Select, .bmm-c-select) に加え、新たな custom-select / role=combobox /
# class に "elect" を含む select 要素 / "dropdown" を含む要素もカバーする。
# `_find_section_selects` / `_dump_section_elements` / `set_region` で共有。
_SECTION_SELECT_QUERY = (
    '.Select, .bmm-c-select, .bmm-c-custom-select, [role="combobox"], '
    'select[class*="elect"], [class*="dropdown"]:not([class*="hover"])'
)


def _find_section_selects(page, section_title_keyword):
    """
    指定の見出しテキストに続く .Select 要素のインデックスを配列で返す。

    .bmm-c-summary__ttl や h3/dt の直後に .Select が並ぶ BUYMA の DOM 構造で、
    closest() が効かない／別セクションの Select まで拾ってしまう事を避けるため、
    「見出し要素の位置」と「次の見出し要素の位置」の間にある .Select を対象にする。

    セレクタは旧 (.Select / .bmm-c-select) に加え、新しい custom-select /
    role=combobox / [class*=dropdown] 等までカバーするように拡張済み (重複は dedupe)。
    """
    return page.evaluate(f"""(function(){{
        var titles = document.querySelectorAll(
            '.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt'
        );
        // 重複は dedupe (.Select かつ [class*=dropdown] みたいな要素を 1 つに)
        var rawSels = document.querySelectorAll({json.dumps(_SECTION_SELECT_QUERY)});
        var seen = new Set();
        var allSels = [];
        for (var k = 0; k < rawSels.length; k++) {{
            if (!seen.has(rawSels[k])) {{ seen.add(rawSels[k]); allSels.push(rawSels[k]); }}
        }}
        var keyword = {json.dumps(section_title_keyword)};
        // このセクションの開始見出しと、次の見出しの DOM 位置を特定する
        var startIdx = -1;
        for (var i = 0; i < titles.length; i++) {{
            var t = titles[i].textContent.trim();
            if (t === keyword || t.indexOf(keyword) === 0) {{ startIdx = i; break; }}
        }}
        if (startIdx < 0) return {{error: 'no_title', found_titles: Array.from(titles).map(function(t){{return t.textContent.trim().slice(0,20)}})}};
        var startEl = titles[startIdx];
        var endEl = titles[startIdx + 1] || null;
        // startEl の後ろ、endEl の前にある .Select を収集
        function afterStart(el){{
            return startEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING;
        }}
        function beforeEnd(el){{
            if (!endEl) return true;
            return endEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING;
        }}
        var result = [];
        for (var j = 0; j < allSels.length; j++) {{
            if (afterStart(allSels[j]) && beforeEnd(allSels[j])) {{
                result.push(j);
            }}
        }}
        // セクション内のラジオボタンやサブ見出しもついでに返す
        var radios = [];
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        var el;
        while ((el = walker.nextNode())) {{
            if (!afterStart(el) || !beforeEnd(el)) continue;
            if (el.tagName === 'INPUT' && el.type === 'radio') {{
                var parent = el.closest('label') || el.parentElement;
                var labelTxt = parent ? (parent.textContent || '').trim().slice(0, 20) : '';
                radios.push({{label: labelTxt, id: el.id || null}});
            }}
        }}
        return {{selects: result, radios: radios}};
    }})()""")


def _dump_section_elements(page, section_title_keyword, limit=30):
    """指定セクション (見出し → 次見出し) のスコープ内 DOM を診断ダンプする。

    Mac 実走 1 ターンで真因取得するため、買付地/発送地のセレクタが効かない場合に
    section スコープ内に存在する要素のメタ情報（tag/classes/role/id/text）を返す。

    戻り値: dict
      - error: 'no_title' のとき: {error, found_titles}
      - 通常: {section_html_length, dom_elements: [...], sels_found_via_extended: [{idx, tag, classes}, ...]}
    """
    return page.evaluate(f"""(function(){{
        var titles = document.querySelectorAll(
            '.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt, label'
        );
        var keyword = {json.dumps(section_title_keyword)};
        var startIdx = -1;
        for (var i = 0; i < titles.length; i++) {{
            var t = (titles[i].textContent || '').trim();
            if (t === keyword || t.indexOf(keyword) === 0) {{ startIdx = i; break; }}
        }}
        if (startIdx < 0) {{
            return {{
                error: 'no_title',
                found_titles: Array.from(titles).map(function(t){{
                    return (t.textContent || '').trim().slice(0, 20);
                }}).filter(function(s){{ return s.length > 0; }}).slice(0, 60)
            }};
        }}
        var startEl = titles[startIdx];
        var endEl = titles[startIdx + 1] || null;
        function afterStart(el){{
            return startEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING;
        }}
        function beforeEnd(el){{
            if (!endEl) return true;
            return endEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING;
        }}
        // セクションの HTML 長 (DOM 範囲の概算)
        var sectionHtmlLength = 0;
        // start..end の間にあるトップレベル兄弟の outerHTML を概算で合算
        try {{
            var node = startEl;
            while (node && (!endEl || node !== endEl)) {{
                if (node.outerHTML) sectionHtmlLength += node.outerHTML.length;
                node = node.nextElementSibling;
                if (!node) {{
                    // 親へ上って次へ
                    var p = (node || startEl).parentElement;
                    if (!p) break;
                    node = p.nextElementSibling;
                    if (!node) break;
                }}
                if (sectionHtmlLength > 200000) break;
            }}
        }} catch(e) {{}}

        // TreeWalker でセクション内要素を走査
        var elements = [];
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        var el;
        var lim = {limit};
        while ((el = walker.nextNode())) {{
            if (!afterStart(el)) continue;
            if (!beforeEnd(el)) break;
            var cls = (el.className && typeof el.className === 'string') ? el.className : (el.getAttribute && el.getAttribute('class')) || '';
            var role = (el.getAttribute && el.getAttribute('role')) || '';
            var idAttr = el.id || '';
            var txt = ((el.textContent || '').trim()).slice(0, 30);
            elements.push({{
                tag: (el.tagName || '').toLowerCase(),
                classes: String(cls).slice(0, 80),
                role: role,
                id: idAttr,
                text: txt
            }});
            if (elements.length >= lim) break;
        }}

        // 拡張クエリで実際にヒットした要素を section スコープで列挙
        var rawSels = document.querySelectorAll({json.dumps(_SECTION_SELECT_QUERY)});
        var hits = [];
        for (var j = 0; j < rawSels.length; j++) {{
            var s = rawSels[j];
            if (!afterStart(s) || !beforeEnd(s)) continue;
            var c = (s.className && typeof s.className === 'string') ? s.className : (s.getAttribute && s.getAttribute('class')) || '';
            hits.push({{
                idx: j,
                tag: (s.tagName || '').toLowerCase(),
                classes: String(c).slice(0, 80)
            }});
        }}

        return {{
            section_html_length: sectionHtmlLength,
            dom_elements: elements,
            sels_found_via_extended: hits
        }};
    }})()""")


def set_region(page, purchase_country="イタリア", ship_prefecture="神奈川県"):
    """買付地と発送地を設定する。

    BUYMA 側の DOM 変化で「まず 国内/海外 ラジオを押さないと Select が出ない」
    ケースがあるため、ラジオ選択を先行し、Select 未検出時はグローバル走査で
    ラベル一致選択を試す。
    """
    results = []

    # --- 診断ダンプ ---
    try:
        buy_dump = _dump_section_elements(page, "買付地")
    except Exception as e:
        buy_dump = {"error": f"dump_exception:{e}"}
    print(f"    🌍 [DUMP-買付地] {buy_dump}")
    try:
        ship_dump = _dump_section_elements(page, "発送地")
    except Exception as e:
        ship_dump = {"error": f"dump_exception:{e}"}
    print(f"    🌍 [DUMP-発送地] {ship_dump}")

    def _dump_keys(d):
        if not isinstance(d, dict) or d.get("error"):
            return []
        hits = d.get("sels_found_via_extended") or []
        keys = []
        for h in hits[:8]:
            tag = h.get("tag", "?")
            cls = (h.get("classes") or "").split()
            cls_short = ".".join(cls[:2]) if cls else ""
            keys.append(f"{tag}.{cls_short}" if cls_short else tag)
        return keys

    EXT_QUERY = _SECTION_SELECT_QUERY

    def _click_or_fallback(sel_idx, label, debug_name, legacy_query="'.Select, .bmm-c-select'"):
        try:
            dd = page.locator(EXT_QUERY).nth(sel_idx)
            if _click_select_option(page, dd, label, debug_name=debug_name):
                return True
        except Exception as e:
            print(f"       [_click_or_fallback:{debug_name}] native click 例外: {e}")
        try:
            return _select_by_label(
                page,
                f"document.querySelectorAll({legacy_query})[{sel_idx}]",
                label,
                debug_name=f"{debug_name}_fallback",
            )
        except Exception as e:
            print(f"       [_click_or_fallback:{debug_name}] fallback 例外: {e}")
            return False

    def _click_section_radio(section_title, label_text):
        """section スコープ内のラジオを Playwright native click で選択する。

        旧実装は JS の el.click() だったが、2026-06-10 実走で
        「発送地=国内をクリックしたはずなのに海外用エリア select が
        render されたまま」= React state が更新されていないことを確認
        (CLAUDE.md §3 の罠と同じ)。さらに span 候補への前方一致だったため
        '国内' が '国内海外' コンテナに誤マッチしていた。

        新実装:
          1. JS で section 範囲内の input[type=radio] を走査し、label テキスト
             が完全一致するものに data 属性をタグ付け (_tag_variation_rows 方式)
          2. Playwright locator でタグを本物クリック
          3. _radio_checked で state 反映を検証、未反映なら force click で再試行
        """
        TAG = "data-bma-radio-target"
        try:
            found = page.evaluate(f"""(function(){{
                var keyword = {json.dumps(section_title)};
                var target = {json.dumps(label_text)};
                document.querySelectorAll('[{TAG}]').forEach(function(el){{ el.removeAttribute('{TAG}'); }});
                var titles = document.querySelectorAll('.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt');
                var startIdx = -1;
                for (var i = 0; i < titles.length; i++) {{
                    var t = (titles[i].textContent || '').trim();
                    if (t === keyword || t.indexOf(keyword) === 0) {{ startIdx = i; break; }}
                }}
                if (startIdx < 0) return 'no_title';
                var startEl = titles[startIdx];
                var endEl = titles[startIdx + 1] || null;
                function inRange(el) {{
                    var aft = !!(startEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
                    var bef = !endEl || !!(endEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING);
                    return aft && bef;
                }}
                var radios = document.querySelectorAll('input[type="radio"]');
                for (var j = 0; j < radios.length; j++) {{
                    var r = radios[j];
                    if (!inRange(r)) continue;
                    var lb = r.closest('label')
                        || (r.id ? document.querySelector('label[for="' + r.id + '"]') : null)
                        || r.parentElement;
                    var txt = (lb && lb.textContent) ? lb.textContent.trim() : '';
                    if (txt === target) {{
                        (lb || r).setAttribute('{TAG}', '1');
                        (lb || r).scrollIntoView({{block: 'center'}});
                        return 'tagged';
                    }}
                }}
                return 'no_radio';
            }})()""")
            if found != "tagged":
                print(f"       [_click_section_radio:{section_title}] {label_text}: {found}")
                return False
            page.locator(f"[{TAG}]").first.click(timeout=3000)
            time.sleep(0.4)
            if _radio_checked(section_title, label_text):
                return True
            # 1 回だけ force click で再試行 (overlay 等でクリックが吸われるケース)
            page.locator(f"[{TAG}]").first.click(timeout=3000, force=True)
            time.sleep(0.4)
            checked = _radio_checked(section_title, label_text)
            if not checked:
                print(f"       [_click_section_radio:{section_title}] {label_text}: クリック後も checked にならず")
            return checked
        except Exception as e:
            print(f"       [_click_section_radio:{section_title}] 例外: {e}")
        return False

    # 注: _select_label_anywhere (全域 select 走査) は 2026-06-10 に撤去。
    # 大量リトライでページ状態を乱す副作用が利益を上回った (HANDOFF 参照)。

    def _radio_checked(section_title, label_text):
        try:
            return bool(page.evaluate(f"""(function(){{
                var keyword = {json.dumps(section_title)};
                var target = {json.dumps(label_text)};
                var titles = document.querySelectorAll('.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt');
                var startIdx = -1;
                for (var i = 0; i < titles.length; i++) {{
                    var t = (titles[i].textContent || '').trim();
                    if (t === keyword || t.indexOf(keyword) === 0) {{ startIdx = i; break; }}
                }}
                if (startIdx < 0) return false;
                var startEl = titles[startIdx];
                var endEl = titles[startIdx + 1] || null;
                function inRange(el) {{
                    var aft = !!(startEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
                    var bef = !endEl || !!(endEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING);
                    return aft && bef;
                }}
                var radios = document.querySelectorAll('input[type="radio"]');
                for (var j = 0; j < radios.length; j++) {{
                    var r = radios[j];
                    if (!inRange(r)) continue;
                    if (!r.checked) continue;
                    var lb = r.closest('label') || (r.id ? document.querySelector('label[for="'+r.id+'"]') : null) || r.parentElement;
                    var txt = (lb && lb.textContent) ? lb.textContent.trim() : '';
                    if (txt === target || txt.indexOf(target) === 0) return true;
                }}
                return false;
            }})()"""))
        except Exception:
            return False

    def _find_select_with_option(sel_indices, option_label, debug_name):
        # 失敗時の診断用に、開いた各 select の先頭オプションを記録する。
        # (sel_indices は範囲内の数件のみ。62 件スキャンのような暴走はしない)
        seen = {}
        for idx in sel_indices[:8]:
            try:
                dd = page.locator(EXT_QUERY).nth(idx)
                dd.scroll_into_view_if_needed(timeout=1500)
                dd.click(timeout=2500)
                page.wait_for_selector('.Select-menu-outer .Select-option, [role="listbox"] [role="option"]', timeout=2000)
                opts = page.locator('.Select-menu-outer .Select-option, [role="listbox"] [role="option"]')
                cnt = min(opts.count(), 30)
                vals = []
                for i in range(cnt):
                    vals.append((opts.nth(i).text_content() or '').strip())
                seen[idx] = vals[:8]
                try:
                    page.locator('body').click(timeout=1000)
                except Exception:
                    pass
                if any((v == option_label) or (option_label in v) for v in vals):
                    return idx
            except Exception as e:
                seen[idx] = f"<open失敗: {type(e).__name__}>"
                try:
                    page.locator('body').click(timeout=800)
                except Exception:
                    pass
                continue
        print(f"       [_find_select_with_option:{debug_name}] '{option_label}' を含む select 不在: {sel_indices}")
        # 各 select の中身を出す (次セッションでの真因特定用、CLAUDE.md §12 の罠)
        for idx, vals in seen.items():
            print(f"          [DIAG] select[{idx}] options(先頭): {vals}")
        return None

    # --- 買付地: 先に海外ラジオを押す ---
    if _click_section_radio("買付地", "海外"):
        results.append("買付地_海外選択")
    time.sleep(0.8)

    info = _find_section_selects(page, "買付地")
    sel_indices = info.get("selects", []) if isinstance(info, dict) and not info.get("error") else []

    buy_continent_ok = False
    buy_country_ok = False
    buy_cont_idx = _find_select_with_option(sel_indices, "ヨーロッパ", "買付地_大陸")

    if buy_cont_idx is not None:
        buy_continent_ok = _click_or_fallback(buy_cont_idx, "ヨーロッパ", "買付地_大陸", legacy_query=json.dumps(EXT_QUERY))
    if (not buy_continent_ok) and (buy_cont_idx is not None):
        buy_continent_ok = _click_or_fallback(buy_cont_idx, "ヨーロッパ", "買付地_大陸_retry", legacy_query=json.dumps(EXT_QUERY))

    # 大陸選択後に国ドロップダウンが描画されるケースがあるため、ここで再探索
    buy_country_idx = None
    if buy_continent_ok:
        time.sleep(0.5)
        info = _find_section_selects(page, "買付地")
        sel_indices = info.get("selects", []) if isinstance(info, dict) and not info.get("error") else sel_indices
        buy_country_idx = _find_select_with_option(sel_indices, purchase_country, "買付地_国")

    if buy_country_idx is not None:
        buy_country_ok = _click_or_fallback(buy_country_idx, purchase_country, "買付地_国", legacy_query=json.dumps(EXT_QUERY))
    if (not buy_country_ok) and (buy_country_idx is not None):
        buy_country_ok = _click_or_fallback(buy_country_idx, purchase_country, "買付地_国_retry", legacy_query=json.dumps(EXT_QUERY))

    if buy_continent_ok:
        results.append("買付地_大陸=ヨーロッパ")
    if buy_country_ok:
        results.append(f"買付地_国={purchase_country}")
    if not buy_country_ok:
        results.append(f"買付地_未設定(selects={sel_indices})")

    # --- 発送地: 国内ラジオ選択 → 都道府県 ---
    domestic_clicked = _click_section_radio("発送地", "国内")
    if domestic_clicked:
        results.append("発送地_国内選択")
    time.sleep(0.8)

    def _scroll_section_into_view(keyword):
        """セクション見出しを画面中央に出し、実ホイールで IntersectionObserver を発火させる。"""
        try:
            page.evaluate(f"""(function(){{
                var titles = document.querySelectorAll('.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt');
                for (var i = 0; i < titles.length; i++) {{
                    var t = (titles[i].textContent || '').trim();
                    if (t === {json.dumps(keyword)} || t.indexOf({json.dumps(keyword)}) === 0) {{
                        titles[i].scrollIntoView({{block: 'center'}});
                        return true;
                    }}
                }}
                return false;
            }})()""")
            page.mouse.wheel(0, 80)
            time.sleep(0.15)
            page.mouse.wheel(0, -80)
        except Exception:
            pass

    # 都道府県 select は「国内」ラジオのクリック後に遅延描画される。
    # 2026-06-10 実走: radio 直後の即時探索では section 内に select が存在せず
    # (DUMP: section_html_length=269 で 国内海外 field のみ)、発送地が未設定の
    # まま保存されていた。section を視界に入れつつ出現を最大 6 秒ポーリングする。
    _scroll_section_into_view("発送地")
    sel2 = []
    for _ in range(12):
        info2 = _find_section_selects(page, "発送地")
        sel2 = info2.get("selects", []) if isinstance(info2, dict) and not info2.get("error") else []
        if sel2:
            break
        time.sleep(0.5)
        _scroll_section_into_view("発送地")

    ship_ok = False
    ship_idx = _find_select_with_option(sel2, ship_prefecture, "発送地_都道府県")
    if ship_idx is not None:
        ship_ok = _click_or_fallback(ship_idx, ship_prefecture, "発送地_都道府県", legacy_query=json.dumps(EXT_QUERY))
    if (not ship_ok) and (ship_idx is not None):
        ship_ok = _click_or_fallback(ship_idx, ship_prefecture, "発送地_都道府県_retry", legacy_query=json.dumps(EXT_QUERY))

    # 注: 旧実装にあった「全域 select 走査フォールバック」は撤去した。
    # 2026-06-10 実走で 62 回スキャン × 179 回リトライを発生させ、ページ状態を
    # 乱して item3 の買付地まで巻き添えで壊した。根本原因は radio の React
    # state 未更新 (上の _click_section_radio native 化で対処) であり、
    # 全域走査は症状を悪化させるだけだった。
    if ship_ok:
        results.append(f"発送地={ship_prefecture}")
    else:
        results.append(f"発送地_未設定(selects={sel2})")
        # 読み取りのみの全 select インベントリ (クリックしない = 安全)。
        # 都道府県 select が「範囲外に描画」されているのか「そもそも native
        # select でない (react-select で値ラベル='選択してください')」のかを
        # 切り分ける。次セッションの発送地修正の決め手にする。
        try:
            inv = page.evaluate("""(function(){
                var sels = document.querySelectorAll('.Select, .bmm-c-select, select, [role="combobox"]');
                var out = [];
                for (var i = 0; i < sels.length && i < 40; i++) {
                    var s = sels[i];
                    var lbl = s.querySelector('.Select-value-label, .bmm-c-select__value, .Select-placeholder, .bmm-c-select__placeholder');
                    var val = lbl ? (lbl.textContent || '').trim() : (s.value || '');
                    // native <select> なら option をいくつか読める (開かずに)
                    var opts = '';
                    if (s.tagName === 'SELECT') {
                        var o = [];
                        for (var k = 0; k < s.options.length && k < 6; k++) o.push(s.options[k].text.trim());
                        opts = o.join('/');
                    }
                    var r = s.getBoundingClientRect();
                    out.push(i + ':val=' + val.slice(0,16) + (opts ? ' opts=[' + opts + ']' : '') +
                             ' tag=' + s.tagName + ' vis=' + (r.width>0 && r.height>0 ? 'Y':'N'));
                }
                return out;
            })()""")
            print(f"       [DIAG-発送地] 全 select インベントリ ({len(inv)}件、読取のみ):")
            for line in inv:
                print(f"          {line}")
        except Exception as e:
            print(f"       [DIAG-発送地] インベントリ取得失敗: {e}")

    # 最終整合チェック（逆転事故の防止）
    if not _radio_checked("買付地", "海外"):
        if _click_section_radio("買付地", "海外"):
            results.append("買付地_海外_再補正")
            time.sleep(0.4)
            if buy_cont_idx is not None:
                _click_or_fallback(buy_cont_idx, "ヨーロッパ", "買付地_大陸_fix", legacy_query=json.dumps(EXT_QUERY))
            if buy_country_idx is not None:
                _click_or_fallback(buy_country_idx, purchase_country, "買付地_国_fix", legacy_query=json.dumps(EXT_QUERY))

    if not _radio_checked("発送地", "国内"):
        if _click_section_radio("発送地", "国内"):
            results.append("発送地_国内_再補正")
            time.sleep(0.4)
            if ship_idx is not None:
                _click_or_fallback(ship_idx, ship_prefecture, "発送地_都道府県_fix", legacy_query=json.dumps(EXT_QUERY))

    results.append(f"dump_keys_buy={_dump_keys(buy_dump)}")
    results.append(f"dump_keys_ship={_dump_keys(ship_dump)}")
    print(f"    🌍 地域: {results}")


def _scroll_through_page(page, chunks=12, step_px=500, pause=0.25):
    """ページを上から下まで段階的にスクロールし、全ての lazy render セクションを
    DOM に出現させる。スクロール後は元の位置には戻さない。
    """
    try:
        page.evaluate("window.scrollTo({top: 0, behavior: 'auto'})")
    except Exception:
        pass
    time.sleep(0.3)
    for _ in range(chunks):
        try:
            page.mouse.wheel(0, step_px)
        except Exception:
            page.evaluate(f"window.scrollBy(0, {step_px})")
        time.sleep(pause)


def _ensure_rendered(page, css_selector, max_scrolls=15, step_px=600):
    """BUYMA の遅延描画フォームで、指定 CSS セレクタが DOM に現れるまで
    ホイールスクロールを繰り返す。

    返り値: True なら描画された、False なら最大回数でも出なかった。
    """
    if page.evaluate(f"!!document.querySelector({json.dumps(css_selector)})"):
        return True
    for _ in range(max_scrolls):
        try:
            page.mouse.wheel(0, step_px)
        except Exception:
            page.evaluate(f"window.scrollBy(0, {step_px})")
        time.sleep(0.35)
        if page.evaluate(f"!!document.querySelector({json.dumps(css_selector)})"):
            return True
    return False


def set_sku(page, sku, identify_memo=""):
    """品番 (SKU) + 識別メモ (非公開) を入力する。

    BUYMA の品番セクションは遅延描画されるため、まずページ全体をスクロールして
    全セクションを DOM に出現させてから、複数セレクタで品番 input を探す。
    """
    if not sku:
        print("    🔖 品番: (なし)")
        return

    # まずページ全体を舐めるように下スクロールして lazy render を全部起こす
    _scroll_through_page(page)

    # 品番 input を複数戦略で探す:
    #   戦略A: .sell-model-number-table クラス
    #   戦略B: placeholder が SKU サンプル形式
    #   戦略C: placeholder が既知の特定文字列 "1BD075" から始まる
    result = page.evaluate(f"""(function(){{
        var sku = {json.dumps(sku)};
        var memo = {json.dumps(identify_memo)};
        var SKU_RE = /^[A-Z0-9][A-Z0-9_\\-]{{5,}}$/;

        // 全 bmm-c-text-field の placeholder を dump（診断用）
        var bmmFields = document.querySelectorAll('input.bmm-c-text-field');
        var phDump = [];
        for (var i = 0; i < bmmFields.length && phDump.length < 40; i++) {{
            var ph = bmmFields[i].placeholder || bmmFields[i].getAttribute('placeholder') || '';
            if (ph) phDump.push(ph.slice(0, 40));
        }}

        var skuInput = null;

        // 戦略A: .sell-model-number-table
        var table = document.querySelector('.sell-model-number-table');
        if (table) {{
            var tableInputs = table.querySelectorAll('input[type="text"], input:not([type])');
            if (tableInputs.length >= 1) {{
                skuInput = tableInputs[0];
                window.__si(skuInput, sku);
                if (tableInputs.length >= 2 && memo) {{
                    window.__si(tableInputs[1], memo);
                    return ['品番=table_idx0', '識別メモ=table_idx1'];
                }}
                return ['品番=table_idx0'];
            }}
        }}

        // 戦略B: placeholder が SKU 正規表現にマッチ
        var all = document.querySelectorAll('input.bmm-c-text-field, input[type="text"], input:not([type])');
        var skuInputs = [];
        for (var i = 0; i < all.length; i++) {{
            var ph2 = all[i].placeholder || all[i].getAttribute('placeholder') || '';
            if (ph2 && SKU_RE.test(ph2)) {{
                skuInputs.push(all[i]);
            }}
        }}
        if (skuInputs.length >= 1) {{
            window.__si(skuInputs[0], sku);
            var ret = ['品番=placeholder_match'];
            if (skuInputs.length >= 2 && memo) {{
                window.__si(skuInputs[1], memo);
                ret.push('識別メモ=placeholder_idx1');
            }} else if (memo) {{
                var tr = skuInputs[0].closest('tr');
                if (tr) {{
                    var rowInputs = tr.querySelectorAll('input[type="text"], input:not([type])');
                    for (var k = 0; k < rowInputs.length; k++) {{
                        if (rowInputs[k] !== skuInputs[0]) {{
                            window.__si(rowInputs[k], memo);
                            ret.push('識別メモ=row_sibling');
                            break;
                        }}
                    }}
                }}
            }}
            return ret;
        }}

        // 戦略C: 見つからない場合は全 bmm-c-text-field の placeholder を dump（診断用）
        return {{not_found: true, bmm_field_count: bmmFields.length, placeholders: phDump}};
    }})()""")
    print(f"    🔖 品番: {sku} ({result})")


def set_season(page, season):
    """シーズンドロップダウン（例: AW25, SS24）を設定する。

    BUYMA のシーズン欄は react-select のドロップダウンで、候補は
    '2024 AW' / '2025 SS' / '2025 AW' のような表記が多い。
    仕入先の 'AW25' → '2025 AW' に正規化して選択を試みる。
    """
    if not season:
        return
    s = season.strip().upper()
    # "AW25" → year=2025, half="AW" のように分解
    import re as _re
    m = _re.match(r"([A-Z]{2,3})[\s\-]?(\d{2,4})", s)
    if not m:
        # "25AW" 形式にも対応
        m = _re.match(r"(\d{2,4})[\s\-]?([A-Z]{2,3})", s)
        if m:
            year_raw, half = m.group(1), m.group(2)
        else:
            print(f"    🗓️ シーズン: パース失敗 ({season})")
            return
    else:
        half, year_raw = m.group(1), m.group(2)
    year = "20" + year_raw[-2:] if len(year_raw) <= 2 else year_raw
    # FW は BUYMA 側では AW と同義。AW 表記に統一する
    if half == "FW":
        half = "AW"
    # 候補ラベルは複数パターンを試す(BUYMA は AW 年跨ぎ "2025-2026 AW" を使う)
    candidates = []
    if half == "AW":
        try:
            next_year = str(int(year) + 1)
            candidates.extend([
                f"{year}-{next_year} AW",
                f"{year}-{next_year}AW",
                f"{year}/{next_year} AW",
                f"{year}/{next_year}AW",
            ])
        except ValueError:
            pass
    candidates.extend([
        f"{year} {half}", f"{year}{half}",
        f"{half} {year}", f"{half}{year}",
        f"{year}年{half}",
    ])

    # シーズン見出しの近傍で .Select を特定
    # BUYMA は「シーズン」見出しを <p class="bmm-c-summary__ttl"> で表示し、
    # dropdown は兄弟の .bmm-l-col-9 に入っている(bmm-l-col-3 と bmm-l-col-9
    # が横並びの 2 カラムレイアウト)。近い親だけ見ると dropdown を見逃すため、
    # 見出し text="シーズン" 厳密一致要素から上に登って最初に .Select を含む
    # 祖先で探す。
    idx = page.evaluate("""(function(){
        var titles = document.querySelectorAll('p.bmm-c-summary__ttl, .bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt, label');
        for (var i = 0; i < titles.length; i++) {
            var t = (titles[i].textContent || '').trim();
            if (t !== 'シーズン') continue;
            var cur = titles[i].parentElement;
            for (var hop = 0; hop < 8 && cur && cur !== document.body; hop++) {
                var sels = cur.querySelectorAll('.Select, .bmm-c-select');
                if (sels.length > 0) {
                    var all = document.querySelectorAll('.Select, .bmm-c-select');
                    return Array.from(all).indexOf(sels[0]);
                }
                cur = cur.parentElement;
            }
        }
        return -1;
    })()""")
    if idx is None or idx < 0:
        print(f"    🗓️ シーズン: ドロップダウンが見つからない ({season})")
        return

    dd = page.locator('.Select, .bmm-c-select').nth(idx)
    for cand in candidates:
        if _click_select_option(page, dd, cand, debug_name=f"シーズン[{cand}]"):
            print(f"    🗓️ シーズン: {cand}")
            return
    print(f"    🗓️ シーズン: 候補該当なし ({season})")


def set_theme(page):
    """テーマ欄を既定値(指定なし)に設定する。未設定だと保存失敗するケースに対応。"""
    info = _find_section_selects(page, "テーマ")
    if isinstance(info, dict) and info.get("error"):
        print("    🧩 テーマ: 見出し未検出")
        return
    sel_indices = info.get("selects", []) if isinstance(info, dict) else []
    if not sel_indices:
        print("    🧩 テーマ: Select未検出")
        return

    dd = page.locator(_SECTION_SELECT_QUERY).nth(sel_indices[0])
    for cand in ["指定なし", "指定なしの場合"]:
        if _click_select_option(page, dd, cand, debug_name=f"テーマ[{cand}]"):
            print(f"    🧩 テーマ: {cand}")
            return
    print("    🧩 テーマ: 候補該当なし")


def set_tags(page, tags):
    """BUYMA 出品フォームのタグモーダルを開いて指定タグをチェック → 保存する。

    tags: 付与したいタグ文字列のリスト(例 ["レザー(本革)", "スエード"])。
          空リストなら何もしない。
    タグ UI は「一覧からタグを選択」リンクを押すとダイアログが開き、
    <label class="bmm-c-checkbox--tag"> に <span class="bmm-c-checkbox__body">
    でタグ名が表示されている。チェック後「選択したタグを設定」ボタンで確定。
    """
    if not tags:
        print(f"    🏷️ タグ: 付与対象なし")
        return

    _scroll_through_page(page, chunks=8)

    # 1) モーダルを開く
    open_sel = 'a:has-text("一覧からタグを選択"), button:has-text("一覧からタグを選択")'
    try:
        opener = page.locator(open_sel).first
        opener.scroll_into_view_if_needed(timeout=2000)
        opener.click(timeout=3000)
    except Exception as e:
        print(f"    🏷️ タグモーダル open 失敗: {e}")
        return

    # モーダル(チェックボックス群)の出現を待つ
    try:
        page.wait_for_selector(
            'label.bmm-c-checkbox--tag, .sell-tag-group__body',
            timeout=5000, state="visible",
        )
        time.sleep(0.3)
    except Exception as e:
        print(f"    🏷️ タグモーダルが開かない: {e}")
        return

    # 2) 各タグのチェックボックスを click
    results = []
    for tag_text in tags:
        # tags.json の半角カッコと画面の全角カッコの不一致を避けるため
        # ()（）[]［］ 等と前後空白を除いた文字列で比較する
        outcome = page.evaluate(f"""(function(){{
            var target = {json.dumps(tag_text)};
            function norm(s) {{
                return (s || '').trim()
                    .replace(/[（]/g, '(')
                    .replace(/[）]/g, ')')
                    .replace(/[［]/g, '[')
                    .replace(/[］]/g, ']')
                    .replace(/\\s+/g, '');
            }}
            var t = norm(target);
            var labels = document.querySelectorAll('label.bmm-c-checkbox--tag');
            for (var i = 0; i < labels.length; i++) {{
                var body = labels[i].querySelector('.bmm-c-checkbox__body');
                if (!body) continue;
                if (norm(body.textContent) !== t) continue;
                var inp = labels[i].querySelector('input[type="checkbox"]');
                if (!inp) return 'no_input';
                if (inp.checked) return 'already';
                labels[i].click();
                return 'clicked';
            }}
            return 'not_found';
        }})()""")
        results.append(f"{tag_text}={outcome}")
        time.sleep(0.15)

    # 3) 「選択したタグを設定」で確定
    save_sel = 'button:has-text("選択したタグを設定")'
    try:
        page.locator(save_sel).first.click(timeout=3000)
        time.sleep(0.5)
    except Exception as e:
        print(f"    🏷️ タグ保存ボタン失敗: {e}")
        return

    print(f"    🏷️ タグ: {results}")


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


def _click_select_option(page, dropdown_locator, option_label, debug_name=""):
    """Playwright locator 経由で任意の react-select を開いて option をクリックする。

    dropdown_locator: page.locator(...) で取得した .Select 要素
    option_label: 選びたい option のテキスト（完全一致 or 部分一致）
    """
    try:
        dropdown_locator.scroll_into_view_if_needed(timeout=2000)
        dropdown_locator.click(timeout=3000)
    except Exception as e:
        print(f"       [_click_select_option:{debug_name}] ドロップダウン開けず: {e}")
        return False
    # オプション描画待ち
    try:
        page.wait_for_selector(
            ".Select-menu-outer .Select-option, [role=\"listbox\"] [role=\"option\"]",
            timeout=3000,
            state="visible",
        )
    except Exception:
        print(f"       [_click_select_option:{debug_name}] オプション未描画")
        return False
    # 完全一致優先 → 部分一致
    OPT_SEL = '.Select-menu-outer .Select-option, [role="listbox"] [role="option"]'
    opts = page.locator(OPT_SEL)
    count = opts.count()
    for i in range(count):
        try:
            t = (opts.nth(i).text_content() or "").strip()
        except Exception:
            continue
        if t == option_label:
            try:
                opts.nth(i).click(timeout=2000)
                time.sleep(0.4)
                return True
            except Exception:
                pass
    for i in range(count):
        try:
            t = (opts.nth(i).text_content() or "").strip()
        except Exception:
            continue
        if option_label in t:
            try:
                opts.nth(i).click(timeout=2000)
                time.sleep(0.4)
                return True
            except Exception:
                pass
    dump = [((opts.nth(i).text_content() or "").strip())[:30] for i in range(min(count, 15))]
    print(f"       [_click_select_option:{debug_name}] '{option_label}' 候補なし: {dump}")
    # 閉じる
    try: page.locator("body").click(timeout=1000)
    except Exception: pass
    return False


def _click_tab_by_name(page, tab_name):
    """[role=\"tab\"] の中から textContent が tab_name に一致するものをクリックし、
    aria-controls で対応する tabpanel のCSSセレクタ("#id") を返す。
    見つからない場合は None。
    """
    panel_id = page.evaluate(f"""(function(){{
        var target = {json.dumps(tab_name)};
        var tabs = document.querySelectorAll('[role="tab"]');
        for (var i = 0; i < tabs.length; i++) {{
            if (tabs[i].textContent.trim() === target) {{
                tabs[i].click();
                return tabs[i].getAttribute('aria-controls');
            }}
        }}
        return null;
    }})()""")
    time.sleep(0.8)
    return ("#" + panel_id) if panel_id else None


def set_color(page, color_name="マルチカラー", color_label=None):
    """色タブを開いて 色の系統 + 色名 の両方を設定する。

    color_name: 色の系統ドロップダウンのラベル（BUYMA内の分類。「ブラック」等の日本語）
    color_label: 色名テキスト欄の自由記述（仕入先の表記 "Black" などをそのまま使うと便利）。
                 未指定時は color_name と同じ値を使う。
    """
    if color_label is None:
        color_label = color_name

    # 色・サイズ セクションを lazy render から起こす
    _scroll_through_page(page, chunks=8)
    # 色タブ周辺までスクロールして表示させる
    page.evaluate("""(function(){
        var tabs = document.querySelectorAll('[role="tab"]');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === '色') {
                tabs[i].scrollIntoView({block: 'center'});
                return;
            }
        }
    })()""")
    time.sleep(0.5)

    # 「色」タブをクリックして active panel を取得
    panel_sel = _click_tab_by_name(page, "色")
    if not panel_sel:
        print(f"    🎨 色: 色タブが見つからない")
        return

    # 1) 色の系統ドロップダウン
    panel = page.locator(panel_sel)
    color_dd = panel.locator('.Select, .bmm-c-custom-select').first

    # 診断: ドロップダウンを一旦開いて候補を全件 dump し、そのまま閉じる
    # (成否に関わらず実行する。毎回 1回だけロギングして COLOR_JA_MAP 調整の手がかりにする)
    page.evaluate(f"""(function(){{
        var p = document.querySelector({json.dumps(panel_sel)});
        if (!p) return;
        var sel = p.querySelector('.Select, .bmm-c-custom-select');
        if (!sel) return;
        var ctrl = sel.querySelector('.Select-control');
        if (ctrl) ctrl.click();
    }})()""")
    time.sleep(0.4)
    peek = page.evaluate("""
        Array.from(document.querySelectorAll(
            '.Select-menu-outer .Select-option, [role=\"listbox\"] [role=\"option\"]'
        )).slice(0, 40).map(function(o){ return o.textContent.trim().slice(0, 30); })
    """)
    print(f"       [色の系統] options ({len(peek)}): {peek}")
    # 閉じる（次のクリック処理のため）
    try:
        page.locator('body').click(position={'x': 5, 'y': 5}, timeout=500)
    except Exception:
        pass
    time.sleep(0.3)

    # color_name そのまま失敗時はマルチカラーにフォールバック
    candidates = [color_name]
    if color_name not in ("マルチカラー",):
        candidates.append("マルチカラー")
    ok = False
    for cand in candidates:
        if _click_select_option(page, color_dd, cand, debug_name=f"色の系統[{cand}]"):
            color_name = cand
            ok = True
            break

    # 2) 色名テキスト入力
    result = page.evaluate(f"""(function(){{
        var p = document.querySelector({json.dumps(panel_sel)});
        if (!p) return 'no_panel';
        var inputs = p.querySelectorAll('input[type="text"], input:not([type])');
        for (var i = 0; i < inputs.length; i++) {{
            var el = inputs[i];
            var ph = (el.getAttribute('placeholder') || '').toLowerCase();
            if (ph.indexOf('ブランド') !== -1) continue;
            window.__si(el, {json.dumps(color_label)});
            return 'set idx=' + i;
        }}
        return 'no_input';
    }})()""")
    print(f"    🎨 色: {color_name} (ラベル={color_label!r} {result} panel={panel_sel})")


def set_size_and_stock(
    page,
    product_type="",
    available_sizes_csv="",
    fallback_sizes_csv="",
    stock_qty_per_size=1,
):
    """サイズタブを開いて サイズ・在庫を設定する。

    product_type を見て:
      - CLOTHING / FOOTWEAR → 'バリエーションあり' で複数サイズを登録
      - BAGS / ACCESSORIES / その他 → 'バリエーションなし' で単一サイズ登録

    available_sizes_csv: 在庫ありサイズ（カンマ区切り、優先）
    fallback_sizes_csv:  取れなかった場合の全サイズ
    """
    category = classify_size_category(product_type)
    sizes_str = (available_sizes_csv or "").strip() or (fallback_sizes_csv or "").strip()
    sizes_list = [s.strip() for s in sizes_str.split(",") if s.strip()]

    # サイズ セクションを lazy render から起こす
    _scroll_through_page(page, chunks=8)
    page.evaluate("""(function(){
        var tabs = document.querySelectorAll('[role="tab"]');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].textContent.trim() === 'サイズ') {
                tabs[i].scrollIntoView({block: 'center'});
                return;
            }
        }
    })()""")
    time.sleep(0.5)

    panel_sel = _click_tab_by_name(page, "サイズ")
    if not panel_sel:
        print(f"    📦 サイズタブが見つからない")
        return

    if category == "variation" and sizes_list:
        _set_size_variations(page, panel_sel, sizes_list, product_type, stock_qty_per_size)
    else:
        # 単一サイズ (バッグ・アクセ・サイズ情報なし)
        first_size = sizes_list[0] if sizes_list else ""
        jp_size = map_size_to_jp_reference(first_size, product_type) if first_size else "指定なし"
        size_name = format_size_name_for_listing(first_size, product_type) or (first_size or "FREE")
        _set_size_single(page, panel_sel, jp_size, size_name, stock_qty_per_size)


def _set_size_single(page, panel_sel, jp_size, size_name, stock_qty):
    """バリエーションなし：単一サイズ + 在庫数量。"""
    panel = page.locator(panel_sel)

    # 1) バリエーション: なし
    variation_dd = panel.locator('.Select').first
    _click_select_option(page, variation_dd, "バリエーションなし", debug_name="バリエーション")

    # 1b) サイズ名テキスト欄
    page.evaluate(f"""(function(){{
        var p = document.querySelector({json.dumps(panel_sel)});
        if (!p) return 'no_panel';
        var inputs = p.querySelectorAll('input[type="text"], input:not([type])');
        for (var i = 0; i < inputs.length; i++) {{
            var el = inputs[i];
            var ph = (el.getAttribute('placeholder') || '');
            if (ph.indexOf('ブランド') !== -1) continue;
            window.__si(el, {json.dumps(size_name)});
            return 'set idx=' + i;
        }}
        return 'no_input';
    }})()""")

    # 2) 参考日本サイズ: 「指定なし」を表示している .Select を探す
    target_dd_js = """(function(){
        var all = document.querySelectorAll('.Select, .bmm-c-custom-select');
        for (var i = 0; i < all.length; i++) {
            var lbl = all[i].querySelector('.Select-value-label, .Select-placeholder');
            var t = lbl ? (lbl.textContent || '').trim() : '';
            if (t === '指定なし') {
                return i;
            }
        }
        return -1;
    })()"""
    idx = page.evaluate(target_dd_js)
    if idx is not None and idx >= 0:
        ref_size_dd = page.locator('.Select, .bmm-c-custom-select').nth(idx)
        _click_select_option(page, ref_size_dd, jp_size, debug_name="参考日本サイズ")
    else:
        print(f"       [参考日本サイズ] '指定なし' dropdown が見つからない")

    _set_stock_status_and_qty(page, per_row_qty=stock_qty, total_qty=stock_qty)
    print(f"    📦 サイズ/在庫(単一): size={size_name} jp={jp_size} qty={stock_qty}")


def _count_variation_rows(page, panel_sel):
    """panel 内の「input を持つ <tr>」（= データ行）の件数を数える。"""
    return page.evaluate(f"""(function(){{
        var p = document.querySelector({json.dumps(panel_sel)});
        if (!p) return 0;
        var n = 0;
        p.querySelectorAll('table tr').forEach(function(r){{
            if (r.querySelector('input[type="text"], input:not([type])')) n++;
        }});
        return n;
    }})()""") or 0


def _tag_variation_rows(page, panel_sel):
    """input を持つ <tr> に data-bma-row-idx="N" を振って、行 N の locator を安定化する。"""
    return page.evaluate(f"""(function(){{
        var p = document.querySelector({json.dumps(panel_sel)});
        if (!p) return 0;
        var idx = 0;
        p.querySelectorAll('table tr').forEach(function(r){{
            if (r.querySelector('input[type="text"], input:not([type])')) {{
                r.setAttribute('data-bma-row-idx', String(idx));
                idx++;
            }}
        }});
        return idx;
    }})()""") or 0


def _set_size_variations(page, panel_sel, sizes_list, product_type, stock_qty_per_size):
    """バリエーションあり：複数サイズ行を追加して埋める。

    BUYMA の出品フォームは React 製で、動的に行が追加される。
    選択後、初期状態で 1行目が存在する前提で、2行目以降は
    「+ 新しいサイズを追加」ボタンを押す。
    """
    panel = page.locator(panel_sel)

    # 1) バリエーション: あり
    variation_dd = panel.locator('.Select').first
    _click_select_option(page, variation_dd, "バリエーションあり", debug_name="バリエーション")
    time.sleep(0.6)

    rows_to_fill = len(sizes_list)
    initial_rows = _count_variation_rows(page, panel_sel)
    print(f"    📦 バリエーションあり: {rows_to_fill}サイズ {sizes_list} (初期行数={initial_rows})")

    # 2) 行数を揃える: 「+ 新しいサイズを追加」を押して期待行数に到達させる
    add_btn_sel = (
        'button:has-text("新しいサイズを追加"), '
        'a:has-text("新しいサイズを追加"), '
        '[role="button"]:has-text("新しいサイズを追加")'
    )
    for i in range(1, rows_to_fill):
        expected = i + 1
        clicked = False
        for attempt in range(2):
            try:
                page.locator(add_btn_sel).first.scroll_into_view_if_needed(timeout=1500)
                page.locator(add_btn_sel).first.click(timeout=2500)
                clicked = True
            except Exception as e:
                print(f"    📦 行追加ボタン click 失敗 (row={expected}, attempt={attempt+1}): {e}")
            time.sleep(0.5)
            if _count_variation_rows(page, panel_sel) >= expected:
                break
        actual = _count_variation_rows(page, panel_sel)
        if actual < expected:
            print(f"    📦 ⚠️ 行追加が反映されず (期待={expected}, 実際={actual}, click={clicked}) → 以降スキップ")
            rows_to_fill = actual
            sizes_list = sizes_list[:actual]
            break

    final_rows = _count_variation_rows(page, panel_sel)
    tagged = _tag_variation_rows(page, panel_sel)
    print(f"    📦 サイズ行: 最終行数={final_rows} tagged={tagged} fill予定={rows_to_fill}")

    # 3) 各行を埋める
    for idx, raw_size in enumerate(sizes_list):
        size_name = format_size_name_for_listing(raw_size, product_type) or raw_size
        jp_size = map_size_to_jp_reference(raw_size, product_type)
        filled = _fill_variation_row(page, panel_sel, idx, size_name, jp_size)
        print(f"    📦 row[{idx}]: size_name={size_name!r} jp={jp_size!r} → {filled}")

    # 4) 在庫ステータスと合計数量
    _set_stock_status_and_qty(
        page,
        per_row_qty=stock_qty_per_size,
        total_qty=rows_to_fill * stock_qty_per_size,
    )


def _fill_variation_row(page, panel_sel, row_idx, size_name, jp_size):
    """バリエーションあり の row_idx 番目行に サイズ名 と 参考日本サイズ をセットする。

    _tag_variation_rows() で data-bma-row-idx 属性が振られている前提。
    JS セット と Playwright locator を同じ属性で引くため行ずれが起きない。
    """
    row_sel = f'{panel_sel} tr[data-bma-row-idx="{row_idx}"]'

    # 1) サイズ名 input
    name_result = page.evaluate(f"""(function(){{
        var r = document.querySelector({json.dumps(row_sel)});
        if (!r) return 'no_row';
        var inp = r.querySelector('input[type="text"], input:not([type])');
        if (!inp) return 'no_input';
        window.__si(inp, {json.dumps(size_name)});
        return 'ok';
    }})()""")

    # 2) 参考日本サイズ Select を同じ行内で Playwright native クリック
    jp_result = "skipped"
    try:
        row_locator = page.locator(row_sel)
        row_select = row_locator.locator('.Select, .bmm-c-custom-select').first
        ok = _click_select_option(
            page, row_select, jp_size,
            debug_name=f"参考日本サイズ[row={row_idx}]",
        )
        jp_result = "ok" if ok else "click_failed"
    except Exception as e:
        jp_result = f"exception:{e}"

    return f"name={name_result} / jp_dd={jp_result}"


def _set_stock_status_and_qty(page, per_row_qty=1, total_qty=1):
    """在庫ステータス=買付可 + 行ごとの数量 + 合計数量。

    - 各行 input[placeholder="数量"] → per_row_qty
    - 「買付できる合計数量」input → total_qty
    バリエーションなしの場合は per_row_qty == total_qty で呼ばれる想定。
    """
    stock_dd_js = """(function(){
        var all = document.querySelectorAll('.Select');
        for (var i = 0; i < all.length; i++) {
            var lbl = all[i].querySelector('.Select-value-label, .Select-placeholder');
            var t = lbl ? lbl.textContent.trim() : '';
            if (t === '手元に在庫あり' || t === '買付不可' || t === '買付可') {
                return i;
            }
        }
        return -1;
    })()"""
    stock_idx = page.evaluate(stock_dd_js)
    if stock_idx is not None and stock_idx >= 0:
        stock_dd = page.locator('.Select').nth(stock_idx)
        _click_select_option(page, stock_dd, "買付可", debug_name="在庫ステータス")

    stock_result = page.evaluate(f"""(function(){{
        var perRow = {per_row_qty};
        var total = {total_qty};
        var results = [];
        document.querySelectorAll('input[placeholder="数量"]').forEach(function(el){{
            window.__si(el, String(perRow));
            results.push('row=' + perRow);
        }});
        var titles = document.querySelectorAll('*');
        for (var i = 0; i < titles.length; i++) {{
            var t = (titles[i].textContent || '').trim();
            if (t.length > 40) continue;
            if (t.indexOf('買付できる合計数量') === -1) continue;
            var parent = titles[i];
            for (var d = 0; d < 6 && parent; d++) {{
                var inp = parent.querySelector('input[type="number"], input[type="text"], input:not([type])');
                if (inp && (inp.value === '' || inp.value === '0' || inp.value === String(perRow))) {{
                    window.__si(inp, String(total));
                    results.push('買付合計=' + total);
                    return results;
                }}
                parent = parent.parentElement;
            }}
        }}
        return results;
    }})()""")
    print(f"       [在庫合計] per_row={per_row_qty} total={total_qty} {stock_result}")


def set_purchase_memo(page, product):
    """出品メモ・買付先ショップ名・買付先メモ を設定する。

    - 出品メモ: 選定理由・利益計算・コスト内訳（BUYMAの商品問合せ欄で確認できる内部メモ）
    - 買付先ショップ名: BaseBlu（15文字制限あり）
    - 買付先メモ: 買付先名 / URL / 説明 の 3input
    """
    product_url = product.get("product_url", "")
    sale_price_eur = product.get("sale_price_eur", product.get("sale_price_usd", "0"))
    recommended_price = product.get("recommended_price", "0")
    total_cost = product.get("total_cost_jpy", "0")
    profit = product.get("profit_jpy", product.get("estimated_profit_jpy", "0"))
    title = product.get("title", "")
    sku = product.get("sku", "")

    def _fmt(v):
        try: return f"{int(float(v)):,}"
        except: return str(v)

    def _num(v, default=0):
        try: return int(float(v))
        except: return default

    eur_rate = 160
    purchase_jpy = _num(sale_price_eur) * eur_rate
    total_cost_n = _num(total_cost)
    recommended_n = _num(recommended_price)
    profit_n = _num(profit)
    fees_jpy = max(total_cost_n - purchase_jpy, 0)
    buyma_commission = int(recommended_n * 0.058)
    profit_rate = (profit_n / recommended_n * 100) if recommended_n else 0

    # 出品メモ: 仕入先・商品URL・品番は含めない（それぞれ専用フィールドがある）
    listing_memo = (
        f"【選定理由】\n"
        f"BaseBlu セールから抽出、想定利益 ¥{_fmt(profit)} / 利益率 {profit_rate:.1f}% で基準クリア。\n\n"
        f"【売価 / 利益】\n"
        f"販売価格: ¥{_fmt(recommended_price)}\n"
        f"総仕入コスト: ¥{_fmt(total_cost)}\n"
        f"想定利益: ¥{_fmt(profit)}\n"
        f"利益率: {profit_rate:.1f}%\n\n"
        f"【コスト内訳（概算）】\n"
        f"仕入価格: {sale_price_eur} EUR (≒ ¥{_fmt(purchase_jpy)} @ {eur_rate}円/EUR)\n"
        f"送料・関税・消費税 小計: ¥{_fmt(fees_jpy)}\n"
        f"BUYMA 手数料(5.8%): ¥{_fmt(buyma_commission)}\n\n"
        f"【商品】\n"
        f"タイトル: {title}"
    )
    shop_name = ""
    buyer_name = "BaseBlu"
    buyer_url = product_url
    # 買付先メモ 説明: 現地価格と総コストのみ（品番は専用フィールドに入る）
    buyer_desc = (
        f"現地価格: {sale_price_eur} EUR / 総コスト: ¥{_fmt(total_cost)}"
    )

    def _fill_in_section(section_title, value, tag="textarea", input_idx=0, match_placeholder=None):
        """section_title の見出しから次の見出しまでの範囲で、N番目の tag 要素に value を入れる。

        match_placeholder が指定された場合は、範囲内の input のうち placeholder が
        一致するものを優先的に選ぶ（input が複数あるセクション向け）。
        """
        js = f"""(function(){{
            var titles = document.querySelectorAll('.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt');
            var title = {json.dumps(section_title)};
            var val = {json.dumps(value)};
            var tag = {json.dumps(tag)};
            var idx = {input_idx};
            var ph_key = {json.dumps(match_placeholder or "")};
            for (var i = 0; i < titles.length; i++) {{
                var tt = (titles[i].textContent || '').trim();
                if (tt !== title) continue;
                var startEl = titles[i];
                var endEl = titles[i + 1] || null;
                var els = document.querySelectorAll(tag);
                var picked = [];
                for (var j = 0; j < els.length; j++) {{
                    if (!(startEl.compareDocumentPosition(els[j]) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
                    if (endEl && !(endEl.compareDocumentPosition(els[j]) & Node.DOCUMENT_POSITION_PRECEDING)) continue;
                    if (ph_key) {{
                        var ph = els[j].getAttribute('placeholder') || '';
                        if (ph.indexOf(ph_key) === -1) continue;
                    }}
                    picked.push(els[j]);
                }}
                if (picked.length > idx) {{
                    var target = picked[idx];
                    if (tag === 'textarea') window.__sta(target, val);
                    else window.__si(target, val);
                    return 'ok(count=' + picked.length + ')';
                }}
                return 'no_element(count=' + picked.length + ')';
            }}
            return 'title_not_found';
        }})()"""
        return page.evaluate(js)

    results = {}
    # 出品メモ (textarea)
    results["出品メモ"] = _fill_in_section("出品メモ", listing_memo, tag="textarea")

    # 買付先ショップ名 (1 input) — 15文字制限があるため "BaseBlu" のみ
    results["買付先ショップ名"] = _fill_in_section("買付先ショップ名", shop_name, tag="input")

    # 買付先メモ (3 inputs: 買付先名 / URL / 説明)
    # 実際の DOM では placeholder が空なので、位置ベース（セクション内の 1/2/3番目）で判定する。
    # 視覚上のラベル文字 ("買付先名" / "URL" / "説明") は別要素でレンダリングされている。
    results["買付先メモ_名"]  = _fill_in_section("買付先メモ", buyer_name, tag="input", input_idx=0)
    results["買付先メモ_URL"] = _fill_in_section("買付先メモ", buyer_url,  tag="input", input_idx=1)
    results["買付先メモ_説明"] = _fill_in_section("買付先メモ", buyer_desc, tag="input", input_idx=2)

    print(f"    📝 メモ: {results}")


def publish_product(page):
    captured_urls = []
    vr = {"status": None}
    def on_resp(r):
        captured_urls.append((r.url, r.status))
        if "validation" in r.url:
            vr["status"] = r.status
    page.on("response", on_resp)

    # ボタンテキスト・disabled状態を列挙してデバッグ
    btns = page.evaluate("""Array.from(document.querySelectorAll('button')).map(function(b){return {text:b.textContent.trim(), disabled:b.disabled, classes:b.className}}).filter(function(b){return b.text.length>0})""")
    print(f"    🔍 ボタン一覧: {btns}")

    # ネイティブクリックでReactイベントを確実に発火
    confirm_btn = page.locator("button", has_text="入力内容を確認する").first
    if confirm_btn.count() == 0:
        page.remove_listener("response", on_resp)
        print("    ❌ 確認ボタンなし"); return False
    confirm_btn.click()

    # 確認画面への遷移 or API レスポンスを待つ（最大15秒）
    for _ in range(30):
        time.sleep(0.5)
        cur_url = page.url
        if vr["status"] is not None: break
        if "confirm" in cur_url or "preview" in cur_url or "check" in cur_url: break
    page.remove_listener("response", on_resp)

    # デバッグ: キャプチャした全URLを出力
    print(f"    🌐 APIレスポンス({len(captured_urls)}件): {[(u.split('?')[0][-60:], s) for u, s in captured_urls[-10:]]}")
    print(f"    📍 現在URL: {page.url[-80:]}")
    # スクリーンショット保存
    import os as _os
    ss_path = _os.path.join(_os.path.dirname(__file__), "..", "outputs", "reports", "debug_publish_click.png")
    page.screenshot(path=ss_path, full_page=False)
    print(f"    📸 スクリーンショット: {ss_path}")
    # フロントエンドのバリデーションエラーを取得（より広いセレクタ）
    errors = page.evaluate("""Array.from(document.querySelectorAll('[class*="error"],[class*="Error"],[class*="invalid"],[class*="warning"]')).map(function(e){return e.textContent.trim()}).filter(function(t){return t.length>2 && t.length<300}).slice(0,10)""")
    if errors:
        print(f"    ❗ UIエラー: {errors}")

    if vr["status"] is not None and vr["status"] != 200:
        print(f"    ❌ バリデーション失敗 (status={vr['status']})"); return False
    if vr["status"] == 200:
        print("    ✅ バリデーションOK (API)")
    else:
        print("    ✅ 確認画面へ遷移（APIなし形式）")
    human_delay(0.5, 1.0)

    # 「注意事項に同意して公開する」ボタンをネイティブクリック
    pub_btns = page.locator("button", has_text="公開する")
    count = pub_btns.count()
    print(f"    🔍 公開ボタン候補: {count}件")
    if count == 0:
        print("    ❌ 公開するボタンなし"); return False
    # クリック前SS
    import os as _os2
    ss_before = _os2.path.join(_os2.path.dirname(__file__), "..", "outputs", "reports", "debug_before_pubclick.png")
    page.screenshot(path=ss_before, full_page=False)
    pub_btns.first.click()
    # URL が sell/new から離れるまで最大60秒待つ（APIレスポンスに時間がかかる）
    for _ in range(120):
        time.sleep(0.5)
        cur = page.url
        if "sell/new" not in cur: break
    url_after = page.url
    print(f"    📍 公開後URL: {url_after[-80:]}")
    # 「出品が完了しました」ページのURL or ページテキストで判定
    completed_page = page.evaluate("""document.body.innerText.includes('出品が完了しました') || document.body.innerText.includes('出品完了')""")
    if completed_page or "sell/new" not in url_after:
        print("    🎉 出品公開完了！"); return True
    ss2 = _os2.path.join(_os2.path.dirname(__file__), "..", "outputs", "reports", "debug_after_publish.png")
    page.screenshot(path=ss2, full_page=False)
    print(f"    ⚠️ 公開後もsell/newのまま"); return False


def _clear_customs_checkbox(page):
    """関税負担チェックを外す（保存422 duty_attributes の回避用）。"""
    return page.evaluate("""(function(){
        var labels = document.querySelectorAll('label');
        for(var i=0; i<labels.length; i++){
            var text = labels[i].textContent || '';
            if(text.indexOf('関税') === -1) continue;
            var cb = labels[i].querySelector('input[type="checkbox"]');
            if(!cb){
                var f = labels[i].getAttribute('for');
                if(f) cb = document.getElementById(f);
            }
            if(cb && cb.checked){ cb.click(); return 'unchecked'; }
            if(cb && !cb.checked){ return 'already_unchecked'; }
        }
        return 'not_found';
    })()""")


def save_draft(page, _retried=False):
    """下書き保存ボタンを押し、URLの遷移で成否を判定する。

    BUYMA の「下書き保存する」は手動クリックを前提とした React ボタン。
    JS の .click() では反応しないため Playwright のネイティブクリックを使う。
    成功時は /my/sell/{item_id}/edit?tab=b に遷移する。
    """
    import re
    url_before = page.url

    # Playwright のネイティブクリック（下部固定バーの visible ボタンを優先）
    btn = page.locator('.sell-btnbar button:has-text("下書き保存する"):visible').first
    try:
        if btn.count() == 0:
            btn = page.locator('button:has-text("下書き保存する"):visible').first
    except Exception:
        btn = page.locator('button:has-text("下書き保存する")').first

    try:
        btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    clicked = False
    net_hit = None
    net_detail = None
    try:
        with page.expect_response(
            lambda r: (r.request.method in ("POST", "PUT", "PATCH") and "/sell" in r.url),
            timeout=7000,
        ) as resp_info:
            btn.click(timeout=5000)
        resp = resp_info.value
        net_hit = f"{resp.request.method} {resp.status} {resp.url}"
        if resp.status >= 400:
            try:
                body = resp.text() or ""
                net_detail = body[:800]
            except Exception:
                net_detail = None
        clicked = True
    except Exception as e:
        print(f"    ⚠️ ボタンクリック失敗: {e}")

    if not clicked:
        try:
            btn.click(timeout=3000, force=True)
            clicked = True
            print("    ↪ force click で再試行")
        except Exception as e:
            print(f"    ⚠️ force click 失敗: {e}")

    if not clicked:
        # フォールバック: JS 経由
        page.evaluate("""(function(){
            var btns = Array.from(document.querySelectorAll('button')).filter(function(b){
                return (b.textContent||'').trim().includes('下書き保存する');
            });
            var visible = btns.filter(function(b){
                var r = b.getBoundingClientRect();
                var st = window.getComputedStyle(b);
                return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden';
            });
            var b = visible[0] || btns[0];
            if(!b) return false;
            b.scrollIntoView({block:'center'});
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(type){
                b.dispatchEvent(new MouseEvent(type, {bubbles:true,cancelable:true,view:window}));
            });
            return true;
        })()""")

    if net_hit:
        print(f"    📡 保存通信: {net_hit}")
    if net_detail:
        print(f"       保存API応答(抜粋): {net_detail}")

    # 422 duty_attributes は「関税込み時の発送エリア/発送都市不足」
    # 一度だけ関税チェックを外して保存を再試行する
    if (not _retried) and net_detail and ("duty_attributes" in net_detail):
        clr = _clear_customs_checkbox(page)
        print(f"    ↪ 関税チェック解除して再試行: {clr}")
        time.sleep(0.4)
        return save_draft(page, _retried=True)

    # 確認モーダルがあればクリック（「保存する」「はい」「OK」など）
    for modal_text in ["保存する", "はい", "OK"]:
        try:
            modal_btn = page.locator(f'button:has-text("{modal_text}")').first
            if modal_btn.is_visible(timeout=1000):
                modal_btn.click(timeout=2000)
                break
        except Exception:
            continue

    # URL の変化を最大 15 秒待つ
    item_id = None
    for _ in range(30):
        time.sleep(0.5)
        url = page.url
        if url == url_before:
            continue
        m = re.search(r"/my/sell/(\d+)(?:/edit)?", url)
        if m:
            item_id = m.group(1)
            break
        m = re.search(r"/my/sell/edit/(\d+)", url)
        if m:
            item_id = m.group(1)
            break
        if "/my/" in url and "/sell/new" not in url:
            break

    url_after = page.url
    if item_id:
        print(f"    💾 下書き保存: ID={item_id}")
        return item_id
    if url_after != url_before and "/sell/new" not in url_after:
        print(f"    💾 下書き保存（ID未確定）: {url_after}")
        return "saved"

    # URL が変わらない実装に備えて、DOM 上の成功トースト/ヒントを確認
    save_hint = page.evaluate("""(function(){
        var text = (document.body && document.body.innerText) ? document.body.innerText : '';
        var hints = [
            '下書き保存しました',
            '保存しました',
            '保存が完了しました',
            '下書きに保存しました'
        ];
        var matched = '';
        for (var i = 0; i < hints.length; i++) {
            if (text.indexOf(hints[i]) !== -1) { matched = hints[i]; break; }
        }

        var itemId = null;
        var nodes = document.querySelectorAll('a[href*="/my/sell/"], form[action*="/my/sell/"]');
        for (var j = 0; j < nodes.length; j++) {
            var v = nodes[j].getAttribute('href') || nodes[j].getAttribute('action') || '';
            var m = v.match(new RegExp('/my/sell/(\\d+)(?:/edit)?'));
            if (m) { itemId = m[1]; break; }
        }
        return {matched: matched, item_id: itemId};
    })()""")
    if save_hint.get("item_id"):
        print(f"    💾 下書き保存: ID={save_hint['item_id']} (DOM検出)")
        return save_hint["item_id"]
    if save_hint.get("matched"):
        print(f"    💾 下書き保存（URL据え置き）: {save_hint['matched']}")
        return "saved"

    # 失敗時はフォーム上のエラー表示を dump する（visible なものだけ）
    errors = page.evaluate("""(function(){
        var errs = [];
        document.querySelectorAll('.bmm-c-error, .bmm-c-field-error, .error, [class*="error"]')
            .forEach(function(e){
                var t = (e.textContent || '').trim();
                if (!t || t.length > 120) return;
                var rect = e.getBoundingClientRect();
                var style = window.getComputedStyle(e);
                var visible = rect.width > 0 && rect.height > 0
                    && style.display !== 'none' && style.visibility !== 'hidden';
                errs.push({text: t, visible: visible, cls: e.className});
            });

        var titles = Array.from(document.querySelectorAll('.bmm-c-summary__ttl, .bmm-c-ttl, h2, h3, h4, legend, dt'));
        function sectionName(el){
            var cur = '';
            for (var i = 0; i < titles.length; i++) {
                if (titles[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) {
                    cur = (titles[i].textContent || '').trim();
                } else {
                    break;
                }
            }
            return cur;
        }

        var placeholders = [];
        document.querySelectorAll('.Select-placeholder').forEach(function(p){
            var txt = (p.textContent || '').trim();
            if (!txt || txt.indexOf('選択') === -1) return;
            var rect = p.getBoundingClientRect();
            var style = window.getComputedStyle(p);
            var visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            if (!visible) return;
            placeholders.push({section: sectionName(p), text: txt});
        });

        var btn = Array.from(document.querySelectorAll('button'))
            .find(function(b){return b.textContent.trim().indexOf('下書き保存') !== -1});
        var btnInfo = btn ? ('btn disabled=' + btn.disabled) : 'no_button';
        var btnHtml = btn ? (btn.outerHTML || '').slice(0, 240) : '';

        var invalids = [];
        document.querySelectorAll(':invalid').forEach(function(el){
            var name = el.getAttribute('name') || el.id || el.className || el.tagName;
            var req = !!el.required;
            var val = ('value' in el) ? String(el.value || '') : '';
            invalids.push({name: name, required: req, value_len: val.length});
        });

        var dutyFields = [];
        var dutyLabels = Array.from(document.querySelectorAll('label, .bmm-c-summary__ttl, .bmm-c-label, dt, th')).filter(function(n){
            var t = (n.textContent || '').trim();
            return t.indexOf('発送エリア') !== -1 || t.indexOf('発送都市') !== -1;
        });
        dutyLabels.forEach(function(lb){
            var root = lb.closest('tr, .bmm-l-row, .bmm-c-form-group, .bmm-c-summary__item, .bmm-c-summary') || lb.parentElement;
            if (!root) return;
            var cand = root.querySelector('input, select, textarea, [role="combobox"], .Select-input input');
            var info = {
                label: (lb.textContent || '').trim().slice(0, 40),
                field_found: !!cand
            };
            if (cand) {
                info.tag = cand.tagName;
                info.type = cand.type || '';
                info.name = cand.name || cand.id || '';
                info.value = ('value' in cand) ? String(cand.value || '') : '';
                info.placeholder = cand.placeholder || '';
            }
            dutyFields.push(info);
        });

        return {
            errors: errs.slice(0, 10),
            button: btnInfo,
            button_html: btnHtml,
            placeholders: placeholders.slice(0, 20),
            invalids: invalids.slice(0, 20),
            duty_fields: dutyFields.slice(0, 10)
        };
    })()""")
    print(f"    ⚠️ 保存未確認 (url={url_after})")
    print(f"       診断: {errors}")
    return None


# ========== 1商品の処理 ==========

def process_product(page, product, draft_mode, brands_data, cat_data, tag_rules=None):
    title   = product["title"]
    vendor  = product["vendor"]
    price   = int(product["recommended_price"])
    sku     = product.get("sku", "")
    desc_en = product.get("description_en", "")
    img_url = product.get("image_url", "")
    sub_imgs = product.get("sub_images", "")
    product_type = product.get("product_type", "")

    cat_path = get_category_path(title, product_type, cat_data)
    cat_label = " > ".join(cat_path)
    safe_vendor = normalize_text(vendor)
    b_id, b_phonetic = resolve_brand(vendor, brands_data)

    # v4: SEO最適化タイトル & プロ仕様商品説明
    display_title = generate_buyma_title(title, vendor, sku, cat_label)
    desc = generate_description(title, vendor, sku, desc_en, cat_label)

    readiness, readiness_reasons = evaluate_listing_readiness(product, price, cat_label, desc)

    print(f"  📦 {display_title[:50]}")
    print(f"     ブランド={safe_vendor}(id={b_id}) カテゴリ={cat_label} ¥{price:,}")
    if sku:
        print(f"     品番={sku}")
    print(f"     出品判定={readiness} / {readiness_reasons}")

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
    set_category(page, cat_path); human_delay(0.5, 1.0)
    set_price(page, price); human_delay(0.3, 0.6)

    # 6. 配送・地域（draft_mode でも設定してから保存する）
    set_shipping(page, price); human_delay(0.3, 0.6)
    set_region(page); human_delay(0.3, 0.6)

    # 7. シーズン（baseblu の "AW25" 等）
    set_season(page, product.get("season", "")); human_delay(0.3, 0.6)

    # 8. テーマ（未設定だと保存失敗する場合があるため先に埋める）
    set_theme(page); human_delay(0.2, 0.5)

    # 9. 購入期限（90日）
    set_purchase_deadline(page); human_delay(0.3, 0.6)

    # 10. 関税チェック
    set_customs_checkbox(page); human_delay(0.3, 0.6)

    # 10. 色: baseblu から抽出した英語 color を日本語にマップ（色の系統ドロップダウン用）
    #    色名テキストフィールドには原文（"Black" 等）をそのまま入れる
    raw_color = (product.get("color") or "").strip()
    first_color_en = raw_color.split(",")[0].strip() if raw_color else ""
    color_jp = translate_color_to_jp(first_color_en)
    color_label = first_color_en or color_jp  # テキスト欄用（英語優先、無ければ日本語）
    set_color(page, color_name=color_jp, color_label=color_label); human_delay(0.3, 0.6)

    # 11. サイズ・在庫（買付可）
    # CLOTHING / FOOTWEAR は「バリエーションあり」で在庫ありサイズを全登録。
    # BAGS / ACCESSORIES は「バリエーションなし」で単一サイズ。
    set_size_and_stock(
        page,
        product_type=product_type,
        available_sizes_csv=(product.get("available_sizes") or "").strip(),
        fallback_sizes_csv=(product.get("sizes") or "").strip(),
        stock_qty_per_size=1,
    ); human_delay(0.5, 1.0)

    # 11b. タグ (data/tags.json のルールで自動判定 → チェックして保存)
    if tag_rules is not None:
        tags_to_apply = determine_tags(product, tag_rules)
        if tags_to_apply:
            set_tags(page, tags_to_apply); human_delay(0.3, 0.6)
        else:
            print(f"    🏷️ タグ: 付与対象なし")

    # 12. 出品メモ・買付先メモ
    set_purchase_memo(page, product); human_delay(0.3, 0.6)

    # 13. ブランド（他フィールドの React 再レンダリングで brand state がリセットされ
    #     「未登録」警告が残るのを防ぐため、また 品番セクションが
    #     ブランド設定後に条件付きでDOMに出現するため、保存直前に配置）
    brand_ok = select_brand(page, safe_vendor, b_phonetic, b_id)
    if not brand_ok:
        return "brand_not_found", None
    human_delay(1.0, 1.5)

    # 14. 品番 (SKU) + 識別メモ — ブランド入力後に出現するセクション
    first_color_en2 = (product.get("color") or "").strip().split(",")[0].strip()
    first_size_tmp = (product.get("sizes") or "").strip().split(",")[0].strip()
    identify_parts = []
    if first_color_en2: identify_parts.append(f"色:{first_color_en2}")
    if first_size_tmp: identify_parts.append(f"サイズ:{first_size_tmp}")
    identify_memo = "/".join(identify_parts)
    set_sku(page, sku, identify_memo=identify_memo); human_delay(0.5, 1.0)

    # 保存 or 公開
    if draft_mode:
        item_id = save_draft(page)
        return ("draft", item_id) if item_id else ("save_failed", None)

    ok = publish_product(page)
    return ("published", "published") if ok else ("publish_failed", None)


# ========== メイン ==========

def main():
    args = sys.argv[1:]
    test_mode   = "--test"   in args
    resume_mode = "--resume" in args
    draft_mode  = "--draft"  in args
    publish_mode = "--publish" in args
    # 安全策: 明示的に --publish を指定しない限り draft 扱い
    if not draft_mode and not publish_mode:
        draft_mode = True
    hold_mode   = "--hold"   in args
    skip_confirm = "--yes" in args
    start_from  = 1
    limit_count = None
    max_price = None
    min_profit = None
    include_review = "--include-review" in args
    # SU環境デフォルト: 右モニタ上部に出す
    window_x = 1800
    window_y = 0
    window_w = 1400
    window_h = 900
    if "--from" in args:
        idx = args.index("--from")
        try: start_from = int(args[idx + 1])
        except: print("❌ --from の後に数字を指定"); sys.exit(1)
    if "--limit" in args:
        idx = args.index("--limit")
        try: limit_count = int(args[idx + 1])
        except: print("❌ --limit の後に数字を指定"); sys.exit(1)
    if "--max-price" in args:
        idx = args.index("--max-price")
        try: max_price = int(args[idx + 1])
        except: print("❌ --max-price の後に数字を指定"); sys.exit(1)
    if "--min-profit" in args:
        idx = args.index("--min-profit")
        try: min_profit = int(args[idx + 1])
        except: print("❌ --min-profit の後に数字を指定"); sys.exit(1)

    def _read_int_arg(name, default=None):
        if name not in args:
            return default
        idx = args.index(name)
        try:
            return int(args[idx + 1])
        except Exception:
            print(f"❌ {name} の後に数字を指定"); sys.exit(1)

    window_x = _read_int_arg("--window-x", window_x)
    window_y = _read_int_arg("--window-y", window_y)
    window_w = _read_int_arg("--window-w", window_w)
    window_h = _read_int_arg("--window-h", window_h)

    print("=" * 50)
    mode_label = "下書き" if draft_mode else "🚨 本公開"
    print(f"🛒 BUYMA自動出品 v4.2 ({mode_label}{'・テスト' if test_mode else ''})")
    print("=" * 50)

    # 本公開モードの安全確認 (--yes でスキップ可)
    if publish_mode and not skip_confirm:
        n = limit_count or "全件"
        print("⚠️ 本公開モードです。実際に BUYMA 上で公開されます。")
        print(f"   対象: {start_from} 番目から {n} 件")
        print("   この操作は取り消せません。続行するには 'YES' と入力してください。")
        try:
            answer = input("   > ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "YES":
            print("❌ 中止しました")
            sys.exit(0)
    if max_price:
        print(f"   フィルタ: 販売価格 ≤ ¥{max_price:,}")
    if min_profit:
        print(f"   フィルタ: 利益 ≥ ¥{min_profit:,}")

    config = load_config()
    cat_data = load_categories()
    brands_data = load_brands()
    tag_rules = load_tags()
    products = load_products(max_price=max_price, min_profit=min_profit)
    if not products:
        print("❌ 商品なし"); sys.exit(1)

    # 自動出品の安全策: デフォルトでは「出品OK」判定のみを対象にする。
    # 高額・サイズ不明・コメント汚染などは --include-review 指定時だけ処理対象に含める。
    if not include_review:
        ready_products = []
        skipped_review = 0
        for p in products:
            cat_label = " > ".join(get_category_path(p["title"], p.get("product_type", ""), cat_data))
            desc = generate_description(p["title"], p["vendor"], p.get("sku", ""), p.get("description_en", ""), cat_label)
            verdict, reasons = evaluate_listing_readiness(p, int(float(p.get("recommended_price") or 0)), cat_label, desc)
            if verdict == "出品OK":
                ready_products.append(p)
            else:
                skipped_review += 1
                print(f"  ⏭ 要確認除外: {p['vendor']} / {p['title'][:40]} ({verdict}: {reasons[:2]})")
        products = ready_products
        print(f"🛡 出品OKフィルタ: {len(products)} 件 / 要確認・NG除外 {skipped_review} 件")
        if not products:
            print("❌ 出品OK商品なし（--include-review で要確認商品も対象化できます）"); sys.exit(1)

    progress = load_progress()
    if resume_mode:
        # v4.1: --resume は「成功済み」と「恒久的スキップ」のみ除外する。
        # limit 適用前に除外しないと、先頭が成功済みの場合に --limit 1 が空振りする。
        succeeded = set(progress.get("succeeded_titles", []))
        # 後方互換: 旧スキーマでは processed_titles に全件が入っていたが、
        # エラー履歴と成功履歴の区別ができないため、--resume 時は無視する。
        # （必要なら --resume-legacy で旧挙動を復元可能）
        products = [p for p in products if p["title"] not in succeeded]
        print(f"↩️ 再開: 成功済み {len(succeeded)} 件を除外 → 残り {len(products)} 件")

    target = products[start_from - 1:]
    if test_mode:
        target = target[:1]
    elif limit_count is not None:
        target = target[:limit_count]
    print(f"📦 対象: {len(target)}件（{start_from}番〜）")

    os.makedirs(STATE_DIR, exist_ok=True)

    results = []
    with sync_playwright() as pw:
        launch_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox", f"--window-size={window_w},{window_h}"]
        if window_x is not None and window_y is not None:
            launch_args.append(f"--window-position={window_x},{window_y}")

        browser = pw.chromium.launch(headless=False, args=launch_args)

        context_kwargs = dict(
            viewport=None,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        if os.path.exists(STORAGE_STATE_PATH):
            context_kwargs["storage_state"] = STORAGE_STATE_PATH

        ctx = browser.new_context(**context_kwargs)
        page = ctx.new_page()

        if not login(page, config["buyma_email"], config["buyma_password"]):
            browser.close(); sys.exit(1)

        try:
            ctx.storage_state(path=STORAGE_STATE_PATH)
        except Exception as e:
            print(f"  ⚠️ storage_state 保存失敗: {e}")

        total = len(target)
        for i, product in enumerate(target, 1):
            print(f"\n{'─'*40} [{i}/{total}] {'─'*5}")
            # retry 戦略: RETRIABLE なエラー (timeout/error) は最大 2 回まで再試行
            status, item_id = None, None
            for attempt in range(1, 3):
                try:
                    status, item_id = process_product(page, product, draft_mode, brands_data, cat_data, tag_rules=tag_rules)
                except Exception as e:
                    import traceback; traceback.print_exc()
                    status, item_id = "error", None
                if status not in ("timeout", "error") or attempt >= 2:
                    break
                print(f"  🔁 retry {attempt}/2 (status={status})")
                time.sleep(random.uniform(5, 10))

            results.append({
                "status": status, "item_id": item_id or "",
                "title": product["title"], "vendor": product["vendor"],
                "price": product["recommended_price"],
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            # 連続失敗の通知 (status が retriable 系で 2 回 retry も失敗した時のみ)
            # silent skip 設定: SLACK_WEBHOOK_URL / SMTP_HOST 未設定なら何も送られない
            if status in ("error", "timeout", "publish_failed"):
                try:
                    from app.utils.notifier import notify
                    notify(
                        "warn",
                        f"出品失敗: {product['vendor']} {product['title'][:40]}",
                        f"status={status} attempt=2/2\n"
                        f"price=¥{int(product['recommended_price']):,}\n"
                        f"sku={product.get('sku', '')}\n"
                        f"url={product.get('product_url', '')}"
                    )
                except Exception as notify_exc:
                    print(f"  ⚠️ 通知送信失敗 (無視): {notify_exc}")

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

        if hold_mode:
            print("\n" + "=" * 50)
            print("🔍 --hold モード: ブラウザウィンドウを開いたままにしています。")
            print("   BUYMA の画面で手動操作・DevTools 確認をしてください。")
            print("   終了するには、このターミナルで Enter キーを押してください。")
            print("=" * 50)
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass

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

    # バッチ完了通知 (失敗率 30% 超 or 公開モードなら必ず送る)
    failure_rate = fail / len(results) if results else 0
    should_notify = (failure_rate > 0.3) or (publish_mode and (pub + dra) > 0)
    if should_notify:
        try:
            from app.utils.notifier import notify
            level = "error" if failure_rate > 0.3 else "success"
            notify(
                level,
                f"BUYMA 出品バッチ完了 (mode={'publish' if publish_mode else 'draft'})",
                f"対象 {len(results)} 件 → 公開:{pub} 下書き:{dra} スキップ:{skip} 失敗:{fail}\n"
                f"失敗率: {failure_rate*100:.1f}%\n"
                f"CSV: {result_path}"
            )
        except Exception as notify_exc:
            print(f"⚠️ 完了通知送信失敗 (無視): {notify_exc}")

if __name__ == "__main__":
    main()
