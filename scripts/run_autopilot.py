"""
run_autopilot.py — 仕入れ候補の取得 → 利益計算 → 相場 → AI 補強 → 下書き作成 を 1 コマンドで
--------------------------------------------------------------------------
run_weekly.py の工程に「AI 補強 (出品文・カテゴリ・審査)」と「下書き作成」を足したもの。
決定論的な工程 (利益計算・相場フィルタ) には AI を使わず、AI は上位候補にだけ使う。

使い方 (Mac のターミナルで):

    cd ~/buyma_automation
    python3 scripts/run_autopilot.py                 # 取得 → 利益 → 相場 → AI 補強 (下書きなし)
    python3 scripts/run_autopilot.py --draft 3       # さらに上位 3 件を BUYMA に下書き保存
    python3 scripts/run_autopilot.py --skip-scrape   # 今日取得済みのセール CSV を再利用
    python3 scripts/run_autopilot.py --skip-market   # 相場取得を飛ばす (速いが精度が落ちる)
    python3 scripts/run_autopilot.py --ai-limit 10   # AI に送る件数を絞る (費用を抑える)
    python3 scripts/run_autopilot.py --no-ai         # AI を使わない (従来の run_weekly と同等)
    python3 scripts/run_autopilot.py --weekly-review # 最後に Fable による週次レビューを生成
    python3 scripts/run_autopilot.py --test          # モックデータで通し確認 (ネット不要)
    python3 scripts/run_autopilot.py --dry-run       # 実行せずコマンドだけ表示

実行される工程:
    ① baseblu セール商品の取得            (baseblu_sales_to_csv.py)   ネット必要
    ② 利益フィルタ 1 回目                 (filter_baseblu_profitable.py)
    ③ BUYMA 相場の取得                    (fetch_buyma_market_prices.py) ネット必要・時間がかかる
    ④ 利益フィルタ 2 回目 (相場連動)      (filter_baseblu_profitable.py --market …)
    ⑤ AI 補強: 出品文/カテゴリ/審査       (ai_enrich_candidates.py)    API キー必要 (無ければ自動スキップ)
    ⑥ 下書き作成 (--draft N 指定時)      (buyma_auto_listing.py --draft --limit N --yes)
    ⑦ 週次レビュー (--weekly-review 時)   (Fable 5.1 に集計値だけ渡す)
    ⑧ AI 費用レポート                     (ai_cost_report.py)

途中で失敗した工程はコマンドとエラーが表示されます。
    python3 scripts/ai_diagnose.py --log <ログ>   で AI 診断できます (API キーがあれば)。
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
REPORTS = PROJECT_ROOT / "outputs" / "reports"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --test 用のモック仕入れデータ (baseblu_sales_to_csv.py の出力と同じ列)
MOCK_SALES_ROWS = [
    {"title": "GG Marmont small matelasse shoulder bag", "vendor": "GUCCI", "product_type": "BAGS",
     "sku": "443497_DTDIT_1000", "color": "Black", "sizes": "UNI", "available_sizes": "UNI", "season": "AW25",
     "sale_price": "1290", "original_price": "1980", "discount_rate": "35", "available": "true",
     "description_en": "Small shoulder bag in matelasse chevron leather with Double G hardware. Made in Italy.",
     "image_url": "https://cdn.shopify.com/mock/gucci-marmont.jpg", "sub_images": "",
     "product_url": "https://www.baseblu.com/en-us/products/mock-gucci-marmont"},
    {"title": "Re-Nylon padded jacket", "vendor": "PRADA", "product_type": "CLOTHING",
     "sku": "SGB456_1WQ8_F0002", "color": "Navy", "sizes": "46, 48, 50, 52", "available_sizes": "48, 50", "season": "AW25",
     "sale_price": "980", "original_price": "1650", "discount_rate": "41", "available": "true",
     "description_en": "Padded jacket in regenerated nylon with enamel triangle logo. Zip closure. Made in Italy.",
     "image_url": "https://cdn.shopify.com/mock/prada-jacket.jpg", "sub_images": "",
     "product_url": "https://www.baseblu.com/en-us/products/mock-prada-jacket"},
    {"title": "Intrecciato leather card case", "vendor": "BOTTEGA VENETA", "product_type": "ACCESSORIES",
     "sku": "635057VCPQ4", "color": "Parakeet", "sizes": "UNI", "available_sizes": "UNI", "season": "SS25",
     "sale_price": "310", "original_price": "420", "discount_rate": "26", "available": "true",
     "description_en": "Card case in intrecciato lambskin. Four card slots. Made in Italy.",
     "image_url": "https://cdn.shopify.com/mock/bv-card.jpg", "sub_images": "",
     "product_url": "https://www.baseblu.com/en-us/products/mock-bv-card"},
    {"title": "Wool blend midi skirt", "vendor": "JIL SANDER", "product_type": "CLOTHING",
     "sku": "J02MA0089", "color": "Camel", "sizes": "36, 38, 40", "available_sizes": "", "season": "AW24",
     "sale_price": "420", "original_price": "790", "discount_rate": "47", "available": "false",
     "description_en": "Midi skirt in wool blend. Sold out sample row.",
     "image_url": "https://cdn.shopify.com/mock/js-skirt.jpg", "sub_images": "",
     "product_url": "https://www.baseblu.com/en-us/products/mock-js-skirt"},
    {"title": "Python leather ankle boots", "vendor": "SAINT LAURENT", "product_type": "FOOTWEAR",
     "sku": "7654321PY", "color": "Natural", "sizes": "36, 37, 38, 39", "available_sizes": "37, 38", "season": "AW25",
     "sale_price": "890", "original_price": "1590", "discount_rate": "44", "available": "true",
     "description_en": "Ankle boots in natural python skin (CITES). Leather sole. Made in Italy.",
     "image_url": "https://cdn.shopify.com/mock/ysl-boots.jpg", "sub_images": "",
     "product_url": "https://www.baseblu.com/en-us/products/mock-ysl-boots"},
]


def _latest(pattern: str) -> str | None:
    files = sorted(glob.glob(str(REPORTS / pattern)))
    return files[-1] if files else None


def write_mock_sales_csv(path: Path | None = None, source: str = "baseblu") -> Path:
    """--test 用: 仕入れスクリプトの出力形式でモック CSV を書く。"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = path or (REPORTS / f"{date_str}_{source}_sales_products_sorted.csv")
    fieldnames = [
        "title", "vendor", "product_type", "sku", "color", "sizes", "available_sizes", "season",
        "sale_price", "original_price", "discount_rate", "available",
        "description_en", "image_url", "sub_images", "product_url",
        "source_name", "currency", "landed_cost_basis",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in MOCK_SALES_ROWS:
            row = dict(r)
            row.setdefault("source_name", source)
            row.setdefault("currency", "EUR")
            row.setdefault("landed_cost_basis", "DDU")
            w.writerow(row)
    return path


def build_steps(args) -> list[dict]:
    """実行工程のリスト (純粋関数、テスト可能)。

    各 step: {"name", "cmd" (list[str] | None), "required", "resolver"?, "note"?}
    """
    py = sys.executable or "python3"
    source = (getattr(args, "source", "") or "baseblu").strip().lower()
    steps: list[dict] = []

    if args.test:
        steps.append({"name": "⓪ モック仕入れ CSV の生成 (--test)", "cmd": None,
                      "resolver": "write_mock", "required": True, "source": source})
    elif not args.skip_scrape:
        # baseblu は商品ページ HTML からの色抽出があるため専用スクリプトを使う。
        # 他の仕入先は data/sources.json 設定ベースの汎用スクリプト。
        if source == "baseblu":
            scrape_cmd = [py, str(SCRIPTS / "baseblu_sales_to_csv.py")]
        else:
            scrape_cmd = [py, str(SCRIPTS / "shopify_sales_to_csv.py"), "--source", source]
        steps.append({"name": f"① {source} セール商品の取得", "required": True, "cmd": scrape_cmd})

    steps.append({"name": "② 利益フィルタ (1回目・相場なし)", "required": True,
                  "cmd": [py, str(SCRIPTS / "filter_baseblu_profitable.py"), "--source", source]})

    if not args.skip_market and not args.test:
        market_cmd = [py, str(SCRIPTS / "fetch_buyma_market_prices.py"), "--csv", "latest"]
        if args.market_limit:
            market_cmd += ["--limit", str(args.market_limit)]
        steps.append({"name": "③ BUYMA 相場の取得 (時間がかかります)", "cmd": market_cmd, "required": True})
        steps.append({"name": "④ 利益フィルタ (2回目・相場連動)", "cmd": None,
                      "resolver": "filter_with_market", "required": True, "source": source})

    if not args.no_ai:
        enrich_cmd = [py, str(SCRIPTS / "ai_enrich_candidates.py"), "--limit", str(args.ai_limit)]
        steps.append({"name": f"⑤ AI 補強 (出品文/カテゴリ/審査・上位 {args.ai_limit} 件)",
                      "cmd": enrich_cmd, "required": False,
                      "note": "ANTHROPIC_API_KEY 未設定なら自動で従来ロジックにフォールバックします"})

    if args.draft and not args.test:
        steps.append({"name": f"⑥ BUYMA 下書き作成 (上位 {args.draft} 件)", "required": False,
                      "cmd": [py, str(SCRIPTS / "buyma_auto_listing.py"), "--draft",
                              "--limit", str(args.draft), "--yes"],
                      "note": "ブラウザが開きます。公開は管理画面で人が行います (下書き=ツール / 公開=人間)"})

    if args.weekly_review:
        steps.append({"name": "⑦ 週次レビュー (Fable 5.1・集計値のみ)", "cmd": None,
                      "resolver": "weekly_review", "required": False})

    if not args.no_ai:
        steps.append({"name": "⑧ AI 費用レポート", "required": False,
                      "cmd": [py, str(SCRIPTS / "ai_cost_report.py")]})
    return steps


def resolve_dynamic_cmd(step: dict) -> list[str] | None:
    py = sys.executable or "python3"
    if step.get("resolver") == "filter_with_market":
        market_json = _latest("*_market_prices.json")
        if not market_json:
            print("   ⚠️ 相場 JSON が見つからないためスキップします")
            return None
        return [py, str(SCRIPTS / "filter_baseblu_profitable.py"),
                "--source", step.get("source", "baseblu"), "--market", market_json]
    return None


def summarize_pipeline() -> dict:
    """週次レビューに渡す集計値 (生データは渡さない)。"""
    out: dict = {}
    sales = _latest("*_sales_products_sorted.csv")
    prof = _latest("*_profitable_products.csv")
    if sales:
        with open(sales, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        out["sourced_total"] = len(rows)
        out["sourced_available"] = sum(1 for r in rows if (r.get("available") or "").lower() in ("true", "1", "yes"))
    if prof:
        with open(prof, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        listable = [r for r in rows if (r.get("action") or "list") == "list"]
        out["listable"] = len(listable)

        def _median(key):
            vals = []
            for r in listable:
                try:
                    vals.append(float(r.get(key) or 0))
                except ValueError:
                    pass
            vals = sorted(v for v in vals if v > 0)
            return int(vals[len(vals) // 2]) if vals else None
        out["median_final_price_jpy"] = _median("final_price_jpy") or _median("selling_price_jpy")
        out["median_expected_profit_jpy"] = _median("expected_profit_jpy") or _median("profit_jpy")
        levels: dict[str, int] = {}
        verdicts: dict[str, int] = {}
        for r in listable:
            levels[r.get("competition_level") or "unknown"] = levels.get(r.get("competition_level") or "unknown", 0) + 1
            v = r.get("ai_verdict") or ""
            if v:
                verdicts[v] = verdicts.get(v, 0) + 1
        out["competition_levels"] = levels
        if verdicts:
            out["ai_verdicts"] = verdicts
        brands: dict[str, int] = {}
        for r in listable:
            b = r.get("vendor") or "?"
            brands[b] = brands.get(b, 0) + 1
        out["top_brands"] = dict(sorted(brands.items(), key=lambda kv: -kv[1])[:8])
    results = _latest("*_auto_listing_results.csv")
    if results:
        with open(results, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        stat: dict[str, int] = {}
        for r in rows:
            stat[r.get("status") or "?"] = stat.get(r.get("status") or "?", 0) + 1
        out["last_listing_run"] = stat
    return out


def run_weekly_review() -> bool:
    from app.ai.client import get_ai_client
    from app.ai.tasks.review import build_review_payload, weekly_review

    client = get_ai_client()
    if not client.available:
        print(f"   ℹ️ AI はオフ ({client.why_unavailable()}) → レビューをスキップ")
        return True
    funnel = None
    funnel_path = PROJECT_ROOT / "data" / "funnel_history.json"
    if funnel_path.exists():
        try:
            data = json.loads(funnel_path.read_text(encoding="utf-8"))
            funnel = data[-1] if isinstance(data, list) and data else data
        except Exception:
            funnel = None
    payload = build_review_payload(
        pipeline=summarize_pipeline(), funnel=funnel,
        ai_usage=client.ledger.summarize(7),
    )
    memo = weekly_review(payload, client)
    if not memo:
        print("   ⚠️ レビューを取得できませんでした")
        return False
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{datetime.now():%Y-%m-%d}_ai_weekly_review.md"
    out.write_text(f"# AI 週次レビュー ({datetime.now():%Y-%m-%d})\n\n{memo}\n\n---\n入力集計値:\n```json\n"
                   + json.dumps(payload, ensure_ascii=False, indent=1) + "\n```\n", encoding="utf-8")
    print(memo)
    print(f"   📄 保存: {out}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="仕入れ〜下書きまでの自動パイプライン")
    parser.add_argument("--source", default="baseblu",
                        help="仕入先 (既定 baseblu)。data/sources.json のキー名。"
                             "一覧: python3 scripts/shopify_sales_to_csv.py --list")
    parser.add_argument("--skip-scrape", action="store_true", help="セール CSV の再取得を飛ばす")
    parser.add_argument("--skip-market", action="store_true", help="相場取得を飛ばす")
    parser.add_argument("--market-limit", type=int, help="相場取得の件数上限")
    parser.add_argument("--ai-limit", type=int, default=30, help="AI に送る上位件数 (デフォルト 30)")
    parser.add_argument("--no-ai", action="store_true", help="AI 補強を使わない")
    parser.add_argument("--draft", type=int, default=0, metavar="N", help="上位 N 件を BUYMA に下書き保存")
    parser.add_argument("--weekly-review", action="store_true", help="Fable による週次レビューを生成")
    parser.add_argument("--test", action="store_true", help="モックデータで通し確認 (ネット不要)")
    parser.add_argument("--dry-run", action="store_true", help="実行せずコマンドだけ表示")
    args = parser.parse_args(argv)

    steps = build_steps(args)
    print("=" * 60)
    print(f"🤖 AI オートパイロット ({datetime.now():%Y-%m-%d %H:%M}){' [TEST]' if args.test else ''}")
    print("=" * 60)
    print("実行予定:")
    for s in steps:
        print(f"   {s['name']}")
    print()

    failed: list[str] = []
    for step in steps:
        print("─" * 60)
        print(f"▶ {step['name']}")
        if step.get("note"):
            print(f"   ℹ️ {step['note']}")
        resolver = step.get("resolver")
        if resolver == "write_mock":
            if args.dry_run:
                print("   $ (モック CSV を outputs/reports に生成)")
                continue
            path = write_mock_sales_csv(source=step.get("source", "baseblu"))
            print(f"   📄 {path}")
            continue
        if resolver == "weekly_review":
            if args.dry_run:
                print("   $ (集計値を Fable 5.1 に渡して週次レビューを生成)")
                continue
            if not run_weekly_review():
                failed.append(step["name"])
            continue
        if step["cmd"] is None and args.dry_run:
            print("   $ (実行時に最新の market JSON を自動指定して filter を再実行)")
            continue
        cmd = step["cmd"] or resolve_dynamic_cmd(step)
        if cmd is None:
            continue
        print(f"   $ {' '.join(cmd)}")
        if args.dry_run:
            continue
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            failed.append(step["name"])
            print()
            print(f"❌ 失敗: {step['name']} (exit code {result.returncode})")
            print("   ↑ このエラーを `python3 scripts/ai_diagnose.py --log <ログ>` で診断するか、Claude に貼り付けてください。")
            if step["required"]:
                print("   必須工程のため、ここで中断します。")
                return 1
            print("   任意工程のため、続行します。")

    if args.dry_run:
        print("\n(dry-run のため何も実行していません)")
        return 0

    print()
    print("=" * 60)
    print(f"⚠️ 完了 (失敗した任意工程: {', '.join(failed)})" if failed else "✅ 全工程完了！")
    final_csv = _latest("*_profitable_products.csv")
    if final_csv:
        print(f"📄 出品候補 CSV (期待値順・AI 列付き): {final_csv}")
    if not args.draft:
        print("次のステップ (下書きテスト):")
        print("   python3 scripts/run_autopilot.py --skip-scrape --skip-market --draft 1")
        print("   または python3 scripts/buyma_auto_listing.py --draft --limit 1 --hold")
    else:
        print("次のステップ: BUYMA 管理画面 (下書き一覧) で内容を確認し、公開ボタンを押してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
