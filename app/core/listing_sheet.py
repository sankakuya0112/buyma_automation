"""出品シート: BUYMA の通常の出品フォーム (https://www.buyma.com/my/sell/new?tab=b) に
本人が手で入力するための、人が読む一覧 (Markdown / 印刷用 HTML / CSV)。

- BUYMA にはアクセスしない。ブラウザ自動操作もしない (2026-10-07 の方針)
- 項目の並びは、リポジトリが知っている出品フォームの入力順
  (scripts/buyma_auto_listing.py の process_product。2026-06 に下書き保存まで通った手順)。
  画面の上から下の並びと完全に同じとは限らない
- 各項目に「入力 (コピペ)」「選択 (BUYMA の画面で選ぶ)」「確認」「参考」を付ける。
  ブランド・カテゴリ・色系統・配送方法・地域などの ID は BUYMA の画面で選ぶ (推測の ID は書かない)
- 原価内訳と見込み利益は仕入先の設定 (data/sources.json / app/core/sources) と
  app/core/pricing.py から計算し直す (シート作成時点の為替)

純粋関数のみ (タイトル・説明文・カテゴリ・色の生成は呼び出し側が scripts/buyma_auto_listing.py の
関数で作って渡す)。
"""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.core.candidate_select import brand_tier, model_number, search_urls
from app.utils.listing_helpers import (
    _buyma_title_width,
    _strip_accents,
    clean_source_description,
    classify_size_category,
    format_size_name_for_listing,
    is_waist_inch_size,
    listing_sizes,
    uses_collar_sizes,
    map_size_to_jp_reference_for,
)

BUYMA_LISTING_FORM_URL = "https://www.buyma.com/my/sell/new?tab=b"

ACTION_INPUT = "入力"     # シートの値をそのまま貼る
ACTION_SELECT = "選択"    # BUYMA の画面のプルダウン / サジェストで選ぶ (ID は書かない)
ACTION_CHECK = "確認"     # 本人が判断・確認する
ACTION_INFO = "参考"      # フォームには入れない (判断材料)

ACTION_ICON = {ACTION_INPUT: "✏️", ACTION_SELECT: "🔽", ACTION_CHECK: "⚠️", ACTION_INFO: "ℹ️"}

# 買付地 (sources.json の country → BUYMA の 大陸 > 国)。無い国は空 (画面で選ぶ)
BUY_REGION_BY_COUNTRY = {
    "IT": ("ヨーロッパ", "イタリア"),
    "FR": ("ヨーロッパ", "フランス"),
    "GB": ("ヨーロッパ", "イギリス"),
    "DE": ("ヨーロッパ", "ドイツ"),
    "ES": ("ヨーロッパ", "スペイン"),
    "US": ("北米", "アメリカ"),
}

# リポジトリの既定値 (scripts/buyma_auto_listing.py の set_shipping / set_region / set_theme /
# set_purchase_deadline / set_customs_checkbox)。本人の BUYMA の設定に合わせて画面で選ぶ
DEFAULT_SHIPPING_METHODS = ("宅急便コンパクト", "宅急便")
DEFAULT_SHIP_FROM = ("国内", "神奈川県")
DEFAULT_THEME = "指定なし"
DEFAULT_DEADLINE_DAYS = 90
DEFAULT_MIN_PROFIT_JPY = 5000


@dataclass
class SheetField:
    section: str
    label: str
    value: str
    action: str
    note: str = ""


@dataclass
class ListingSheet:
    key: str                       # ファイル名用 (商品管理番号)
    heading: str
    summary: dict
    fields: list[SheetField] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    product: dict = field(default_factory=dict)   # 元の商品データ (出品記録への追記用)


# ---------------------------------------------------------------------------
# 原価内訳
# ---------------------------------------------------------------------------

