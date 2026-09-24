"""
ai_enrich_candidates.py — 利益フィルタ済み CSV の上位 N 件だけを AI で補強する
--------------------------------------------------------------------------
入力: outputs/reports/*_profitable_products.csv (filter_baseblu_profitable.py の出力)
出力: 同じ CSV に ai_* 列を追加して上書き (--output で別ファイルも可)

追加される列:
    category_path / category_source   … 3 階層カテゴリ (keyword | ai | type_default | global_default)
    ai_title_ja / ai_description_ja   … 日本語タイトル・説明文 (Haiku 4.5)
    ai_keywords / ai_color_ja         … 検索キーワード ("|" 区切り) / 系統色
    ai_verdict / ai_risk_flags / ai_reason / ai_priority
                                       … 審査結果 list|hold|skip (Sonnet 5)
    ai_enriched_at / ai_models

トークン節約の仕組み:
    - 決定論フィルタ (action=list) を通過し opportunity_score 上位 N 件だけを送る (--limit)
    - カテゴリはキーワード辞書で決まらなかった商品だけ AI に番号で選ばせる
    - 同じ入力は data/ai_cache.sqlite から返す (再実行はほぼ無料)
    - ANTHROPIC_API_KEY 未設定・予算超過なら AI をスキップして従来の辞書翻訳に任せる

使い方 (Mac):
    python3 scripts/ai_enrich_candidates.py                # 最新 CSV の上位 30 件
    python3 scripts/ai_enrich_candidates.py --limit 10     # 上位 10 件
    python3 scripts/ai_enrich_candidates.py --dry-run      # 送信内容とトークン概算だけ表示
    python3 scripts/ai_enrich_candidates.py --no-judge     # 審査を省略 (出品文とカテゴリのみ)
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # pragma: no cover
    pass

from app.ai.client import get_ai_client, rough_token_count  # noqa: E402
from app.ai.router import policy_for, resolve_model, price_table  # noqa: E402
from app.ai.tasks import category as category_task  # noqa: E402
from app.ai.tasks import judge as judge_task  # noqa: E402
from app.ai.tasks import listing_copy as copy_task  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports"
CATEGORIES_PATH = PROJECT_ROOT / "data" / "categories.json"

AI_COLUMNS = [
    "category_path", "category_source",
    "ai_title_ja", "ai_description_ja", "ai_keywords", "ai_color_ja",
    "ai_verdict", "ai_risk_flags", "ai_reason", "ai_priority",
    "ai_enriched_at", "ai_models",
]


def latest_profitable_csv() -> str | None:
    files = sorted(glob.glob(str(OUTPUT_DIR / "*_profitable_products.csv")), reverse=True)
    return files[0] if files else None


def load_rows(path: str) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def select_candidates(rows: list[dict], limit: int) -> list[int]:
    """AI に送る行のインデックス。action=list (または未設定) を期待値順に上位 limit 件。"""
    indexed = []
    for i, r in enumerate(rows):
        action = (r.get("action") or "list").strip().lower()
        if action != "list":
            continue
        try:
            score = float(r.get("opportunity_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            profit = float(r.get("expected_profit_jpy") or r.get("profit_jpy") or 0)
        except (TypeError, ValueError):
            profit = 0.0
        indexed.append((-score, -profit, i))
    indexed.sort()
    return [i for _, _, i in indexed[:limit]]


def row_id(row: dict, idx: int) -> str:
    sku = (row.get("sku") or "").strip()
    return f"{sku}#{idx}" if sku else f"row{idx}"


def enrich(rows: list[dict], cand_idx: list[int], client, cat_data: dict, *,
           do_copy=True, do_category=True, do_judge=True) -> dict:
    """rows を in-place で補強し、統計を返す。"""
    stats = {"candidates": len(cand_idx), "copy": 0, "category_ai": 0, "category_keyword": 0,
             "judge": 0, "verdict": {"list": 0, "hold": 0, "skip": 0}}
    if not cand_idx:
        return stats
    products = [rows[i] for i in cand_idx]
    ids = [row_id(rows[i], i) for i in cand_idx]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    models = []

    # 1. カテゴリ: 決定論 → 未決のものだけ AI
    ai_cat: dict[str, dict] = {}
    if do_category:
        undecided, undecided_ids = [], []
        for p, pid in zip(products, ids):
            _, source = category_task.keyword_category_path(p.get("title", ""), p.get("product_type", ""), cat_data)
            if source == "keyword":
                stats["category_keyword"] += 1
            else:
                undecided.append(p)
                undecided_ids.append(pid)
        if undecided:
            ai_cat = category_task.classify_categories(undecided, client, cat_data, ids=undecided_ids)
            if ai_cat:
                models.append(f"category={resolve_model(policy_for('category').tier)}")
        for p, pid in zip(products, ids):
            path, source = category_task.resolve_category(p, cat_data, ai_cat.get(pid))
            p["category_path"] = " > ".join(path)
            p["category_source"] = source
            if source == "ai":
                stats["category_ai"] += 1

    # 2. 出品文
    if do_copy:
        copies = copy_task.generate_listing_copy(products, client, ids=ids)
        if copies:
            models.append(f"copy={resolve_model(policy_for('listing_copy').tier)}")
        for p, pid in zip(products, ids):
            c = copies.get(pid)
            if not c:
                continue
            p["ai_title_ja"] = c["title_ja"]
            p["ai_description_ja"] = c["description_ja"]
            p["ai_keywords"] = "|".join(c["keywords"])
            p["ai_color_ja"] = c["color_ja"]
            stats["copy"] += 1

    # 3. 審査
    if do_judge:
        verdicts = judge_task.judge_candidates(products, client, ids=ids)
        if verdicts:
            models.append(f"judge={resolve_model(policy_for('judge').tier)}")
        for p, pid in zip(products, ids):
            v = verdicts.get(pid)
            if not v:
                continue
            p["ai_verdict"] = v["verdict"]
            p["ai_risk_flags"] = "|".join(v["risk_flags"])
            p["ai_reason"] = v["reason"]
            p["ai_priority"] = str(v["priority"])
            stats["judge"] += 1
            stats["verdict"][v["verdict"]] += 1

    for p in products:
        p["ai_enriched_at"] = now
        p["ai_models"] = ";".join(models)
    return stats


def write_rows(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    out_fields = list(fieldnames)
    for c in AI_COLUMNS:
        if c not in out_fields:
            out_fields.append(c)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in out_fields})
    os.replace(tmp, path)


def dry_run_report(rows: list[dict], cand_idx: list[int], cat_data: dict) -> dict:
    """送信予定の概算トークンと概算費用 (課金なし)。"""
    products = [rows[i] for i in cand_idx]
    ids = [row_id(rows[i], i) for i in cand_idx]
    report = {}
    undecided = [p for p in products
                 if category_task.keyword_category_path(p.get("title", ""), p.get("product_type", ""), cat_data)[1] != "keyword"]
    plans = [
        ("category", category_task.build_system_prompt(category_task.allowed_paths(cat_data)),
         [json.dumps(category_task._compact(p, pid), ensure_ascii=False) for p, pid in zip(undecided, ids)]),
        ("listing_copy", copy_task.SYSTEM_PROMPT,
         [json.dumps(copy_task.compact_product(p, pid), ensure_ascii=False) for p, pid in zip(products, ids)]),
        ("judge", judge_task.SYSTEM_PROMPT,
         [json.dumps(judge_task.compact_candidate(p, pid), ensure_ascii=False) for p, pid in zip(products, ids)]),
    ]
    out_per_item = {"category": 25, "listing_copy": 450, "judge": 90}
    for task, system, items in plans:
        if not items:
            report[task] = {"items": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
            continue
        pol = policy_for(task)
        model = resolve_model(pol.tier)
        calls = (len(items) + pol.items_per_call - 1) // pol.items_per_call
        in_tokens = calls * rough_token_count(system) + sum(rough_token_count(s) for s in items)
        out_tokens = out_per_item[task] * len(items)
        p_in, p_out, _, _ = price_table(model)
        usd = (in_tokens * p_in + out_tokens * p_out) / 1_000_000
        report[task] = {"items": len(items), "calls": calls, "model": model,
                        "input_tokens": in_tokens, "output_tokens": out_tokens, "usd": round(usd, 4)}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="利益フィルタ済み CSV を AI で補強する")
    parser.add_argument("--input", help="入力 CSV (省略時は最新の *_profitable_products.csv)")
    parser.add_argument("--output", help="出力 CSV (省略時は入力を上書き)")
    parser.add_argument("--limit", type=int, default=30, help="AI に送る上位件数 (デフォルト 30)")
    parser.add_argument("--no-copy", action="store_true", help="出品文生成を省略")
    parser.add_argument("--no-category", action="store_true", help="カテゴリ分類を省略")
    parser.add_argument("--no-judge", action="store_true", help="審査を省略")
    parser.add_argument("--dry-run", action="store_true", help="送信せずトークン概算だけ表示")
    args = parser.parse_args(argv)

    input_path = args.input or latest_profitable_csv()
    if not input_path or not os.path.exists(input_path):
        print("❌ 入力 CSV が見つかりません。先に filter_baseblu_profitable.py を実行してください。")
        return 1
    rows, fieldnames = load_rows(input_path)
    cat_data = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    cand_idx = select_candidates(rows, args.limit)
    print(f"📂 入力: {os.path.basename(input_path)} ({len(rows)} 行) → AI 対象 {len(cand_idx)} 件 (上位 {args.limit})")

    if args.dry_run:
        rep = dry_run_report(rows, cand_idx, cat_data)
        total = 0.0
        for task, r in rep.items():
            total += r.get("usd", 0.0)
            print(f"   {task:13s} 商品 {r['items']:3d} 件 / {r['calls']} 回 / "
                  f"入力≈{r['input_tokens']:,} tok 出力≈{r['output_tokens']:,} tok / ≈${r['usd']:.4f} ({r.get('model', '-')})")
        from app.ai.router import usd_to_jpy
        print(f"   合計概算: ≈${total:.4f} (≈¥{usd_to_jpy(total):,.0f})  ※キャッシュ命中分は 0 円")
        print("(dry-run のため送信していません)")
        return 0

    client = get_ai_client()
    if not client.available:
        print(f"ℹ️ AI はオフ ({client.why_unavailable()}) → 従来の辞書翻訳・キーワード分類で続行します")
    stats = enrich(rows, cand_idx, client, cat_data,
                   do_copy=not args.no_copy, do_category=not args.no_category, do_judge=not args.no_judge)

    output_path = args.output or input_path
    write_rows(output_path, rows, fieldnames)

    s = client.session_summary()
    print("✅ AI 補強完了")
    print(f"   カテゴリ: 辞書 {stats['category_keyword']} 件 / AI {stats['category_ai']} 件")
    print(f"   出品文  : {stats['copy']} 件")
    v = stats["verdict"]
    print(f"   審査    : {stats['judge']} 件 (list {v['list']} / hold {v['hold']} / skip {v['skip']})")
    print(f"   API 呼出: {s['calls']} 回 / キャッシュ命中 {s['cache_hits']} 回 / 今回 ≈¥{s['cost_jpy']:,.1f} "
          f"/ 今週累計 ¥{s['weekly_spent_jpy']:,.1f} (予算 ¥{s['weekly_budget_jpy']:,.0f})")
    print(f"   保存先  : {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
