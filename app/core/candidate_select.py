"""手入力で出品する最初の数件の候補選定 (純粋関数)。

scripts/select_listing_candidates.py が使う。BUYMA にはアクセスしない。

方針 (2026-10-08 M1):
  - 原価 (補正後の総仕入原価) ≤ 上限、見込み利益 ≥ 下限
  - よく出るサイズ (common size) の在庫がある。在庫サイズのうち common なものだけを出品する
  - BUYMA で売れやすいブランドを優先 (data/brand_demand_tiers.json。実測ではなく暫定の推測)
  - 競合価格は本人が BUYMA の検索ページで目視する (検索 URL を出すだけ。取得はしない)
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from app.utils.listing_helpers import classify_size_category

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BRAND_TIERS_PATH = PROJECT_ROOT / "data" / "brand_demand_tiers.json"

BUYMA_SEARCH_URL_BASE = "https://www.buyma.com/r/"
TIER_WEIGHT = {"A": 3, "B": 2, "C": 1}

# よく出るサイズ (経験則)。範囲外・ブランド独自表記 (0〜4 など) は「要確認」として出品しない
COMMON_ALPHA_CLOTHING = {"XS", "S", "M", "L", "XL"}
COMMON_IT_CLOTHING = (36, 52)          # IT 36〜52 (レディース 36〜46 / メンズ 44〜52 / 襟 38〜43 を含む)
COMMON_JEANS_WAIST = (24, 32)          # デニムのウエスト (インチ)
COMMON_EU_SHOES = (35.5, 44.0)         # EU 35.5〜44 (レディース 22.5〜25.5cm / メンズ 25.5〜28cm 相当)
ONE_SIZE_TOKENS = {"UNI", "UNICA", "TAGLIA UNICA", "ONE SIZE", "ONESIZE", "OS", "TU", "FREE", "U"}
# サイズの軸が無い商品 (Shopify の Title / Default Title) を「ワンサイズ」として扱うときの印
ONE_SIZE_MARKER = "ONE SIZE"
_FALSY = {"false", "0", "no"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


# ---------------------------------------------------------------------------
# ブランド
# ---------------------------------------------------------------------------

def load_brand_tiers(path: str | Path | None = None) -> dict:
    p = Path(path) if path else BRAND_TIERS_PATH
    if not p.exists():
        return {"tiers": {}, "aliases": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def canonical_brand(vendor: str, data: Optional[dict] = None) -> str:
    """仕入先のブランド表記 → BUYMA で使われるブランド表記 (大文字・アクセント除去)。"""
    data = data if data is not None else load_brand_tiers()
    v = _norm(vendor)
    aliases = {_norm(k): _norm(val) for k, val in (data.get("aliases") or {}).items()}
    return aliases.get(v, v)


def brand_tier(vendor: str, data: Optional[dict] = None) -> str:
    data = data if data is not None else load_brand_tiers()
    name = canonical_brand(vendor, data)
    for tier in ("A", "B"):
        if name in {_norm(b) for b in (data.get("tiers") or {}).get(tier, [])}:
            return tier
    return "C"


# ---------------------------------------------------------------------------
# サイズ
# ---------------------------------------------------------------------------

def split_sizes(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    return [s.strip() for s in items if s and s.strip()]


def is_common_size(size: str, product_type: str, title: str = "") -> bool:
    s = _norm(size)
    if not s:
        return False
    pt = _norm(product_type)
    if s in ONE_SIZE_TOKENS:
        return True
    m = re.fullmatch(r"(?:IT|EU|FR)?\s*(\d+(?:[.,]5)?)", s)
    num = float(m.group(1).replace(",", ".")) if m else None
    if pt == "FOOTWEAR":
        return num is not None and COMMON_EU_SHOES[0] <= num <= COMMON_EU_SHOES[1]
    if pt == "CLOTHING":
        if s in COMMON_ALPHA_CLOTHING:
            return True
        if num is None:
            return False
        if "JEAN" in _norm(title) or "DENIM" in _norm(title):
            return COMMON_JEANS_WAIST[0] <= num <= COMMON_JEANS_WAIST[1] or COMMON_IT_CLOTHING[0] <= num <= COMMON_IT_CLOTHING[1]
        return COMMON_IT_CLOTHING[0] <= num <= COMMON_IT_CLOTHING[1]
    # BAGS / ACCESSORIES / その他: 数値 (ベルト長・リング等) はそのまま可
    return True


def common_sizes(available_sizes: str | Iterable[str] | None, product_type: str, title: str = "") -> list[str]:
    return [s for s in split_sizes(available_sizes) if is_common_size(s, product_type, title)]


def is_sizeless_single(row: dict) -> bool:
    """サイズの軸が無い在庫ありのバッグ・小物 (= ワンサイズとして出品できる) か。

    Shopify の Title / Default Title だけの商品は select_listing_variants() が available_sizes を
    空にする。上流 (baseblu_sales_to_csv → filter_baseblu_profitable / --refresh の在庫確認) で
    在庫ありを確認済みの行なので、バリエーションなし (classify_size_category == 'single') の
    商品に限りワンサイズとみなす。次の場合は対象外 (= 在庫なし扱いのまま):
      - 服・靴 (サイズ別に出すのでサイズ不明は出さない)
      - サイズの軸がある (sizes がある) のに在庫ありサイズが無い = 売切
      - 基準価格より高いサイズしか無い (priced_out_sizes)
      - available / stock_status 列で在庫なしと分かっている
    """
    if classify_size_category(row.get("product_type", "")) != "single":
        return False
    if split_sizes(row.get("available_sizes")) or split_sizes(row.get("source_available_sizes")):
        return False
    if split_sizes(row.get("sizes")) or split_sizes(row.get("priced_out_sizes")):
        return False
    if str(row.get("available") or "").strip().lower() in _FALSY:
        return False
    if str(row.get("stock_status") or "").strip().lower().startswith("sold_out"):
        return False
    return True


# ---------------------------------------------------------------------------
# BUYMA 検索 URL (本人が目視で競合価格を見るため。取得はしない)
# ---------------------------------------------------------------------------

def buyma_search_url(*parts: str) -> str:
    """https://www.buyma.com/r/{キーワード}/ (scripts/fetch_buyma_market_prices.py と同じ形式)。"""
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return BUYMA_SEARCH_URL_BASE + quote(text) + "/"