def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def cost_breakdown(product: dict, proposed_price: Optional[int] = None,
                   min_profit_jpy: float = DEFAULT_MIN_PROFIT_JPY) -> dict:
    """仕入値から原価内訳・提案価格での利益・下限価格を計算し直す。

    proposed_price を省略すると CSV の最終売価 (recommended_price) を使う。
    為替はシート作成時点 (app/core/fx.py)。CSV 作成時と為替が違えば原価も変わる。
    """
    from app.core.pricing import calculate_pricing, min_price_for_profit, profit_at_price
    from app.core.sources import get_source

    source = get_source(product.get("source_name") or "")
    sale_price = _num(product.get("sale_price_eur"))
    params = source.get_pricing_params(sale_price=sale_price, category=product.get("product_type", ""),
                                       title=product.get("title", ""))
    r = calculate_pricing(params)
    price = int(proposed_price if proposed_price is not None else _num(product.get("recommended_price")))
    if price <= 0:
        price = r.selling_price_jpy
    at = profit_at_price(price, r.total_cost_jpy, params.buyma_commission_rate)
    return {
        "source_name": source.name,
        "display_name": getattr(source, "display_name", "") or source.name,
        "country": getattr(source, "country", ""),
        "currency": source.currency,
        "landed_cost_basis": r.landed_cost_basis,
        "vat_treatment": getattr(source, "vat_treatment", ""),
        "sale_price": sale_price,
        "exchange_rate": r.exchange_rate,
        "source_price_jpy": r.source_price_jpy,
        "vat_refund_jpy": r.vat_refund_jpy,
        "shipping_jpy": r.shipping_jpy,
        "duty_rate": r.duty_rate,
        "customs_jpy": r.customs_jpy,
        "consumption_tax_jpy": r.consumption_tax_jpy,
        "customs_handling_jpy": r.customs_handling_jpy,
        "purchase_fx_fee_jpy": r.purchase_fx_fee_jpy,
        "domestic_shipping_jpy": r.domestic_shipping_jpy,
        "bank_transfer_fee_jpy": r.bank_transfer_fee_jpy,
        "total_cost_jpy": r.total_cost_jpy,
        "target_price_jpy": r.selling_price_jpy,
        "proposed_price_jpy": price,
        "commission_rate": params.buyma_commission_rate,
        "commission_jpy": at["commission"],
        "fixed_fee_jpy": at["fixed_fee"],
        "profit_jpy": at["profit"],
        "margin_on_price_pct": (at["profit"] / price * 100) if price else 0.0,
        "min_profit_jpy": min_profit_jpy,
        "min_price_jpy": min_price_for_profit(r.total_cost_jpy, min_profit_jpy, params.buyma_commission_rate),
    }


def _yen(v) -> str:
    return f"¥{round(_num(v)):,}"


# ---------------------------------------------------------------------------
# サイズ (サイズ別価格のルール: 基準価格で在庫のあるサイズだけ。高いサイズは出さない)
# ---------------------------------------------------------------------------

_ALPHA_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]


def sort_sizes(sizes: list[str]) -> list[str]:
    """小さい順 (数値 → 数値順、XS〜XXL → その順)。判別できないものは元の順で後ろに。"""
    def key(item):
        i, s = item
        u = s.strip().upper()
        m = re.fullmatch(r"(?:IT|EU|FR)?\s*(\d+(?:[.,]\d+)?)", u)
        if m:
            return (0, float(m.group(1).replace(",", ".")), i)
        if u in _ALPHA_ORDER:
            return (1, _ALPHA_ORDER.index(u), i)
        return (2, 0, i)
    return [s for _, s in sorted(enumerate(sizes), key=key)]


def size_rows(product: dict) -> list[dict]:
    """出品するサイズの行。メンズ (gender=man) は IT 表記・シャツの襟サイズを考慮して参考日本サイズを出す。"""
    pt = product.get("product_type", "")
    gender = (product.get("gender") or "").lower()
    title = product.get("title", "")
    out = []
    raws = sort_sizes([s.strip() for s in listing_sizes(product).split(",") if s.strip()])
    # 襟サイズかどうかは商品のサイズ一覧全体で判断する (39/41 など奇数があれば襟。偶数だけなら IT 表記)
    collar_scheme = uses_collar_sizes(raws, pt, title, gender)
    for raw in raws:
        collar = collar_scheme
        waist = is_waist_inch_size(raw, pt, title)
        out.append({
            "source_size": raw,
            # 襟サイズ (39 等)・ウエスト (28 等) に IT を付けると別の意味になるので数値のまま
            "size_name": raw if (collar or waist) else (format_size_name_for_listing(raw, pt) or raw),
            "jp_reference": map_size_to_jp_reference_for(raw, pt, gender, title, collar=collar),
            "collar": collar,
            "waist": waist,
        })
    return out


