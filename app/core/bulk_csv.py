"""BUYMA 公式「一括出品編集」用 CSV (items.csv + colorsizes.csv の zip) を作る。

仕様: BUYMA Buyers info「一括出品編集マニュアル」 https://buyersinfo.buyma.com/?page_id=78343
  - アップロード先: https://www.buyma.com/my/sell/bulk/ (本人がブラウザで操作する)
  - zip にする場合のファイル名は items.csv / colorsizes.csv (フォルダではなく 2 ファイルを直接)
  - 全列は不要。最低限「商品ID か 商品管理番号」と「コントロール」があればアップロード可。
    マニュアルに無い列名は無視される。列の並び替えは可
  - 新規出品: 商品ID は空欄必須。商品管理番号で items と colorsizes を紐付ける
  - コントロール: 新規は「公開」か「下書き」。**本モジュールは常に「下書き」しか書かない**
    (公開は BUYMA の画面で本人が内容を確認してから行う)。下書きなら商品名・価格・ID 類は空欄可
  - colorsizes: 並び順は 1 からの連番、サイズ名称は必須、在庫ステータス 1=買付可
    (1 を使うなら items の 買付可数量 が必要)。色を指定しない場合は 色名称=色指定なし / 色系統=0
  - 画像: 商品イメージ1〜20 に Web 上の JPG/GIF/PNG の URL を左詰めで

ID 類 (ブランド・カテゴリ・色系統・配送方法・買付地/発送地) は BUYMA の「ID表」に従う。
data/buyma_id_tables/*.json に本人がダウンロードした ID 表から値を入れるまで、
該当列は空欄 (下書きなので可) にして警告を出す。推測の ID は絶対に書かない。

列名の細部 (例: 「商品イメージ1」か「商品イメージ 1」か) は実際にダウンロードした
items.csv のヘッダと照合すること。--template で本人のダウンロード CSV のヘッダを渡すと、
その列名・並び順に合わせ、テンプレートに無い列は落として警告する。
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

CONTROL_DRAFT = "下書き"
FORBIDDEN_CONTROLS = ("公開", "停止", "削除")

MAX_IMAGES = 20
MAX_MODEL_NUMBERS = 10
MAX_SUPPLIERS = 15
MEMO_MAX_CHARS = 500          # 出品メモ: 全角 500 文字以内
COLOR_NAME_MAX_WIDTH = 26     # 色名称: 全角 13 / 半角 26
MODEL_NUMBER_RE = re.compile(r"^[A-Za-z0-9 _\-.:#]{3,40}$")

ITEMS_COLUMNS: tuple[str, ...] = (
    "商品ID", "商品管理番号", "コントロール", "公開ステータス", "商品名", "ブランド", "ブランド名",
    "モデル", "カテゴリ", "シーズン", "テーマ", "単価", "買付可数量", "購入期限",
    "参考価格/通常出品価格", "参考価格", "商品コメント", "色サイズ補足", "配送方法",
    "買付エリア", "買付都市", "買付ショップ", "発送エリア", "発送都市", "関税込み", "出品メモ",
    *[f"商品イメージ{i}" for i in range(1, MAX_IMAGES + 1)],
    *[f"ブランド型番{i}" for i in range(1, MAX_MODEL_NUMBERS + 1)],
    *[f"ブランド型番識別メモ{i}" for i in range(1, MAX_MODEL_NUMBERS + 1)],
    *[c for i in range(1, MAX_SUPPLIERS + 1) for c in (f"買付先名{i}", f"買付先URL{i}", f"買付先説明{i}")],
)

COLORSIZES_COLUMNS: tuple[str, ...] = (
    "商品ID", "商品管理番号", "商品名", "並び順", "サイズ名称", "サイズ単位", "検索用サイズ",
    "色名称", "色系統", "在庫ステータス", "手元に在庫あり数量", "色サイズリプレイス",
)

# 値が空でも必ず出す列 (それ以外は全行空なら列ごと省く: ID 未設定の列で形式エラーを出さないため)
ITEMS_ALWAYS = ("商品管理番号", "コントロール", "商品名", "単価", "買付可数量")
COLORSIZES_ALWAYS = ("商品管理番号", "並び順", "サイズ名称", "色名称", "色系統", "在庫ステータス")

# 出力の最終形に必ず残っていなければならない列 (テンプレートで落ちたらエラー)
ITEMS_REQUIRED = ("商品管理番号", "コントロール")
COLORSIZES_REQUIRED = ("商品管理番号", "並び順", "サイズ名称", "色名称", "色系統", "在庫ステータス")

ID_TABLE_FILES = ("brands", "categories", "color_families", "shipping", "areas", "defaults")


# ---------------------------------------------------------------------------
# ID 表
# ---------------------------------------------------------------------------

@dataclass
class IdTables:
    """data/buyma_id_tables/*.json の中身。

    各ファイル: {"_placeholder": true/false, "_note": "...", "entries": {名前: ID}}
    defaults.json の entries: shipping_method_ids ("2123_2126" 形式), buy_area_id, buy_city_id,
      ship_area_id, ship_city_id, quantity (買付可数量、既定 1)
    _placeholder が true のファイルは使わない (= 空欄 + 警告)。
    """

    tables: dict[str, dict] = field(default_factory=dict)
    placeholders: list[str] = field(default_factory=list)

    def lookup(self, table: str, key: str) -> str:
        entries = self.tables.get(table) or {}
        if not key:
            return ""
        if key in entries:
            return str(entries[key])
        low = {str(k).lower(): v for k, v in entries.items()}
        v = low.get(key.lower())
        return "" if v is None else str(v)

    def default(self, key: str, fallback: str = "") -> str:
        v = (self.tables.get("defaults") or {}).get(key)
        return fallback if v in (None, "") else str(v)


def load_id_tables(directory: str | Path) -> IdTables:
    d = Path(directory)
    out = IdTables()
    for name in ID_TABLE_FILES:
        path = d / f"{name}.json"
        if not path.exists():
            out.placeholders.append(name)
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("_placeholder", False):
            out.placeholders.append(name)
            continue
        entries = data.get("entries") or {}
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: entries は {{名前: ID}} の dict にしてください")
        out.tables[name] = entries
    return out


# ---------------------------------------------------------------------------
# 行の組み立て (純粋関数)
# ---------------------------------------------------------------------------

def management_number(product: dict) -> str:
    """商品管理番号: <仕入先>-<SKU or ハンドル> を英数と - _ だけにして 40 文字以内。"""
    source = (product.get("source_name") or "src").strip().lower()
    key = (product.get("sku") or "").strip()
    if not key:
        url = product.get("product_url") or ""
        m = re.search(r"/products/([^/?#]+)", url)
        key = m.group(1) if m else (product.get("title") or "item")
    raw = f"{source}-{key}"
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    return clean[:40]


def _width(text: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 1 for c in text)


def _image_urls(product: dict) -> list[str]:
    urls = [product.get("image_url") or ""] + (product.get("sub_images") or "").split("|")
    out = []
    for u in urls:
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http") and u not in out:
            out.append(u)
    return out[:MAX_IMAGES]


def build_purchase_memo(product: dict) -> str:
    """出品メモ (購入者には見えない本人用メモ)。仕入先・原価・想定利益。"""
    parts = [
        f"仕入先:{product.get('source_name', '')}",
        f"URL:{product.get('product_url', '')}",
        f"仕入値:{product.get('sale_price_eur', '')}{product.get('currency', '') or ''}",
        f"原価:¥{product.get('total_cost_jpy', '')}",
        f"想定利益:¥{product.get('profit_jpy', '')}",
    ]
    if product.get("priced_out_sizes"):
        parts.append(f"高いため除外したサイズ:{product['priced_out_sizes']}")
    return " / ".join(parts)[:MEMO_MAX_CHARS]


def build_item_row(product: dict, *, title: str, comment: str, category_path: list[str] | str,
                   tables: IdTables, warnings: list[str]) -> dict:
    mgmt = management_number(product)
    cat_key = " > ".join(category_path) if isinstance(category_path, (list, tuple)) else str(category_path or "")
    vendor = (product.get("vendor") or "").strip()

    brand_id = tables.lookup("brands", vendor)
    category_id = tables.lookup("categories", cat_key)
    if not brand_id:
        warnings.append(f"{mgmt}: ブランド ID 未設定 ({vendor}) → ブランド名だけ入れて下書き")
    if not category_id:
        warnings.append(f"{mgmt}: カテゴリ ID 未設定 ({cat_key}) → 空欄で下書き")

    row = {
        "商品管理番号": mgmt,
        "コントロール": CONTROL_DRAFT,
        "商品名": title,
        "ブランド": brand_id,
        "ブランド名": vendor if not brand_id else "",
        "カテゴリ": category_id,
        "単価": str(int(float(product.get("recommended_price") or 0))) or "",
        "買付可数量": tables.default("quantity", "1"),
        "参考価格/通常出品価格": "0",
        "商品コメント": comment,
        "配送方法": tables.default("shipping_method_ids"),
        "買付エリア": tables.default("buy_area_id"),
        "買付都市": tables.default("buy_city_id"),
        "発送エリア": tables.default("ship_area_id"),
        "発送都市": tables.default("ship_city_id"),
        "出品メモ": build_purchase_memo(product),
        "買付先名1": (product.get("source_name") or "")[:30],
        "買付先URL1": (product.get("product_url") or "")[:2000],
    }
    if not row["配送方法"]:
        warnings.append(f"{mgmt}: 配送方法 ID 未設定 → 空欄で下書き (公開前に BUYMA で設定)")
    for i, url in enumerate(_image_urls(product), 1):
        row[f"商品イメージ{i}"] = url
    sku = (product.get("sku") or "").strip()
    if sku and MODEL_NUMBER_RE.match(sku):
        row["ブランド型番1"] = sku
    elif sku:
        warnings.append(f"{mgmt}: 品番 {sku!r} は BUYMA の型番形式外のため未記入")
    return row


def build_colorsize_rows(product: dict, *, sizes: Iterable[str], color_family_ja: str,
                         color_name: str, tables: IdTables, warnings: list[str]) -> list[dict]:
    """在庫あり・基準価格のサイズだけを行にする (サイズ不明なら空リスト = 出品しない)。"""
    mgmt = management_number(product)
    family_id = tables.lookup("color_families", color_family_ja)
    name = (color_name or "").strip()
    if family_id and name and _width(name) <= COLOR_NAME_MAX_WIDTH:
        color_cell, family_cell = name, family_id
    else:
        if name:
            warnings.append(f"{mgmt}: 色系統 ID 未設定 ({color_family_ja}) → 色指定なしで下書き")
        color_cell, family_cell = "色指定なし", "0"
    rows = []
    for i, size in enumerate([s for s in sizes if s], 1):
        rows.append({
            "商品管理番号": mgmt,
            "並び順": str(i),
            "サイズ名称": size,
            "色名称": color_cell,
            "色系統": family_cell,
            "在庫ステータス": "1",
        })
    return rows


# ---------------------------------------------------------------------------
# 検証と書き出し
# ---------------------------------------------------------------------------

def validate_rows(items: list[dict], colorsizes: list[dict]) -> list[str]:
    """致命的な問題のリスト (空なら OK)。公開・停止・削除は 1 行でもあれば NG。"""
    errors = []
    mgmts = set()
    for r in items:
        if r.get("コントロール") != CONTROL_DRAFT:
            errors.append(f"{r.get('商品管理番号')}: コントロールが「下書き」以外 ({r.get('コントロール')!r})")
        if r.get("商品ID"):
            errors.append(f"{r.get('商品管理番号')}: 新規出品で商品ID が入っている")
        m = r.get("商品管理番号")
        if not m:
            errors.append("商品管理番号が空の行がある")
        elif m in mgmts:
            errors.append(f"{m}: 商品管理番号が重複")
        mgmts.add(m)
    by_item: dict[str, list[int]] = {}
    for r in colorsizes:
        m = r.get("商品管理番号")
        if m not in mgmts:
            errors.append(f"{m}: colorsizes にあるが items に無い")
        if not r.get("サイズ名称"):
            errors.append(f"{m}: サイズ名称が空")
        by_item.setdefault(m, []).append(int(r.get("並び順") or 0))
    for m in mgmts:
        orders = sorted(by_item.get(m, []))
        if not orders:
            errors.append(f"{m}: colorsizes の行が無い")
        elif orders != list(range(1, len(orders) + 1)):
            errors.append(f"{m}: 並び順が 1 からの連番になっていない")
    return errors


def select_columns(rows: list[dict], all_columns: Iterable[str], always: Iterable[str],
                   template: Optional[list[str]] = None, warnings: Optional[list[str]] = None) -> list[str]:
    always = set(always)
    used = [c for c in all_columns if c in always or any(r.get(c) for r in rows)]
    if not template:
        return used
    tmpl = [c.strip() for c in template]
    missing = [c for c in used if c not in tmpl]
    if missing and warnings is not None:
        warnings.append(f"テンプレートに無い列は出力しません: {', '.join(missing[:8])}"
                        + (" ..." if len(missing) > 8 else ""))
    return [c for c in tmpl if c in used]


def _csv_bytes(rows: list[dict], columns: list[str], encoding: str) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in columns})
    text = buf.getvalue()
    if encoding == "sjis":
        return text.encode("cp932", errors="replace")
    return text.encode("utf-8")


def read_template_header(path: str | Path) -> list[str]:
    """本人が BUYMA からダウンロードした items / colorsizes CSV の 1 行目 (列名) を読む。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: 文字コードを判別できません (utf8 / sjis)")
    return next(csv.reader(io.StringIO(text)))


def write_bulk_zip(items: list[dict], colorsizes: list[dict], out_path: str | Path, *,
                   encoding: str = "utf8", items_template: Optional[list[str]] = None,
                   colorsizes_template: Optional[list[str]] = None,
                   warnings: Optional[list[str]] = None) -> Path:
    if encoding not in ("utf8", "sjis"):
        raise ValueError("encoding は utf8 か sjis")
    errors = validate_rows(items, colorsizes)
    if errors:
        raise ValueError("一括出品 CSV の検証エラー:\n  " + "\n  ".join(errors))
    item_cols = select_columns(items, ITEMS_COLUMNS, ITEMS_ALWAYS, items_template, warnings)
    cs_cols = select_columns(colorsizes, COLORSIZES_COLUMNS, COLORSIZES_ALWAYS, colorsizes_template, warnings)
    # テンプレートで列を落とした後の最終形で、紐付け・下書き指定に必要な列が残っているか確認する
    for required in ITEMS_REQUIRED:
        if required not in item_cols:
            raise ValueError(f"items.csv に必須列 {required} がありません (テンプレートを確認)")
    for required in COLORSIZES_REQUIRED:
        if required not in cs_cols:
            raise ValueError(f"colorsizes.csv に必須列 {required} がありません (テンプレートを確認)")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("items.csv", _csv_bytes(items, item_cols, encoding))
        zf.writestr("colorsizes.csv", _csv_bytes(colorsizes, cs_cols, encoding))
    return out
