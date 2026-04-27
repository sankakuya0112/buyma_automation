"""
audit_market_cache.py
---------------------
data/market_cache/*.json を走査し、相場ガード品質の観点から統計を出す。

実行例:
    python3 scripts/audit_market_cache.py                      # 統計 + 疑わしいエントリ一覧
    python3 scripts/audit_market_cache.py --suspicious-only    # 疑わしいエントリのみ
    python3 scripts/audit_market_cache.py --re-evaluate        # raw_items を再計算して JSON 更新
    python3 scripts/audit_market_cache.py --threshold 0.5      # 信頼度の閾値変更

Phase 2c で `brand_match_confidence` フィールドを導入したため、旧キャッシュ
(フィールドなし) の品質を机上で検証する。raw_items が含まれるエントリは
新ロジックで再計算可能。

疑わしい判定基準:
  - brand_match_confidence < threshold (default 0.5)
  - excluded_count_default_price >= 2
  - default_price_warnings に ¥25,980 帯の値が含まれる
  - フィールド未存在 (legacy cache)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "data" / "market_cache"

# BUYMA がデフォルト商品リストに混ぜがちな価格帯 (実測ベース)
SUSPICIOUS_PRICE_BANDS = [
    (25000, 27000),
    (29000, 31000),
]


def is_suspicious_price(price: int) -> bool:
    return any(lo <= price <= hi for lo, hi in SUSPICIOUS_PRICE_BANDS)


def classify_entry(entry: dict, threshold: float) -> tuple[str, list[str]]:
    """エントリの品質を分類する。

    Returns:
        (status, reasons) — status は "ok" / "suspicious" / "legacy" / "empty"
    """
    reasons: list[str] = []

    sample_count = entry.get("sample_count", 0)
    if sample_count == 0:
        return "empty", ["sample_count=0"]

    if "brand_match_confidence" not in entry:
        reasons.append("legacy_no_confidence_field")
        return "legacy", reasons

    confidence = entry.get("brand_match_confidence", 1.0)
    if confidence < threshold:
        reasons.append(f"low_confidence={confidence:.2f}")

    excluded_default = entry.get("excluded_count_default_price", 0)
    if excluded_default >= 2:
        reasons.append(f"default_price_excluded={excluded_default}")

    warnings = entry.get("default_price_warnings", [])
    suspicious_warnings = [p for p in warnings if is_suspicious_price(p)]
    if suspicious_warnings:
        reasons.append(f"suspicious_default_prices={suspicious_warnings}")

    median = entry.get("median_jpy")
    if median is not None and is_suspicious_price(median):
        reasons.append(f"median_in_suspicious_band={median}")

    if reasons:
        return "suspicious", reasons
    return "ok", []


def re_evaluate(entry: dict) -> dict | None:
    """raw_items が含まれていれば compute_stats を再適用して新統計を返す。"""
    raw_items = entry.get("raw_items")
    if not raw_items:
        return None
    from fetch_buyma_market_prices import compute_stats

    brand = entry.get("brand", "")
    new_stats = compute_stats(raw_items, query_brand=brand)
    updated = {
        **entry,
        **new_stats,
    }
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="market_cache の audit + 再評価")
    parser.add_argument(
        "--cache-dir", default=str(CACHE_DIR),
        help="キャッシュディレクトリ (default: data/market_cache)",
    )
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="brand_match_confidence の許容閾値 (default 0.5)")
    parser.add_argument("--suspicious-only", action="store_true",
                        help="疑わしいエントリのみ詳細表示")
    parser.add_argument("--re-evaluate", action="store_true",
                        help="raw_items を含むエントリを compute_stats で再計算し JSON 更新")
    parser.add_argument("--dry-run", action="store_true",
                        help="--re-evaluate と併用時、ファイルを書き換えず差分のみ表示")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    if not cache_dir.exists():
        print(f"❌ キャッシュディレクトリが存在しません: {cache_dir}")
        return 1

    files = sorted(cache_dir.glob("*.json"))
    if not files:
        print(f"⚠️  キャッシュ JSON が見つかりません: {cache_dir}")
        return 0

    counter: Counter[str] = Counter()
    suspicious_entries: list[tuple[Path, dict, list[str]]] = []
    legacy_entries: list[Path] = []
    re_evaluated_count = 0
    re_evaluated_changed = 0

    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                entry = json.load(f)
        except Exception as e:
            print(f"⚠️  読み込み失敗 {fp.name}: {e}")
            counter["read_error"] += 1
            continue

        status, reasons = classify_entry(entry, args.threshold)
        counter[status] += 1

        if status == "suspicious":
            suspicious_entries.append((fp, entry, reasons))
        if status == "legacy":
            legacy_entries.append(fp)

        if args.re_evaluate:
            updated = re_evaluate(entry)
            if updated is None:
                continue
            re_evaluated_count += 1
            old_median = entry.get("median_jpy")
            new_median = updated.get("median_jpy")
            old_n = entry.get("sample_count")
            new_n = updated.get("sample_count")
            if old_median != new_median or old_n != new_n:
                re_evaluated_changed += 1
                print(
                    f"  [DIFF] {fp.name}: median {old_median}->{new_median}, "
                    f"sample {old_n}->{new_n}"
                )
            if not args.dry_run:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(updated, f, ensure_ascii=False, indent=2)

    print("\n========== Audit Result ==========")
    print(f"  総エントリ数        : {len(files)}")
    print(f"  ok                  : {counter['ok']}")
    print(f"  suspicious          : {counter['suspicious']}")
    print(f"  legacy (旧スキーマ) : {counter['legacy']}")
    print(f"  empty (sample=0)    : {counter['empty']}")
    if counter["read_error"]:
        print(f"  読込エラー          : {counter['read_error']}")

    if args.re_evaluate:
        print(f"\n========== Re-evaluation ==========")
        print(f"  raw_items あり      : {re_evaluated_count}")
        print(f"  median/sample 変動  : {re_evaluated_changed}")
        if args.dry_run:
            print(f"  (--dry-run のため JSON は更新していません)")

    if suspicious_entries and not args.suspicious_only:
        print(f"\n========== Suspicious Entries ==========")
    if args.suspicious_only or suspicious_entries:
        for fp, entry, reasons in suspicious_entries[:50]:
            brand = entry.get("brand", "?")
            keyword = entry.get("keyword", "?")
            n = entry.get("sample_count", 0)
            median = entry.get("median_jpy", "-")
            print(f"  • {fp.name}")
            print(f"      brand={brand} keyword={keyword!r} median={median} n={n}")
            print(f"      reasons: {', '.join(reasons)}")
        if len(suspicious_entries) > 50:
            print(f"  ... 残り {len(suspicious_entries) - 50} 件")

    if legacy_entries and not args.suspicious_only:
        print(f"\n========== Legacy Entries (要再 fetch) ==========")
        print(f"  brand_match_confidence フィールドなし: {len(legacy_entries)} 件")
        for fp in legacy_entries[:10]:
            print(f"  • {fp.name}")
        if len(legacy_entries) > 10:
            print(f"  ... 残り {len(legacy_entries) - 10} 件")
        print("  → これらは Mac で再 fetch (キャッシュ無視) が必要")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