# categories.json はレディースの辞書だけ。メンズは第1階層を差し替え、第3階層は画面で近いものを選ぶ
MENS_LEAF = {"シャツ・ブラウス": "シャツ"}


def gendered_category_path(path: list[str], gender: str) -> tuple[list[str], str]:
    """(カテゴリパス, 注記)。gender=man ならメンズファッションに差し替えて注記を返す。"""
    if (gender or "").lower() == "man" and path and path[0] == "レディースファッション":
        new = ["メンズファッション", *path[1:]]
        if len(new) >= 3:
            new[2] = MENS_LEAF.get(new[2], new[2])
        return new, "仕入先の分類はメンズ。メンズの第2・第3階層名はリポジトリ未採取なので画面で近いものを選ぶ"
    return list(path), ""


# 素材名 (仕入先の英語表記) → 日本語。長い語から順に照合する
MATERIAL_JA = {
    "calf leather": "カーフレザー", "lamb leather": "ラムレザー", "lambskin": "ラムスキン",
    "goat leather": "ゴートレザー", "calfskin": "カーフスキン", "suede": "スエード", "leather": "レザー",
    "virgin wool": "ヴァージンウール", "fleece wool": "ウール", "merino wool": "メリノウール", "wool": "ウール",
    "cashmere": "カシミヤ", "mohair": "モヘア", "alpaca": "アルパカ", "silk": "シルク", "cotton": "コットン",
    "linen": "リネン", "flax": "リネン", "viscose": "ビスコース", "rayon": "レーヨン", "cupro": "キュプラ",
    "acetate": "アセテート", "lyocell": "リヨセル", "modal": "モダール", "polyester": "ポリエステル",
    "polyamide": "ポリアミド", "nylon": "ナイロン", "elastane": "エラスタン", "spandex": "スパンデックス",
    "acrylic": "アクリル", "polyurethane": "ポリウレタン", "metal": "メタル", "brass": "真鍮", "rubber": "ラバー",
    "down": "ダウン", "feather": "フェザー",
}
# 学名などの付記 (Bos Taurus 等) は落とす
_LATIN_RE = re.compile(r"\b(bos taurus|ovis aries|capra hircus|bombyx mori|general)\b", re.IGNORECASE)


def materials_ja(description_en: str) -> str:
    """'Composition: GENERAL 95% Fleece Wool Ovis Aries 5% Elastane' → 'ウール 95% / エラスタン 5%'。

    分からない素材名は英語のまま残す。素材の記載が無ければ空文字。
    """
    m = re.search(r"(?:composition|material)\s*[:：]?\s*(.+)", description_en or "", re.IGNORECASE)
    if not m:
        return ""
    text = _LATIN_RE.sub(" ", m.group(1))
    parts = re.findall(r"(\d+(?:[.,]\d+)?)\s*%\s*([A-Za-z][A-Za-z \-]*?)(?=\s*\d+(?:[.,]\d+)?\s*%|$|[,;\n])", text)
    out = []
    for pct, name in parts:
        key = re.sub(r"\s+", " ", name).strip().lower()
        ja = next((v for k, v in sorted(MATERIAL_JA.items(), key=lambda kv: -len(kv[0])) if k in key), key.title())
        out.append(f"{ja} {pct}%")
    return " / ".join(out)


def structured_description_ja(product: dict, *, brand_name: str, phonetic: str, category_leaf: str,
                              color_family: str, color_name: str) -> str:
    """機械翻訳に頼らない日本語の商品詳細 (箇条書き) + 仕入先の英語原文。

    generate_description(desc_ja=...) の「商品詳細」欄に入れる。AI 補強 (ai_description_ja) が
    あればそちらを優先し、これは使わない。
    """
    lines = [f"・ブランド: {brand_name}" + (f" ({phonetic})" if phonetic else "")]
    if category_leaf and category_leaf != "その他":
        lines.append(f"・アイテム: {category_leaf}")
    if color_family or color_name:
        lines.append(f"・カラー: {color_family or ''}" + (f" ({color_name})" if color_name and color_name != color_family else ""))
    mat = materials_ja(product.get("description_en", ""))
    if mat:
        lines.append(f"・素材: {mat}")
    if product.get("season"):
        lines.append(f"・シーズン: {product['season']}")
    rows = size_rows(product)
    if rows and classify_size_category(product.get("product_type", "")) == "variation":
        label = ("・サイズ (襟 cm): " if any(r.get("collar") for r in rows) else
                 "・サイズ (ウエスト インチ): " if any(r.get("waist") for r in rows) else "・サイズ: ")
        lines.append(label + " / ".join(f"{r['size_name']} (参考 {r['jp_reference']})" for r in rows))
        lines.append("・サイズ感はブランドの表記です。ご不明な点はご購入前にお問い合わせください")
    elif rows:
        lines.append("・サイズ: " + ", ".join(r["size_name"] for r in rows))
    original = [ln for ln in clean_source_description(product.get("description_en", "")).splitlines()
                if not ln.lower().startswith("material:")]
    if original:
        lines += ["", "【ブランドによる商品説明 (英語原文)】", *original]
    return _strip_accents("\n".join(lines))


