"""
generate_listing_sheet.py
-------------------------
BUYMA の通常の出品フォーム (https://www.buyma.com/my/sell/new?tab=b) に本人が手入力するための
「出品シート」を作る (Markdown 1 商品 1 ファイル + 印刷用 HTML + CSV)。BUYMA にはアクセスしない。

    # 候補 CSV (select_listing_candidates.py の出力) の上位 3 件
    python3 scripts/generate_listing_sheet.py --limit 3

    # 利益商品 CSV から直接 (出品判定 OK のものを期待値順に)
    python3 scripts/generate_listing_sheet.py --csv outputs/reports/2026-10-08_baseblu_profitable_products.csv --limit 3

    # 出力を別の場所にもコピー
    python3 scripts/generate_listing_sheet.py --limit 3 --copy-to /path/to/folder

出力: outputs/listing_sheets/<日時>/ (gitignore 済み。価格・在庫は作成時点の値)
  - 01_<商品管理番号>.md ... 1 商品ずつ
  - listing_sheets.html   ... 全商品を 1 ファイルに (印刷時は 1 商品 1 ページ、コピー用ボタン付き)
  - listing_sheets.csv    ... 1 行 = 1 項目
  - index.md              ... 一覧 (原価・提案価格・利益・BUYMA 検索 URL)

手順 (本人):
  1. 仕入先ページで在庫・価格を確認 → 2. 出品フォームにシートの順で入力 (🔽 は画面で選ぶ)
  3. 「下書き保存する」 → 4. 内容を確認して公開 (本人) → 5. 商品 ID を控えて出品記録へ:

    # シート #1 を商品 ID 133231149 で下書き保存した (BUYMA で価格を変えたら @価格 も)
    python3 scripts/generate_listing_sheet.py --record 1=133231149
    python3 scripts/generate_listing_sheet.py --record 2=133231150@78000
    → outputs/reports/<日付>_auto_listing_results.csv に追記 (check_inventory / update_listed_prices の対象)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.core.bulk_csv import build_purchase_memo, management_number  # noqa: E402
from app.core.candidate_select import canonical_brand, load_brand_tiers  # noqa: E402
from app.core.listing_sheet import (  # noqa: E402
    DEFAULT_DEADLINE_DAYS,
    DEFAULT_MIN_PROFIT_JPY,
    build_sheet,
    cost_breakdown,
    gendered_category_path,
    structured_description_ja,
    suggest_title,
    to_csv,
    to_html,
    to_markdown,
)
from app.utils.listing_helpers import (  # noqa: E402
    append_result_rows,
    build_result_row,
    evaluate_listing_readiness,
    normalize_item_id,
)
from app.utils.reports import latest_report  # noqa: E402

SHEETS_DIR = PROJECT_ROOT / "outputs" / "listing_sheets"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"


def _bal():
    """buyma_auto_listing の純粋関数 (タイトル・説明文・カテゴリ・色・タグ) を使う。ブラウザは起動しない。"""
    import buyma_auto_listing
    return buyma_auto_listing


def brand_info(vendor: str, brands_data: dict, tiers: dict) -> dict:
    """brands.json (読むだけ。BUYMA のブランド API は呼ばない) から表示名・読み・ID。"""
    name = canonical_brand(vendor, tiers)
    known = {k.lower(): v for k, v in (brands_data.get("brands") or {}).items()}
    info = known.get(name.lower()) or known.get((vendor or "").lower()) or {}
    return {"name": name, "phonetic": info.get("phonetic") or "", "brand_id": info.get("brand_id")}


_REVIEW_REASONS = ("高額商品", "品番なし")
_NON_CONTENT_REASONS = ("利益基準",) + _REVIEW_REASONS


def build_sheets(products: list[dict], *, limit: int, min_profit: float, deadline_days: int,
                 include_review: bool = False, today: date | None = None) -> tuple[list, list]:
    bal = _bal()
    cat_data = bal.load_categories()
    tag_rules = bal.load_tags()
    brands_data = bal.load_brands()
    tiers = load_brand_tiers()
    sheets, skipped = [], []
    for p in products:
        if limit and len(sheets) >= limit:
            break
        binfo = brand_info(p.get("vendor", ""), brands_data, tiers)
        shown = {**p, "vendor": binfo["name"]}          # タイトル・説明文は BUYMA のブランド表記で
        cat_path, cat_note = gendered_category_path(bal.resolve_listing_category(p, cat_data), p.get("gender", ""))
        cat_label = " > ".join(cat_path)
        color_family, color_name = bal.resolve_listing_color(p)
        # 日本語の説明: AI 補強があればそれ、無ければ仕入先データからの箇条書き + 英語原文 (単語置換の機械翻訳は使わない)
        desc_ja = p.get("ai_description_ja") or structured_description_ja(
            p, brand_name=binfo["name"], phonetic=binfo["phonetic"], category_leaf=cat_path[-1] if cat_path else "",
            color_family=color_family, color_name=color_name)
        comment = bal.generate_description(p["title"], shown["vendor"], p.get("sku", ""), p.get("description_en", ""),
                                           cat_label, desc_ja=desc_ja)
        b = cost_breakdown(p, min_profit_jpy=min_profit)
        # 内容の判定 (画像・カテゴリ・サイズ・コメント) だけ使う。利益は下で「今の為替で再計算した値」と
        # --min-profit で判定する (evaluate_listing_readiness の 利益 ¥10,000 / 15% 基準は自動出品用)
        verdict, reasons = evaluate_listing_readiness(
            {**p, "profit_jpy": b["profit_jpy"], "expected_margin_pct": b["margin_on_price_pct"]},
            b["proposed_price_jpy"], cat_label, comment)
        if verdict == "NG":
            # 利益の NG だけなら外す (下の --min-profit 判定に任せる)。内容の NG は残す
            content_blockers = [r for r in reasons if not r.startswith(_NON_CONTENT_REASONS)]
            if not content_blockers:
                verdict = "要確認" if any(r.startswith(_REVIEW_REASONS) for r in reasons) else "出品OK"
        if verdict == "NG" or (verdict != "出品OK" and not include_review):
            skipped.append((p.get("title", ""), f"{verdict}: {reasons[:2]}"))
            continue
        if b["profit_jpy"] < min_profit:
            skipped.append((p.get("title", ""), f"現在の為替で利益 ¥{b['profit_jpy']:,.0f} < ¥{min_profit:,.0f}"))
            continue
        title = suggest_title(bal.resolve_listing_title(shown, cat_label), cat_path[-1] if cat_path else "")
        sheet = build_sheet(
            p, key=management_number(p), title=title, comment=comment, category_path=cat_path,
            color_family=color_family, color_name=color_name, tags=bal.determine_tags(p, tag_rules),
            brand_info=binfo, breakdown=b, purchase_memo=build_purchase_memo(p),
            today=today, deadline_days=deadline_days, rank=len(sheets) + 1, category_note=cat_note,
        )
        sheet.product = p
        sheets.append((sheet, b))
    return sheets, skipped


def latest_manifest() -> Path | None:
    found = sorted(SHEETS_DIR.glob(f"*/{MANIFEST_NAME}"))
    return found[-1] if found else None


def record_listings(specs: list[str], manifest_path: Path, reports_dir: Path = REPORTS_DIR,
                    now: datetime | None = None) -> int:
    """'1=133231149' / '<商品管理番号>=133231149@98000' → 出品記録 (results CSV) に追記。"""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    now = now or datetime.now()
    rows = []
    for spec in specs:
        ref, _, rest = spec.partition("=")
        item_id, _, price = rest.partition("@")
        item_id = normalize_item_id(item_id)
        price = price.strip()
        if price and not (price.isdigit() and int(price) > 0):
            print(f"❌ {spec!r}: 価格は正の整数 (円) で指定してください (例 1=133231149@98000)")
            continue
        hit = next((it for it in items if str(it["rank"]) == ref.strip() or it["key"] == ref.strip()), None)
        if not hit or not item_id:
            print(f"❌ {spec!r}: シート番号/商品管理番号が見つからないか、商品 ID が数字ではありません")
            continue
        product = dict(hit["product"])
        product["recommended_price"] = price.strip() or str(hit.get("proposed_price_jpy") or product.get("recommended_price", ""))
        rows.append(build_result_row(product, "draft", item_id, now.strftime("%Y-%m-%d %H:%M:%S")))
    if not rows:
        return 0
    path = reports_dir / f"{now:%Y-%m-%d}_auto_listing_results.csv"
    append_result_rows(str(path), rows)
    print(f"✅ {len(rows)} 件を出品記録に追記: {path}")
    print("   ※ BUYMA の画面でサイズを変えた場合は listed_sizes も直してください")
    return len(rows)


MANIFEST_NAME = "sheets_manifest.json"
MANIFEST_PRODUCT_KEYS = ("title", "vendor", "sku", "product_type", "product_url", "source_name",
                         "available_sizes", "sizes", "priced_out_sizes", "color", "recommended_price")


def write_outputs(sheets: list, out_dir: Path, generated_at: str, products_for_manifest: list[dict]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    index = ["# 出品シート一覧", "", f"作成: {generated_at}。価格・在庫は作成時点。入力前に仕入先ページで確認すること。", "",
             "| # | ブランド / 商品 | 原価 | 提案価格 | 見込み利益 | 下限価格 | サイズ | 仕入先 | BUYMA 検索 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, (sheet, b) in enumerate(sheets, 1):
        p = out_dir / f"{i:02d}_{sheet.key}.md"
        p.write_text(to_markdown(sheet, b, generated_at), encoding="utf-8")
        paths.append(p)
        sm = sheet.summary
        index.append(f"| {i} | {sm['brand']} / {sm['title_source']} | ¥{sm['total_cost_jpy']:,} | ¥{sm['proposed_price_jpy']:,}"
                     f" | ¥{sm['profit_jpy']:,} | ¥{sm['min_price_jpy']:,} | {sm['sizes']} | [仕入先]({sm['supplier_url']})"
                     f" | [商品名]({sm['buyma_search_url']})"
                     + (f" / [品番]({sm['buyma_search_url_sku']})" if sm.get("buyma_search_url_sku") else "") + " |")
    (out_dir / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    (out_dir / "listing_sheets.html").write_text(to_html(sheets, generated_at), encoding="utf-8")
    # Excel でも開けるように BOM 付き UTF-8
    (out_dir / "listing_sheets.csv").write_text(to_csv([s for s, _ in sheets]), encoding="utf-8-sig")
    # --record で出品記録に追記するための対応表 (シート番号 / 商品管理番号 → 商品データ)
    manifest = {"generated_at": generated_at, "items": [
        {"rank": i, "key": sheet.key, "proposed_price_jpy": b["proposed_price_jpy"],
         "product": {k: v for k, v in sheet_product.items() if k in MANIFEST_PRODUCT_KEYS}}
        for i, ((sheet, b), sheet_product) in enumerate(zip(sheets, products_for_manifest), 1)]}
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_dir / "index.md", out_dir / "listing_sheets.html", out_dir / "listing_sheets.csv",
            out_dir / MANIFEST_NAME, *paths]


def main(argv=None):
    from app.utils.env import load_project_env
    load_project_env()
    ap = argparse.ArgumentParser(description="手入力用の出品シートを作る (BUYMA にはアクセスしない)")
    ap.add_argument("--csv", default="latest",
                    help="候補 CSV (*_listing_candidates.csv) か利益商品 CSV。既定は最新の候補 CSV → 無ければ利益商品 CSV")
    ap.add_argument("--source", help="仕入先名で最新 CSV を絞る")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--min-profit", type=float, default=DEFAULT_MIN_PROFIT_JPY,
                    help="下限価格の基準にする利益 (円、既定 5,000)")
    ap.add_argument("--deadline-days", type=int, default=DEFAULT_DEADLINE_DAYS)
    ap.add_argument("--include-review", action="store_true", help="「要確認」判定も含める (NG は常に除外)")
    ap.add_argument("--out-dir", help="出力先 (既定 outputs/listing_sheets/<日時>)")
    ap.add_argument("--copy-to", help="出力一式をこのフォルダにもコピーする")
    ap.add_argument("--record", action="append", metavar="N=商品ID[@価格]",
                    help="下書き保存した商品 ID を出品記録に追記 (N はシート番号か商品管理番号)。複数可")
    ap.add_argument("--manifest", help="--record で使う sheets_manifest.json (既定は最新のシート)")
    args = ap.parse_args(argv)

    if args.record:
        mpath = Path(args.manifest) if args.manifest else latest_manifest()
        if not mpath or not mpath.exists():
            print("❌ sheets_manifest.json が見つかりません (先にシートを作るか --manifest で指定)")
            sys.exit(1)
        if record_listings(args.record, mpath) == 0:
            sys.exit(1)
        return

    csv_path = args.csv
    from_candidates = False
    if csv_path == "latest":
        csv_path = latest_report("listing_candidates.csv", source=args.source, reports_dir=str(REPORTS_DIR))
        from_candidates = bool(csv_path)
        if not csv_path:
            csv_path = "latest"
    else:
        from_candidates = "listing_candidates" in Path(csv_path).name
    bal = _bal()
    # 候補 CSV は選定済みの順位どおり、利益商品 CSV は期待値順
    products = bal.load_products(csv_path=csv_path, source=args.source, sort=not from_candidates)
    sheets, skipped = build_sheets(products, limit=args.limit, min_profit=args.min_profit,
                                   deadline_days=args.deadline_days, include_review=args.include_review)
    for title, why in skipped:
        print(f"  ⏭ {title[:40]} ({why})")
    if not sheets:
        print("❌ シートを作れる商品がありません")
        sys.exit(1)
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M")
    out_dir = Path(args.out_dir) if args.out_dir else SHEETS_DIR / now.strftime("%Y%m%d_%H%M%S")
    paths = write_outputs(sheets, out_dir, generated_at, [sh.product for sh, _ in sheets])
    print(f"\n✅ 出品シート {len(sheets)} 件 → {out_dir}")
    for sheet, b in sheets:
        sm = sheet.summary
        print(f"   {sheet.heading[:60]} | 提案 ¥{sm['proposed_price_jpy']:,} (下限 ¥{sm['min_price_jpy']:,})"
              f" | 利益 ¥{sm['profit_jpy']:,}")
    if args.copy_to:
        dest = Path(args.copy_to)
        dest.mkdir(parents=True, exist_ok=True)
        for p in paths:
            shutil.copy2(p, dest / p.name)
        print(f"   コピー: {dest}")
    print(f"\n次の手順 (本人): {out_dir / 'listing_sheets.html'} を開き、仕入先で在庫・価格を確認してから\n"
          "  https://www.buyma.com/my/sell/new?tab=b にシートの順で入力 → 「下書き保存する」 (公開は確認後に本人)")


if __name__ == "__main__":
    main()
