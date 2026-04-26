"""Farfetch JP の同等品ベンチマーク価格を取得する。

Phase 2b で導入。BUYMA 内で competition_level が none/low の商品 (= 独占
チャンスと判定された商品) は、外部 EC で同等品が安く出ていると即破綻する。
Farfetch JP は日本円表示で関税・輸入税込みのため、BUYMA 出品価格と直接比較
可能で、ベンチマーク基準としては最良。

Usage:
    python3 scripts/fetch_farfetch_benchmarks.py \\
        --csv outputs/reports/2026-04-26_baseblu_profitable_products.csv \\
        --output outputs/reports/2026-04-26_farfetch_benchmarks.json

挙動:
  - CSV を読み、decision_reason in (no_market_data, low_competition,
    fake_market) の商品だけ対象とする
  - 各商品について Farfetch JP の検索ページに遷移し、上位 5 件の
    タイトル + 価格 + URL を抽出
  - キャッシュ (24h) で重複 fetch を回避
  - レート制限 5 秒/req
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

# プロジェクトルート (このファイルの親) を sys.path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import Config  # noqa: E402
from app.core.external_benchmark import (  # noqa: E402
    ExternalBenchmark,
    load_benchmarks,
    make_product_key,
    save_benchmarks,
)

FARFETCH_SEARCH_URL = "https://www.farfetch.com/jp/shopping/search/items.aspx?q={query}"
TARGET_REASONS = {"no_market_data", "low_competition", "fake_market"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
RATE_LIMIT_SEC = (4.0, 6.0)
CACHE_TTL_SEC = 24 * 60 * 60


def build_query(vendor: str, title: str) -> str:
    """検索クエリを組み立てる。ブランド + タイトル先頭 5 語まで。"""
    keywords = re.findall(r"[A-Za-z0-9]+", title)[:5]
    parts = [vendor.strip(), *keywords]
    return " ".join(p for p in parts if p)


def parse_jpy(text: str) -> Optional[int]:
    """¥1,234,567 形式 / 1234567 円 形式 / 1,234.56 等を JPY int に変換。"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None
    try:
        # JSON-LD price は "1234.56" のような浮動小数も許容
        value = float(cleaned)
    except ValueError:
        return None
    return int(value)


def extract_prices_from_page(page) -> list[tuple[int, str, str]]:
    """ページから (price_jpy, title, url) のリストを抽出する。

    優先順位:
      1. JSON-LD (script[type="application/ld+json"]) の Product schema
      2. DOM の data-component="ProductCardLink" 系要素
    """
    results: list[tuple[int, str, str]] = []

    # 1. JSON-LD
    try:
        ld_blocks = page.eval_on_selector_all(
            'script[type="application/ld+json"]',
            "els => els.map(e => e.textContent)",
        )
    except Exception:
        ld_blocks = []
    for block in ld_blocks or []:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            # ItemList → itemListElement
            if item.get("@type") == "ItemList":
                for elem in item.get("itemListElement", []) or []:
                    product = elem.get("item") if isinstance(elem, dict) else None
                    if isinstance(product, dict):
                        _try_collect_product(product, results)
            elif item.get("@type") == "Product":
                _try_collect_product(item, results)

    # 2. DOM フォールバック
    if not results:
        try:
            cards = page.query_selector_all('[data-component="ProductCardLink"], a[href*="/shopping/"]')
        except Exception:
            cards = []
        for card in cards[:8]:
            try:
                title = (card.text_content() or "").strip()
                href = card.get_attribute("href") or ""
                price_text = ""
                price_el = card.query_selector('[data-component*="Price"], [class*="rice"]')
                if price_el:
                    price_text = (price_el.text_content() or "").strip()
                price_jpy = parse_jpy(price_text)
                if price_jpy and title:
                    full_url = href if href.startswith("http") else f"https://www.farfetch.com{href}"
                    results.append((price_jpy, title[:120], full_url))
            except Exception:
                continue

    return results


def _try_collect_product(item: dict, results: list[tuple[int, str, str]]) -> None:
    name = item.get("name", "") or ""
    url = item.get("url", "") or item.get("@id", "")
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_text = ""
    if isinstance(offers, dict):
        price_text = str(
            offers.get("price")
            or offers.get("lowPrice")
            or offers.get("highPrice")
            or ""
        )
    price_jpy = parse_jpy(price_text)
    if price_jpy and name:
        results.append((price_jpy, name[:120], url))


