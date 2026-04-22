"""
fetch_buyma_market_prices.py
-----------------------------
BUYMA 商品検索を Playwright でスクレイプし、同ブランド・同類商品の出品価格分布
(中央値・最小・最大・件数) を JSON で保存する。

Phase 2a Task 2: 価格決定ロジック (decide_final_price) に流し込む市場相場データ
の取得元。

使い方:
    # 単発取得 (デバッグ用)
    python3 scripts/fetch_buyma_market_prices.py --brand "Gucci" --keyword "marmont"

    # CSV 全件分を取得 (Mac で実行)
    python3 scripts/fetch_buyma_market_prices.py --csv outputs/reports/2026-04-22_baseblu_profitable_products.csv

    # 既存キャッシュを使い再取得しない (オフライン解析用)
    python3 scripts/fetch_buyma_market_prices.py --csv ... --no-fetch

キャッシュ:
    data/market_cache/{brand_slug}_{keyword_slug}.json (TTL 24h)
    再実行時は TTL 内ならネットワークアクセスをスキップ。

注意:
    - スクレイパーは BUYMA 検索結果ページの HTML 構造に依存。
      class 名は試行錯誤で調整が必要。
    - Mac 上での実行を前提 (サーバから BUYMA に接続不可)
    - 連続取得時はリクエスト間隔 1.5-3 秒 (rate-limit 回避)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "data" / "market_cache"
CACHE_TTL_HOURS = 24
SEARCH_URL_BASE = "https://www.buyma.com/r/"
REQUEST_DELAY_RANGE = (1.5, 3.0)


def _slug(text: str) -> str:
    """キャッシュキー用の安全な文字列化。"""
    if not text:
        return "_empty"
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = text.strip("_").lower()
    return text[:60] or "_"


def _cache_path(brand: str, keyword: str) -> Path:
    h = hashlib.sha1(f"{brand}|{keyword}".encode("utf-8")).hexdigest()[:8]
    return CACHE_DIR / f"{_slug(brand)}_{_slug(keyword)}_{h}.json"


def _is_cache_fresh(path: Path, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=ttl_hours)


def load_cached(brand: str, keyword: str) -> Optional[dict]:
    path = _cache_path(brand, keyword)
    if not _is_cache_fresh(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(brand: str, keyword: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(brand, keyword)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_search_url(brand: str, keyword: str) -> str:
    """BUYMA 商品検索 URL を構築する。

    確認済み実 URL 形式 (2026-04): `https://www.buyma.com/r/{キーワード}/`
      - パス型 (クエリパラメータ無し)
      - 空白は %20 でエンコード
      - 末尾スラッシュ必須
    """
    from urllib.parse import quote
    query_text = f"{brand} {keyword}".strip()
    return SEARCH_URL_BASE + quote(query_text) + "/"


def extract_prices_from_html(html: str) -> list[int]:
    """検索結果 HTML から price (int 円) を抽出する。

    BUYMA の確認済み class 名 (2026-04 時点):
      - product_price / product_price_detail  ← 今の実売価 (採用)
      - Price_Txt                             ← 上と同じものを囲む子要素 (採用)
      - price_reference                       ← 取消線の旧価格 (除外)
      - coupon-price                          ← クーポン適用後の参考価格 (除外)
      - Price_Percent_detail                  ← 割引率 % (除外)

    アプローチ:
      1. 旧価格系 class (price_reference / coupon-price 等) の要素を HTML から削除
      2. product_price class を優先、次に Price_Txt の順で price を抽出
      3. 1 商品あたり 1 価格になるよう「最初に見つかった数値」のみ採用
      4. ブランド品の現実レンジ (¥15,000-5,000 万) で sanity check
    """
    # --- Step 1: 除外 class の要素を削除 ---
    exclude_pat = (
        r'<(?P<tag>[a-zA-Z0-9]+)[^>]*class="[^"]*'
        r'(?:price_reference|coupon-price|coupon_price|price_original|Price_Percent)'
        r'[^"]*"[^>]*>.{0,500}?</(?P=tag)>'
    )
    html_clean = re.sub(exclude_pat, ' ', html, flags=re.IGNORECASE | re.DOTALL)

    candidates: list[int] = []

    # --- Step 2: product_price を優先狙い撃ち ---
    # nested タグに対応するため lazy match で 500 文字まで許容
    primary_patterns = [
        r'<[^>]*class="[^"]*product_price[^"]*"[^>]*>(.{0,500}?)</',
        r'<[^>]*class="[^"]*Price_Txt[^"]*"[^>]*>(.{0,500}?)</',
    ]
    for pat in primary_patterns:
        matches = re.findall(pat, html_clean, flags=re.IGNORECASE | re.DOTALL)
        if not matches:
            continue
        for block in matches:
            # 1 要素あたり最初にヒットした妥当な値だけ採用
            for pm in re.findall(r"([0-9][0-9,]{3,})", block):
                try:
                    v = int(pm.replace(",", ""))
                except ValueError:
                    continue
                if 15000 <= v <= 50_000_000:
                    candidates.append(v)
                    break
        if candidates:
            return candidates

    # --- Step 3: data-price attribute ---
    for m in re.findall(r'data-price="([0-9]+)"', html_clean):
        try:
            v = int(m)
        except ValueError:
            continue
        if 15000 <= v <= 50_000_000:
            candidates.append(v)
    if candidates:
        return candidates

    # --- Step 4: フォールバック ¥表記全捕捉 ---
    raw: list[int] = []
    for m in re.findall(r"¥\s*([0-9][0-9,]+)", html_clean):
        try:
            v = int(m.replace(",", ""))
        except ValueError:
            continue
        if 15000 <= v <= 50_000_000:
            raw.append(v)
    return raw


def _remove_outliers(prices: list[int]) -> list[int]:
    """IQR 方式で外れ値除去 (サンプル 5 件以上の時のみ)。"""
    if len(prices) < 5:
        return prices
    sorted_p = sorted(prices)
    q1 = sorted_p[len(sorted_p) // 4]
    q3 = sorted_p[3 * len(sorted_p) // 4]
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return [p for p in prices if lo <= p <= hi]


def compute_stats(prices: list[int]) -> dict:
    """価格リストから統計を計算する (外れ値除去後)。"""
    if not prices:
        return {
            "sample_count": 0,
            "median_jpy": None,
            "min_jpy": None,
            "max_jpy": None,
            "raw_sample_count": 0,
        }
    raw_n = len(prices)
    cleaned = _remove_outliers(prices)
    if not cleaned:
        cleaned = prices
    return {
        "sample_count": len(cleaned),
        "median_jpy": int(statistics.median(cleaned)),
        "min_jpy": int(min(cleaned)),
        "max_jpy": int(max(cleaned)),
        "raw_sample_count": raw_n,
    }


def fetch_market_for(brand: str, keyword: str, page=None) -> dict:
    """BUYMA 検索を実行し市場統計を返す。

    Args:
        brand: ブランド名 (例 "Gucci")
        keyword: 商品名キーワード (例 "marmont")
        page: 既存の Playwright Page (省略時は新規作成)

    Returns:
        {
            "brand": ..., "keyword": ..., "fetched_at": ISO8601,
            "url": ..., "sample_count": N, "median_jpy": ..., ...
        }
    """
    url = build_search_url(brand, keyword)

    own_browser = False
    if page is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()
        own_browser = True

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(0.5)
        html = page.content()
    except Exception as e:
        print(f"  ⚠️ 取得失敗 brand={brand} keyword={keyword}: {e}")
        html = ""
    finally:
        if own_browser:
            try:
                browser.close()
                pw.stop()
            except Exception:
                pass

    prices = extract_prices_from_html(html)
    stats = compute_stats(prices)
    result = {
        "brand": brand,
        "keyword": keyword,
        "url": url,
        "fetched_at": datetime.now().isoformat(),
        **stats,
    }
    return result


def keyword_from_title(title: str) -> str:
    """タイトルから検索キーワードを抽出する (ストップワード除去 + 短縮)。"""
    if not title:
        return ""
    text = title.lower()
    # 記号/句読点を空白に
    text = re.sub(r"[\(\)\[\]\{\},.;:'\"!?/\\\-_]+", " ", text)
    # 一般的すぎる単語を除外
    stop = {"the", "a", "an", "with", "and", "of", "in", "for", "to"}
    words = [w for w in text.split() if w and w not in stop]
    # 最大 3 単語まで (検索結果を絞り込みすぎない)
    return " ".join(words[:3])


def keyword_from_sku(sku: str) -> str:
    """SKU (型番) を検索キーワードに整形する。

    baseblu の SKU は "R1P953_337" "MBGPD3611_C8279" のような形式。
    BUYMA の検索では _ / - が邪魔になることがあるので空白に置換する。
    """
    if not sku:
        return ""
    return re.sub(r"[_\-/]+", " ", sku).strip()


def fetch_market_with_fallback(
    brand: str,
    sku: str,
    title_keyword: str,
    page=None,
    min_samples: int = 3,
) -> dict:
    """SKU 検索 → タイトル検索 の順でフォールバック付き取得する。

    1. SKU があれば「ブランド + SKU」で検索
    2. サンプル < min_samples なら「ブランド + タイトルキーワード」で再検索
    3. どちらも失敗なら最後の結果を返す

    結果 dict には "source": "sku" | "title" | "merged" | "none" を付与。
    """
    results = []
    if sku:
        sku_kw = keyword_from_sku(sku)
        r = fetch_market_for(brand, sku_kw, page=page)
        r["source"] = "sku"
        r["search_sku"] = sku_kw
        results.append(r)
        if r.get("sample_count", 0) >= min_samples:
            return r

    if title_keyword:
        r2 = fetch_market_for(brand, title_keyword, page=page)
        r2["source"] = "title"
        r2["search_title"] = title_keyword
        results.append(r2)
        # SKU も title もあるなら、より多い方を採用
        if results and (r2.get("sample_count", 0) or 0) > (results[0].get("sample_count", 0) or 0):
            return r2

    if results:
        return results[0]
    return {"brand": brand, "source": "none", "sample_count": 0, "median_jpy": None}


def main():
    parser = argparse.ArgumentParser(description="BUYMA 市場価格スクレイパー")
    parser.add_argument("--brand", help="単発: ブランド名")
    parser.add_argument("--keyword", help="単発: 商品キーワード")
    parser.add_argument("--sku", help="単発: SKU (型番)。指定時は SKU 検索を優先、フォールバックで keyword")
    parser.add_argument("--csv", help="CSV 全件処理: profitable CSV のパス ('latest' で自動選択)")
    parser.add_argument("--no-fetch", action="store_true", help="ネット取得せずキャッシュのみ集計")
    parser.add_argument("--out", help="集計 JSON 出力先 (CSV モード時)")
    parser.add_argument("--limit", type=int, help="CSV モード時の処理件数上限")
    parser.add_argument("--debug-html", action="store_true",
                        help="取得した HTML を /tmp/buyma_market_debug.html に保存 (単発モード時)")
    args = parser.parse_args()

    # 単発モード (--brand 必須、--keyword or --sku のどちらか以上)
    if args.brand and (args.keyword or args.sku):
        # SKU + keyword 両方ある時は fetch_market_with_fallback で 2 段構え
        if args.sku and args.keyword and not args.debug_html:
            if args.no_fetch:
                print("⚠️ --no-fetch は単発 SKU+keyword モードでは未対応")
                return
            result = fetch_market_with_fallback(args.brand, args.sku, args.keyword)
            # 成功したら該当キーでキャッシュ保存
            if result.get("source") == "sku":
                save_cache(args.brand, keyword_from_sku(args.sku), result)
            elif result.get("source") == "title":
                save_cache(args.brand, args.keyword, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # 従来: keyword のみ (または SKU のみ)
        lookup_kw = keyword_from_sku(args.sku) if args.sku else args.keyword
        cached = load_cached(args.brand, lookup_kw)
        if cached and not args.debug_html:
            print(f"📦 キャッシュ使用 ({cached['fetched_at']})")
            print(json.dumps(cached, ensure_ascii=False, indent=2))
            return
        if args.no_fetch:
            print("⚠️ キャッシュなし、--no-fetch のため取得しません")
            return

        if args.debug_html:
            # 単発 + デバッグ: HTML を保存
            from playwright.sync_api import sync_playwright
            url = build_search_url(args.brand, args.keyword)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    locale="ja-JP",
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                time.sleep(0.5)
                html = page.content()
                debug_path = "/tmp/buyma_market_debug.html"
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"💾 HTML 保存: {debug_path} ({len(html):,} chars)")
                prices = extract_prices_from_html(html)
                stats = compute_stats(prices)
                print(f"抽出価格 (raw): {prices[:20]}{'...' if len(prices) > 20 else ''}")
                print(f"統計: {json.dumps(stats, ensure_ascii=False)}")
                browser.close()
            return

        result = fetch_market_for(args.brand, args.keyword)
        save_cache(args.brand, args.keyword, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # CSV モード
    if not args.csv:
        parser.error("--brand+--keyword または --csv のいずれかを指定してください")

    # "latest" または存在しないパス → 最新の profitable CSV を自動選択
    csv_path = args.csv
    if csv_path.lower() == "latest" or not os.path.exists(csv_path):
        pattern = str(PROJECT_ROOT / "outputs" / "reports" / "*_baseblu_profitable_products.csv")
        import glob as _g
        candidates = sorted(_g.glob(pattern))
        if not candidates:
            print(f"❌ CSV not found: {csv_path} & no auto-detect candidate")
            sys.exit(1)
        auto = candidates[-1]
        if csv_path.lower() != "latest":
            print(f"⚠️ 指定 CSV が見つかりません: {csv_path}")
        print(f"📂 最新の profitable CSV を自動選択: {auto}")
        csv_path = auto

    print(f"📂 CSV: {csv_path}")
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]
    print(f"   {len(rows)} 件処理")

    results = {}
    pw = None
    browser = None
    page = None
    if not args.no_fetch:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()

    import random
    try:
        for i, row in enumerate(rows, 1):
            brand = (row.get("vendor") or "").strip()
            sku = (row.get("sku") or "").strip()
            keyword = keyword_from_title(row.get("title") or "")
            # 2段階: まず SKU 検索用キャッシュを探し、なければ title 検索
            sku_kw = keyword_from_sku(sku)
            key = f"{brand}|{sku_kw or keyword}"
            if key in results:
                continue
            # 優先順位: SKU キャッシュ → title キャッシュ
            cached = None
            if sku_kw:
                cached = load_cached(brand, sku_kw)
            if not cached:
                cached = load_cached(brand, keyword)
            if cached:
                results[key] = cached
                used_kw = cached.get("search_sku") or cached.get("search_title") or cached.get("keyword", keyword)
                print(f"  [{i}/{len(rows)}] {brand[:25]} / {used_kw[:30]} → cache (n={cached['sample_count']})")
                continue
            if args.no_fetch:
                results[key] = {"brand": brand, "keyword": keyword, "sample_count": 0, "median_jpy": None}
                continue
            # 新規取得: SKU 検索 → title 検索 の順でフォールバック
            result = fetch_market_with_fallback(
                brand=brand, sku=sku, title_keyword=keyword, page=page,
            )
            source = result.get("source", "title")
            if source == "sku":
                save_cache(brand, sku_kw, result)
            elif source == "title":
                save_cache(brand, keyword, result)
            results[key] = result
            used_kw = result.get("search_sku") or result.get("search_title") or keyword
            print(
                f"  [{i}/{len(rows)}] {brand[:25]} / {used_kw[:30]} [{source}] → "
                f"n={result.get('sample_count', 0)} median=¥{result.get('median_jpy') or 0:,}"
            )
            time.sleep(random.uniform(*REQUEST_DELAY_RANGE))
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()

    out_path = args.out or os.path.join(
        PROJECT_ROOT, "outputs", "reports",
        f"{datetime.now().strftime('%Y-%m-%d')}_market_prices.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 保存: {out_path}")


if __name__ == "__main__":
    main()