_TITLE_STOPWORDS = {"WITH", "AND", "IN", "THE", "OF", "FOR", "A"}


def title_keyword(title: str, max_words: int = 3) -> str:
    """商品名から検索用の英単語 (例 'Leather Card Holder')。"""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", _norm(title)) if w not in _TITLE_STOPWORDS]
    return " ".join(words[:max_words]).title()


def model_number(sku: str) -> str:
    """仕入先 SKU (例 'S56UI0143P4455_T8013') → 品番欄・検索用 (色コードの '_' 以降を落とす)。"""
    return (sku or "").strip().split("_")[0].strip()


def search_urls(vendor: str, title: str, sku: str = "", data: Optional[dict] = None) -> dict:
    brand = canonical_brand(vendor, data)
    out = {"buyma_search_url": buyma_search_url(brand, title_keyword(title))}
    model = model_number(sku)
    if model:
        out["buyma_search_url_sku"] = buyma_search_url(brand, model)
    return out


# ---------------------------------------------------------------------------
# 選定
# ---------------------------------------------------------------------------

def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_candidate(row: dict, *, max_cost: float, min_profit: float, data: Optional[dict] = None) -> dict:
    """profitable CSV の 1 行 → {"ok", "reasons", "tier", "common_sizes", "score", ...}。"""
    reasons = []
    cost = _num(row.get("total_cost_jpy"))
    profit = _num(row.get("expected_profit_jpy")) or _num(row.get("profit_jpy"))
    if (row.get("action") or "list").strip().lower() != "list":
        reasons.append(f"action={row.get('action')}")
    if cost <= 0 or cost > max_cost:
        reasons.append(f"原価 ¥{cost:,.0f} > 上限 ¥{max_cost:,.0f}")
    if profit < min_profit:
        reasons.append(f"見込み利益 ¥{profit:,.0f} < ¥{min_profit:,.0f}")
    pt = row.get("product_type", "")
    sizes = common_sizes(row.get("available_sizes"), pt, row.get("title", ""))
    if not sizes and is_sizeless_single(row):
        sizes = [ONE_SIZE_MARKER]   # サイズ表記の無いバッグ・小物 (CSV の available_sizes は空のまま)
    if not sizes:
        reasons.append(f"よく出るサイズの在庫なし ({row.get('available_sizes') or '在庫サイズ不明'})")
    tier = brand_tier(row.get("vendor", ""), data)
    score = TIER_WEIGHT[tier] * 1_000_000 + len(sizes) * 10_000 + profit
    return {"ok": not reasons, "reasons": reasons, "tier": tier, "common_sizes": sizes,
            "cost": cost, "profit": profit, "score": score}


def dedupe_key(row: dict, data: Optional[dict] = None) -> tuple:
    """同じ商品の色違い等を 1 件にまとめるキー。

    正式ブランド名 + 品番 (SKU の '_' より前。色コードは '_' の後ろ)。SKU が無ければ商品名で代用する
    (商品名は「Shirt」など汎用的なことがあるので、品番がある限り使わない)。
    """
    brand = canonical_brand(row.get("vendor", ""), data)
    model = model_number(row.get("sku", ""))
    return (brand, "sku", model.upper()) if model else (brand, "title", _norm(row.get("title", "")))


def select_candidates(rows: list[dict], *, max_cost: float, min_profit: float, limit: int,
                      data: Optional[dict] = None, dedupe: bool = True,
                      max_per_brand: int = 0) -> tuple[list[dict], list[tuple]]:
    """(選ばれた行 [評価結果を "_eval" に付与], 除外 [(title, reasons)])。スコア降順。

    dedupe: 同じブランド + 商品名 (色違い) は上位 1 件だけ。max_per_brand > 0 ならブランドごとの上限。
    """
    picked, rejected = [], []
    for r in rows:
        ev = evaluate_candidate(r, max_cost=max_cost, min_profit=min_profit, data=data)
        if ev["ok"]:
            picked.append({**r, "_eval": ev})
        else:
            rejected.append((r.get("title", ""), ev["reasons"]))
    picked.sort(key=lambda r: r["_eval"]["score"], reverse=True)
    if dedupe:
        seen, uniq = set(), []
        for r in picked:
            k = dedupe_key(r, data)
            if k in seen:
                rejected.append((r.get("title", ""), ["同じ商品の別色/別バリアント (上位を採用)"]))
                continue
            seen.add(k)
            uniq.append(r)
        picked = uniq
    if max_per_brand > 0:
        count: dict[str, int] = {}
        kept = []
        for r in picked:
            b = canonical_brand(r.get("vendor", ""), data)
            if count.get(b, 0) >= max_per_brand:
                rejected.append((r.get("title", ""), [f"同じブランドは {max_per_brand} 件まで"]))
                continue
            count[b] = count.get(b, 0) + 1
            kept.append(r)
        picked = kept
    return picked[:limit] if limit else picked, rejected
