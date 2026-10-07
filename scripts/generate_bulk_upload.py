"""
generate_bulk_upload.py
------------------------
利益商品 CSV から BUYMA 公式「一括出品編集」用の zip (items.csv + colorsizes.csv) を作る。
**すべて下書き** で、BUYMA には一切アクセスしない。アップロードと公開は本人が行う。

    # 利益が出る出品OK商品の先頭 3 件 (最初は少数で試す)
    python3 scripts/generate_bulk_upload.py --limit 3

    # Shift_JIS で出す / 本人がダウンロードした CSV の列名・並びに合わせる
    python3 scripts/generate_bulk_upload.py --limit 3 --encoding sjis \\
        --items-template ~/Downloads/items.utf8.csv --colorsizes-template ~/Downloads/colorsizes.utf8.csv

    # アップロード後、BUYMA の「下書き」リストをダウンロードした items CSV から
    # 商品管理番号 → 商品ID を取り込み、出品記録 (在庫・価格確認の対象) に追記する
    python3 scripts/generate_bulk_upload.py --import-ids ~/Downloads/items.utf8.csv

手順 (本人):
  1. 出力された outputs/bulk/*_buyma_bulk_draft.zip を https://www.buyma.com/my/sell/bulk/
     の「商品リストをアップロードする」から登録 → 下書きになる
  2. BUYMA の画面で 1 件ずつ内容 (カテゴリ・ブランド・配送方法・画像・サイズ) を確認して公開
  3. 下書き/出品リストをダウンロードし、--import-ids で商品 ID を取り込む

ID 類 (ブランド・カテゴリ・色系統・配送方法・地域) は data/buyma_id_tables/*.json を本人が
BUYMA の「ID表」から埋めるまで空欄 (下書きなので登録は可、公開前に画面で選ぶ)。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core.bulk_csv import (  # noqa: E402
    build_colorsize_rows,
    build_item_row,
    load_id_tables,
    management_number,
    read_template_header,
    write_bulk_zip,
)
from app.utils.listing_helpers import (  # noqa: E402
    append_result_rows,
    build_result_row,
    evaluate_listing_readiness,
    format_size_name_for_listing,
    listing_sizes,
    normalize_item_id,
)

BULK_DIR = PROJECT_ROOT / "outputs" / "bulk"
ID_TABLE_DIR = PROJECT_ROOT / "data" / "buyma_id_tables"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"


def _bal():
    """buyma_auto_listing の純粋関数 (タイトル・説明文・カテゴリ・色) を使う。ブラウザは起動しない。"""
    import buyma_auto_listing
    return buyma_auto_listing


def prepare(products: list[dict], tables, include_review: bool = False) -> dict:
    """商品リスト → {"items", "colorsizes", "manifest", "warnings", "skipped"} (BUYMA 非アクセス)。"""
    bal = _bal()
    cat_data = bal.load_categories()
    items, colorsizes, manifest, warnings, skipped = [], [], [], [], []
    seen = set()
    for p in products:
        cat_path = bal.resolve_listing_category(p, cat_data)
        cat_label = " > ".join(cat_path)
        comment = bal.generate_description(p["title"], p["vendor"], p.get("sku", ""), p.get("description_en", ""),
                                           cat_label, desc_ja=p.get("ai_description_ja") or None)
        price = int(float(p.get("recommended_price") or 0))
        verdict, reasons = evaluate_listing_readiness(p, price, cat_label, comment)
        if verdict == "出品OK" and p.get("ai_verdict") == "hold":
            verdict, reasons = "要確認", [f"AI審査 hold: {p.get('ai_reason') or ''}".strip()]
        if verdict != "出品OK" and not include_review:
            skipped.append((p["title"], f"{verdict}: {reasons[:2]}"))
            continue
        sizes_raw = [s.strip() for s in listing_sizes(p).split(",") if s.strip()]
        sizes = [format_size_name_for_listing(s, p.get("product_type", "")) or s for s in sizes_raw]
        if not sizes:
            skipped.append((p["title"], "出品できるサイズが無い (在庫なし or 高いサイズのみ)"))
            continue
        mgmt = management_number(p)
        if mgmt in seen:
            skipped.append((p["title"], f"商品管理番号が重複 ({mgmt})"))
            continue
        seen.add(mgmt)
        title = bal.resolve_listing_title(p, cat_label)
        color_family, color_name = bal.resolve_listing_color(p)
        item_warn: list[str] = []
        items.append(build_item_row(p, title=title, comment=comment, category_path=cat_path,
                                    tables=tables, warnings=item_warn))
        colorsizes.extend(build_colorsize_rows(p, sizes=sizes, color_family_ja=color_family,
                                               color_name=color_name, tables=tables, warnings=item_warn))
        warnings.extend(item_warn)
        manifest.append({
            "management_number": mgmt, "title": p.get("title", ""), "vendor": p.get("vendor", ""),
            "recommended_price": p.get("recommended_price", ""), "profit_jpy": p.get("profit_jpy", ""),
            "sku": p.get("sku", ""), "product_type": p.get("product_type", ""),
            "product_url": p.get("product_url", ""), "source_name": p.get("source_name", ""),
            "available_sizes": ",".join(sizes_raw), "category": cat_label, "verdict": verdict,
        })
    return {"items": items, "colorsizes": colorsizes, "manifest": manifest,
            "warnings": warnings, "skipped": skipped}


def generate(args) -> Path | None:
    bal = _bal()
    products = bal.load_products(max_price=args.max_price, min_profit=args.min_profit,
                                 csv_path=args.csv, source=args.source)
    products.sort(key=bal._listing_sort_key, reverse=True)
    tables = load_id_tables(args.id_tables)
    if tables.placeholders:
        print(f"ℹ️ ID 表が未設定: {', '.join(tables.placeholders)} → 該当列は空欄 (下書きは登録可)")

    res = prepare(products, tables, include_review=args.include_review)
    for title, why in res["skipped"]:
        print(f"  ⏭ {title[:40]} ({why})")
    items = res["items"][: args.limit] if args.limit else res["items"]
    keep = {r["商品管理番号"] for r in items}
    colorsizes = [r for r in res["colorsizes"] if r["商品管理番号"] in keep]
    manifest = [m for m in res["manifest"] if m["management_number"] in keep]
    if not items:
        print("❌ 一括出品に載せる商品がありません")
        return None

    warnings = [w for w in res["warnings"] if w.split(":")[0] in keep]
    items_tmpl = read_template_header(args.items_template) if args.items_template else None
    cs_tmpl = read_template_header(args.colorsizes_template) if args.colorsizes_template else None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    zip_path = write_bulk_zip(items, colorsizes, out_dir / f"{stamp}_buyma_bulk_draft.zip",
                              encoding=args.encoding, items_template=items_tmpl,
                              colorsizes_template=cs_tmpl, warnings=warnings)
    manifest_path = out_dir / f"{stamp}_buyma_bulk_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "zip": zip_path.name, "items": manifest}, f,
                  ensure_ascii=False, indent=2)

    print(f"\n✅ 下書き用 zip: {zip_path}  ({len(items)} 商品 / {len(colorsizes)} 色サイズ行)")
    print(f"   対応表: {manifest_path}")
    for m in manifest:
        print(f"   - {m['management_number']} | ¥{int(float(m['recommended_price'] or 0)):,} "
              f"(利益 ¥{int(float(m['profit_jpy'] or 0)):,}) | {m['title'][:40]}")
    if warnings:
        print(f"\n⚠️ 警告 {len(warnings)} 件 (公開前に BUYMA の画面で補う):")
        for w in warnings[:30]:
            print(f"   - {w}")
    print("\n次の手順 (本人): https://www.buyma.com/my/sell/bulk/ → 商品リストをアップロード → "
          "下書きを 1 件ずつ確認して公開 → リストをダウンロードして --import-ids")
    return zip_path


def import_ids(downloaded_items_csv: str, bulk_dir: Path, reports_dir: Path) -> int:
    """BUYMA からダウンロードした items CSV (商品ID + 商品管理番号) を出品記録に取り込む。"""
    header = read_template_header(downloaded_items_csv)
    raw = Path(downloaded_items_csv).read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.DictReader(text.splitlines()))
    if "商品ID" not in header or "商品管理番号" not in header:
        print("❌ 商品ID / 商品管理番号 の列がありません (BUYMA の一括出品編集からダウンロードした items CSV を指定)")
        return 0
    ids = {r["商品管理番号"].strip(): normalize_item_id(r.get("商品ID")) for r in rows
           if (r.get("商品管理番号") or "").strip()}
    manifests = {}
    for path in sorted(bulk_dir.glob("*_buyma_bulk_manifest.json")):
        with open(path, encoding="utf-8") as f:
            for m in json.load(f).get("items", []):
                manifests[m["management_number"]] = m
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_rows = []
    for mgmt, item_id in ids.items():
        m = manifests.get(mgmt)
        if not m or not item_id:
            continue
        product = {**m, "available_sizes": m.get("available_sizes", "")}
        out_rows.append(build_result_row(product, "draft", item_id, now))
    if not out_rows:
        print("ℹ️ 取り込める行がありません (manifest に無い商品管理番号、または商品ID が空)")
        return 0
    path = reports_dir / f"{datetime.now():%Y-%m-%d}_auto_listing_results.csv"
    append_result_rows(str(path), out_rows)
    print(f"✅ {len(out_rows)} 件の商品 ID を {path} に追記 (check_inventory / update_listed_prices の対象)")
    return len(out_rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="BUYMA 一括出品 (下書き) 用 zip を作る。BUYMA にはアクセスしない")
    ap.add_argument("--csv", default="latest", help="利益商品 CSV (*_profitable_products.csv)。既定は最新")
    ap.add_argument("--source", help="仕入先名で最新 CSV を絞る")
    ap.add_argument("--limit", type=int, default=3, help="商品数の上限 (既定 3。最初は少数で確認)")
    ap.add_argument("--max-price", type=int)
    ap.add_argument("--min-profit", type=int)
    ap.add_argument("--include-review", action="store_true", help="要確認判定の商品も含める")
    ap.add_argument("--encoding", choices=("utf8", "sjis"), default="utf8")
    ap.add_argument("--items-template", help="BUYMA からダウンロードした items CSV (列名・並びを合わせる)")
    ap.add_argument("--colorsizes-template", help="BUYMA からダウンロードした colorsizes CSV")
    ap.add_argument("--id-tables", default=str(ID_TABLE_DIR))
    ap.add_argument("--out-dir", default=str(BULK_DIR))
    ap.add_argument("--import-ids", metavar="ITEMS_CSV",
                    help="BUYMA からダウンロードした items CSV の商品ID を出品記録に取り込む")
    args = ap.parse_args(argv)
    if args.import_ids:
        import_ids(args.import_ids, Path(args.out_dir), REPORTS_DIR)
        return
    if generate(args) is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