def fetch_one(page, vendor: str, title: str) -> ExternalBenchmark:
    """1 商品分の Farfetch ベンチマークを取得。"""
    query = build_query(vendor, title)
    url = FARFETCH_SEARCH_URL.format(query=quote_plus(query))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(1.5)
        results = extract_prices_from_page(page)
    except Exception as exc:
        print(f"  ⚠️  fetch エラー ({vendor} - {title[:30]}): {exc}", file=sys.stderr)
        results = []

    if not results:
        bench = ExternalBenchmark.empty(source="farfetch_jp")
        bench.fetched_at = datetime.utcnow().isoformat()
        return bench

    results.sort(key=lambda x: x[0])
    min_price, top_title, top_url = results[0]
    return ExternalBenchmark(
        source="farfetch_jp",
        matched_url=top_url,
        matched_title=top_title,
        min_price_jpy=min_price,
        sample_count=len(results),
        fetched_at=datetime.utcnow().isoformat(),
    )


def is_cache_fresh(bench: ExternalBenchmark) -> bool:
    if not bench.fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(bench.fetched_at)
    except ValueError:
        return False
    age = (datetime.utcnow() - fetched).total_seconds()
    return age < CACHE_TTL_SEC


def main() -> int:
    parser = argparse.ArgumentParser(description="Farfetch JP ベンチマーク価格取得")
    parser.add_argument("--csv", required=True, help="入力 CSV (filter の出力)")
    parser.add_argument("--output", required=True, help="出力 JSON")
    parser.add_argument("--limit", type=int, default=20,
                        help="fetch 件数上限 (デフォルト 20)")
    parser.add_argument("--no-cache", action="store_true",
                        help="既存キャッシュを無視して全件再 fetch")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="ヘッドレスで起動 (デフォルト)")
    args = parser.parse_args()

    # CSV 読込 + 対象フィルタ
    targets: list[dict] = []
    with open(args.csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            reason = row.get("decision_reason", "")
            if reason in TARGET_REASONS and row.get("action") == "list":
                targets.append(row)
    if not targets:
        print("ℹ️  対象商品なし (decision_reason フィルタ通過 0 件)")
        return 0

    targets = targets[: args.limit]
    print(f"📥 {len(targets)} 件を Farfetch JP で検索します")

    cache: dict[str, ExternalBenchmark] = {}
    if not args.no_cache:
        cache = load_benchmarks(args.output)
        if cache:
            print(f"♻️  既存キャッシュ {len(cache)} 件を読込")

    # Playwright 起動
    cfg = Config()
    from playwright.sync_api import sync_playwright

    benchmarks: dict[str, ExternalBenchmark] = dict(cache)
    new_count = 0
    skipped_cache = 0

    with sync_playwright() as pw:
        launch_args: dict = {"headless": args.headless}
        if cfg.chromium_executable_path and os.path.exists(cfg.chromium_executable_path):
            launch_args["executable_path"] = cfg.chromium_executable_path
        browser = pw.chromium.launch(**launch_args)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            locale="ja-JP",
        )
        page = ctx.new_page()

        try:
            for idx, row in enumerate(targets, 1):
                vendor = row.get("vendor", "").strip()
                title = (row.get("title") or row.get("﻿title") or "").strip()
                sku = row.get("sku", "").strip()
                key = make_product_key(vendor, title, sku)

                cached = benchmarks.get(key)
                if cached and is_cache_fresh(cached):
                    skipped_cache += 1
                    print(f"[{idx}/{len(targets)}] ♻️  cached: {vendor} - {title[:40]}")
                    continue

                print(f"[{idx}/{len(targets)}] 🔍 fetch: {vendor} - {title[:40]}")
                bench = fetch_one(page, vendor, title)
                benchmarks[key] = bench
                new_count += 1

                if bench.sample_count > 0:
                    print(f"    → ¥{bench.min_price_jpy:,} (n={bench.sample_count}) {bench.matched_title}")
                else:
                    print(f"    → 該当なし")

                # rate limit
                time.sleep(random.uniform(*RATE_LIMIT_SEC))

                # 5 件ごとに途中保存
                if new_count % 5 == 0:
                    save_benchmarks(args.output, benchmarks)
        finally:
            ctx.close()
            browser.close()

    save_benchmarks(args.output, benchmarks)
    print(f"\n✅ 完了: 新規 {new_count}, キャッシュ {skipped_cache}, 計 {len(benchmarks)} 件")
    print(f"   保存先: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