def suggest_title(base_title: str, category_leaf: str, max_width: int = 60) -> str:
    """生成タイトルに、幅が収まればカテゴリ名 (日本語の検索語) を足す。"""
    leaf = (category_leaf or "").strip()
    if not leaf or leaf == "その他" or leaf in base_title:
        return base_title
    cand = f"{base_title} {leaf}"
    return cand if _buyma_title_width(cand) <= max_width else base_title


# ---------------------------------------------------------------------------
# シート組み立て
# ---------------------------------------------------------------------------

def build_sheet(product: dict, *, key: str, title: str, comment: str, category_path: list[str],
                color_family: str, color_name: str, tags: list[str], brand_info: dict,
                breakdown: dict, purchase_memo: str, today: Optional[date] = None,
                deadline_days: int = DEFAULT_DEADLINE_DAYS, rank: Optional[int] = None,
                category_note: str = "") -> ListingSheet:
    """1 商品分のシート。brand_info = {"name", "phonetic", "brand_id" (brands.json に有れば)}。"""
    today = today or date.today()
    pt = (product.get("product_type") or "").strip().upper()
    sizes = size_rows(product)
    variation = classify_size_category(pt) == "variation"
    urls = search_urls(product.get("vendor", ""), product.get("title", ""), model_number(product.get("sku", "")))
    b = breakdown
    region = BUY_REGION_BY_COUNTRY.get((b.get("country") or "").upper(), ("", ""))
    deadline = today + timedelta(days=deadline_days)
    images = _image_urls(product)
    F: list[SheetField] = []

    def add(section, label, value, action, note=""):
        F.append(SheetField(section, label, str(value), action, note))

    s = "1. 商品画像"
    for i, u in enumerate(images, 1):
        add(s, "メイン画像" if i == 1 else f"サブ画像 {i - 1}", u, ACTION_INPUT,
            "仕入先の画像を保存してアップロード (JPG/PNG)。1 枚目が一覧に出る" if i == 1 else "")
    if not images:
        add(s, "画像", "(仕入先に画像なし)", ACTION_CHECK, "画像なしでは公開しない")

    s = "2. 商品名"
    add(s, "商品名", title, ACTION_INPUT, f"全角 30 / 半角 60 文字まで (この案は幅 {_buyma_title_width(title)})")

    s = "3. 商品コメント"
    add(s, "商品コメント", comment, ACTION_INPUT,
        "日本語の箇条書きは仕入先データから作成。英語原文と定型文は必要に応じて直す。アクセント文字 (è 等) は不可")

    s = "4. カテゴリ"
    cat_note = "画面のプルダウンで同じ名前を選ぶ。第3階層が無ければ近いもの / その他"
    if category_note:
        cat_note = category_note + "。" + cat_note
    add(s, "カテゴリ (第1 > 第2 > 第3)", " > ".join(category_path), ACTION_SELECT, cat_note)

    s = "5. 価格"
    add(s, "販売価格 (提案)", _yen(b["proposed_price_jpy"]), ACTION_CHECK,
        f"見込み利益 {_yen(b['profit_jpy'])} (売価比 {b['margin_on_price_pct']:.1f}%)。"
        "競合価格を下の検索 URL で見てから決める")
    add(s, "下限価格", _yen(b["min_price_jpy"]), ACTION_INFO,
        f"これ未満にすると利益が {_yen(b['min_profit_jpy'])} を下回る")
    add(s, "BUYMA 検索 (ブランド + 商品名)", urls["buyma_search_url"], ACTION_INFO, "競合の価格を目視で確認 (自動取得はしない)")
    if urls.get("buyma_search_url_sku"):
        add(s, "BUYMA 検索 (ブランド + 品番)", urls["buyma_search_url_sku"], ACTION_INFO, "同じ品番の出品があれば最も比較しやすい")

    s = "6. 配送方法"
    add(s, "配送方法", " / ".join(DEFAULT_SHIPPING_METHODS), ACTION_SELECT,
        f"BUYMA に登録済みの配送方法から選ぶ。原価には国内送料 {_yen(b['domestic_shipping_jpy'])} を計上済み")

    s = "7. 買付地・発送地"
    add(s, "買付地", " > ".join(x for x in region if x) or "(画面で選ぶ)", ACTION_SELECT,
        f"仕入先: {b['display_name']}")
    add(s, "発送地", " > ".join(DEFAULT_SHIP_FROM), ACTION_SELECT,
        "仕入先から手元に届けて国内発送する前提。都道府県は本人の発送元に合わせる")

    s = "8. シーズン・テーマ"
    add(s, "シーズン", product.get("season") or "指定なし", ACTION_SELECT, "仕入先の表記 (例 AW25) に近いものを選ぶ")
    add(s, "テーマ", DEFAULT_THEME, ACTION_SELECT)

    s = "9. 購入期限"
    add(s, "購入期限", deadline.strftime("%Y/%m/%d"), ACTION_CHECK,
        f"作成日 + {deadline_days} 日 (リポジトリの既定)。セール品は在庫が動くので短くしてもよい")

    s = "10. 関税"
    add(s, "関税込み (出品者負担)", "チェックを入れる", ACTION_CHECK,
        "原価に関税・輸入消費税・通関立替手数料を計上済み (DDU)" if b["landed_cost_basis"] == "DDU"
        else "仕入価格に関税込み (DDP)")

    s = "11. 色・サイズ"
    add(s, "色の系統", color_family or "(画面で選ぶ)", ACTION_SELECT)
    add(s, "色名", color_name or "(仕入先ページで確認)", ACTION_INPUT, "全角 13 / 半角 26 文字まで")
    if variation and sizes:
        add(s, "サイズ", "バリエーションあり", ACTION_SELECT)
        for row in sizes:
            kind = ("襟サイズ (cm)" if row.get("collar") else
                    "ウエスト (インチ)。参考日本サイズはブランドのサイズ表で選ぶ" if row.get("waist") else "仕入先表記")
            add(s, f"サイズ名 {row['size_name']}", f"参考日本サイズ: {row['jp_reference']} / 在庫: 買付可 1",
                ACTION_SELECT, f"{kind} {row['source_size']}。参考日本サイズは目安 (ブランドのサイズ表で確認)")
    elif sizes:
        add(s, "サイズ", "バリエーションなし (" + ", ".join(r["size_name"] for r in sizes) + ")", ACTION_SELECT,
            "在庫: 買付可 1")
    else:
        add(s, "サイズ", "(出品できるサイズなし)", ACTION_CHECK, "在庫切れ or 高いサイズのみ → 出品しない")
    if (product.get("priced_out_sizes") or "").strip():
        add(s, "出さないサイズ", product["priced_out_sizes"], ACTION_INFO, "基準より高い価格のサイズ (この価格では赤字になりうる)")

    s = "12. タグ"
    add(s, "タグ", " / ".join(tags) if tags else "(なし)", ACTION_SELECT, "data/tags.json のルールで判定。根拠が明確なものだけ")

    s = "13. 出品メモ・買付先 (購入者には非公開)"
    add(s, "出品メモ", purchase_memo, ACTION_INPUT)
    add(s, "買付先名", b["display_name"][:30], ACTION_INPUT)
    add(s, "買付先 URL", product.get("product_url", ""), ACTION_INPUT, "公開前と注文時に在庫・価格を必ず確認")

    s = "14. ブランド"
    bname = brand_info.get("name") or product.get("vendor", "")
    note = "入力欄に名前を入れて、サジェストから正式なブランドを選ぶ"
    if brand_info.get("phonetic"):
        note += f" (読み: {brand_info['phonetic']})"
    add(s, "ブランド", bname, ACTION_SELECT, note)

    s = "15. 品番・識別メモ"
    model = model_number(product.get("sku", ""))
    add(s, "品番", model or "(なし)", ACTION_INPUT, "ブランドを選ぶと欄が出る。仕入先 SKU: " + (product.get("sku") or "-"))
    ident = "/".join(x for x in [f"色:{color_name}" if color_name else "",
                                 f"サイズ:{sizes[0]['source_size']}" if sizes else ""] if x)
    add(s, "識別メモ", ident or "-", ACTION_INPUT)

    s = "16. 保存"
    add(s, "保存", "「下書き保存する」を押す (公開はしない)", ACTION_CHECK,
        "保存後の URL の数字 (商品ID) を控える → 出品記録に追記するため")

    checks = [
        "ブランドはサジェストから選んだか (『BUYMAに登録されていないブランド』の警告が出ていないか)",
        "カテゴリ 3 階層・色の系統・サイズ (参考日本サイズ) を画面で選んだか",
        "配送方法・発送地の都道府県が本人の設定と合っているか",
        f"競合価格を検索 URL で確認し、販売価格を下限 {_yen(b['min_price_jpy'])} 以上で決めたか",
        "仕入先ページで在庫 (出品するサイズ) と価格が変わっていないか (シート作成後に変わることがある)",
        "商品コメントの機械翻訳・素材表記を直したか",
        "保存は「下書き」。公開は内容を確認してから本人が行う",
    ]
    assumptions = [
        f"為替: 1 {b['currency']} = ¥{b['exchange_rate']:.2f} (ECB 参照値 + 安全バッファ込み、シート作成時点)",
        f"VAT: {b['vat_treatment'] or '-'} — baseblu の en-us 価格は IT VAT 22% 抜きと判断済み。"
        "日本宛ての会計画面で VAT が加算されないことは未確認 (本人の確認待ち)" if b["source_name"] == "baseblu"
        else f"VAT: {b['vat_treatment'] or '-'} (仕入先設定どおり。未検証の仕入先は安全側)",
        f"国際送料 {_yen(b['shipping_jpy'])} (仕入先設定の定額・1 点ずつ買う前提)、関税率 {b['duty_rate'] * 100:.0f}%、"
        f"通関立替手数料 {_yen(b['customs_handling_jpy'])}・海外カード手数料 {_yen(b['purchase_fx_fee_jpy'])} を計上",
        f"BUYMA 手数料: 定率 {b['commission_rate'] * 100:.1f}% + 定額 {_yen(b['fixed_fee_jpy'])}、振込手数料 {_yen(b['bank_transfer_fee_jpy'])}",
    ]
    vendor_name = brand_info.get("name") or product.get("vendor", "")
    heading = f"{'#' + str(rank) + ' ' if rank else ''}{vendor_name} — {product.get('title', '')}"
    summary = {
        "rank": rank or "",
        "brand": vendor_name,
        "brand_tier": brand_tier(product.get("vendor", "")),
        "title_source": product.get("title", ""),
        "supplier": b["display_name"],
        "supplier_url": product.get("product_url", ""),
        "sale_price": f"{b['sale_price']:.2f} {b['currency']}",
        "total_cost_jpy": round(b["total_cost_jpy"]),
        "proposed_price_jpy": b["proposed_price_jpy"],
        "profit_jpy": round(b["profit_jpy"]),
        "min_price_jpy": b["min_price_jpy"],
        "sizes": ", ".join(r["size_name"] for r in sizes),
        "buyma_search_url": urls["buyma_search_url"],
        "buyma_search_url_sku": urls.get("buyma_search_url_sku", ""),
    }
    return ListingSheet(key=key, heading=heading, summary=summary, fields=F, checks=checks,
                        assumptions=[a for a in assumptions if a])


def cost_table(b: dict) -> list[tuple[str, str]]:
    rows = [
        (f"仕入値 {b['sale_price']:.2f} {b['currency']} × {b['exchange_rate']:.2f}", _yen(b["source_price_jpy"])),
    ]
    if _num(b["vat_refund_jpy"]):
        rows.append(("VAT 控除", "−" + _yen(b["vat_refund_jpy"])))
    rows += [
        ("国際送料", _yen(b["shipping_jpy"])),
        (f"関税 ({b['duty_rate'] * 100:.0f}%)", _yen(b["customs_jpy"])),
        ("輸入消費税 (10%)", _yen(b["consumption_tax_jpy"])),
        ("通関立替手数料", _yen(b["customs_handling_jpy"])),
        ("海外カード手数料", _yen(b["purchase_fx_fee_jpy"])),
        ("国内送料", _yen(b["domestic_shipping_jpy"])),
        ("振込手数料", _yen(b["bank_transfer_fee_jpy"])),
        ("**総原価**", "**" + _yen(b["total_cost_jpy"]) + "**"),
        ("販売価格 (提案)", _yen(b["proposed_price_jpy"])),
        (f"BUYMA 手数料 {b['commission_rate'] * 100:.1f}%", "−" + _yen(b["commission_jpy"])),
        ("BUYMA 定額成約手数料", "−" + _yen(b["fixed_fee_jpy"])),
        ("**見込み利益**", f"**{_yen(b['profit_jpy'])}** (売価比 {b['margin_on_price_pct']:.1f}%)"),
        (f"下限価格 (利益 {_yen(b['min_profit_jpy'])})", _yen(b["min_price_jpy"])),
    ]
    return rows


def _image_urls(product: dict) -> list[str]:
    from app.core.bulk_csv import _image_urls as bulk_images
    return bulk_images(product)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", "<br>")


def to_markdown(sheet: ListingSheet, breakdown: dict, generated_at: str) -> str:
    sm = sheet.summary
    lines = [
        f"# 出品シート {sheet.heading}",
        "",
        f"- 作成: {generated_at} / 入力先: {BUYMA_LISTING_FORM_URL} (通常の出品フォーム、本人が手入力して **下書き保存**)",
        f"- 仕入先: {sm['supplier']} — {sm['supplier_url']}",
        f"- 仕入値 {sm['sale_price']} → 総原価 {_yen(sm['total_cost_jpy'])} / 提案価格 {_yen(sm['proposed_price_jpy'])}"
        f" / 見込み利益 {_yen(sm['profit_jpy'])} / 下限価格 {_yen(sm['min_price_jpy'])}",
        f"- BUYMA 検索 (競合価格の目視): {sm['buyma_search_url']}",
    ]
    if sm.get("buyma_search_url_sku"):
        lines.append(f"- BUYMA 検索 (品番): {sm['buyma_search_url_sku']}")
    lines += [
        "",
        "凡例: ✏️ 入力 = そのまま貼る / 🔽 選択 = BUYMA の画面で選ぶ (ID は書いていない) / "
        "⚠️ 確認 = 本人が判断 / ℹ️ 参考 = フォームには入れない",
        "",
        "## フォーム入力 (リポジトリが知っている入力順)",
        "",
    ]
    current = None
    for f in sheet.fields:
        if f.section != current:
            current = f.section
            lines += ["", f"### {current}", "", "| | 項目 | 値 | メモ |", "|---|---|---|---|"]
        if "\n" in f.value:
            lines.append(f"| {ACTION_ICON[f.action]} {f.action} | {f.label} | (下のブロック) | {_md_cell(f.note)} |")
            lines += ["", "```text", f.value, "```", ""]
        else:
            lines.append(f"| {ACTION_ICON[f.action]} {f.action} | {f.label} | {_md_cell(f.value)} | {_md_cell(f.note)} |")
    lines += ["", "## 原価内訳と見込み利益", "", "| 項目 | 金額 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in cost_table(breakdown)]
    lines += ["", "## 前提 (未確認を含む)", ""] + [f"- {a}" for a in sheet.assumptions]
    lines += ["", "## 下書き保存の前のチェック", ""] + [f"- [ ] {c}" for c in sheet.checks]
    return "\n".join(lines) + "\n"


_HTML_CSS = """
body{font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;margin:24px;color:#222;font-size:14px}
h1{font-size:20px;margin:0 0 8px} h2{font-size:16px;margin:20px 0 6px;border-bottom:1px solid #ccc}
h3{font-size:14px;margin:14px 0 4px;color:#444}
table{border-collapse:collapse;width:100%;margin:4px 0} td,th{border:1px solid #ddd;padding:4px 6px;vertical-align:top}
th{background:#f5f5f5;text-align:left} td.act{white-space:nowrap;width:70px}
.a-選択{background:#fff4d6} .a-確認{background:#ffe3e3} .a-参考{color:#555}
pre{white-space:pre-wrap;margin:0;font-family:inherit}
.meta{color:#444} .sheet{page-break-after:always} .sheet:last-child{page-break-after:auto}
button.copy{font-size:11px;margin-left:4px} @media print{button.copy{display:none}}
"""

_HTML_JS = """
function cp(id){var t=document.getElementById(id).innerText;navigator.clipboard.writeText(t);}
"""


def to_html(sheets: list[tuple[ListingSheet, dict]], generated_at: str) -> str:
    e = html.escape
    out = ["<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>出品シート</title>",
           f"<style>{_HTML_CSS}</style><script>{_HTML_JS}</script></head><body>"]
    out.append(f"<p class='meta'>作成 {e(generated_at)} / 入力先 <a href='{BUYMA_LISTING_FORM_URL}'>{BUYMA_LISTING_FORM_URL}</a>"
               " (本人が手入力して <b>下書き保存</b>)。凡例: ✏️入力=貼る / 🔽選択=BUYMA の画面で選ぶ / ⚠️確認 / ℹ️参考</p>")
    n = 0
    for sheet, b in sheets:
        sm = sheet.summary
        out.append("<div class='sheet'>")
        out.append(f"<h1>{e(sheet.heading)}</h1>")
        out.append(f"<p class='meta'>仕入先 {e(sm['supplier'])}: <a href='{e(sm['supplier_url'])}'>{e(sm['supplier_url'])}</a><br>"
                   f"仕入値 {e(sm['sale_price'])} → 総原価 {_yen(sm['total_cost_jpy'])} / 提案価格 <b>{_yen(sm['proposed_price_jpy'])}</b>"
                   f" / 見込み利益 <b>{_yen(sm['profit_jpy'])}</b> / 下限価格 {_yen(sm['min_price_jpy'])}<br>"
                   f"BUYMA 検索: <a href='{e(sm['buyma_search_url'])}'>ブランド+商品名</a>"
                   + (f" / <a href='{e(sm['buyma_search_url_sku'])}'>ブランド+品番</a>" if sm.get("buyma_search_url_sku") else "")
                   + "</p>")
        current = None
        for f in sheet.fields:
            if f.section != current:
                if current is not None:
                    out.append("</table>")
                current = f.section
                out.append(f"<h3>{e(current)}</h3><table>")
            n += 1
            vid = f"v{n}"
            val = e(f.value)
            if f.value.startswith("http"):
                val = f"<a href='{e(f.value)}'>{e(f.value)}</a>"
            copy = (f"<button class='copy' onclick=\"cp('{vid}')\">コピー</button>"
                    if f.action == ACTION_INPUT else "")
            out.append(f"<tr class='a-{e(f.action)}'><td class='act'>{ACTION_ICON[f.action]} {e(f.action)}</td>"
                       f"<th style='width:150px'>{e(f.label)}</th><td><pre id='{vid}'>{val}</pre>{copy}</td>"
                       f"<td style='width:30%'>{e(f.note)}</td></tr>")
        if current is not None:
            out.append("</table>")
        out.append("<h2>原価内訳と見込み利益</h2><table>")
        for k, v in cost_table(b):
            out.append(f"<tr><th>{e(k.replace('**', ''))}</th><td>{e(v.replace('**', ''))}</td></tr>")
        out.append("</table><h2>前提 (未確認を含む)</h2><ul>")
        out += [f"<li>{e(a)}</li>" for a in sheet.assumptions]
        out.append("</ul><h2>下書き保存の前のチェック</h2><ul>")
        out += [f"<li>☐ {e(c)}</li>" for c in sheet.checks]
        out.append("</ul></div>")
    out.append("</body></html>")
    return "\n".join(out)


CSV_COLUMNS = ("rank", "key", "section", "action", "label", "value", "note")


def to_csv(sheets: list[ListingSheet]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for sh in sheets:
        for f in sh.fields:
            w.writerow({"rank": sh.summary.get("rank", ""), "key": sh.key, "section": f.section,
                        "action": f.action, "label": f.label, "value": f.value, "note": f.note})
    return buf.getvalue()
