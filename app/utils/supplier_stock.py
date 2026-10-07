"""出品済み商品の仕入先在庫・現在価格の確認 (仕入先ごと、サイズごと)。

check_inventory.py / update_listed_prices.py が共通で使う。

- 仕入先は出品記録の source_name 列で決める。列が空なら product_url のホスト名から
  data/sources.json / 専用クラスの URL と照合して推定し、分からなければ確認しない
  (2026-10 以前は全件 baseblu の API に問い合わせていた)。
- Shopify の商品は ``/products/<handle>.js`` を使う。``.json`` の variants には
  ``available`` が無く (2026-10-07 baseblu で確認)、以前の実装は「全サイズ売切」
  「先頭バリアントの価格」と誤判定していた。``.js`` の価格は最小通貨単位 (セント)。
- 価格・在庫は「出品したサイズ」で判定する (一部サイズだけ売切れた場合を検出する)。
"""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

USER_AGENT = "buyma-automation/stock-check (+low frequency; public product data only)"


# ---------------------------------------------------------------------------
# 仕入先の特定
# ---------------------------------------------------------------------------

def _host(url: str) -> str:
    try:
        host = urlsplit(url or "").netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def known_source_hosts() -> dict[str, str]:
    """{ホスト名: 仕入先名}。専用クラス (baseblu) と data/sources.json から作る。"""
    from app.core.sources.config_source import load_source_configs

    hosts = {"baseblu.com": "baseblu"}
    try:
        configs = load_source_configs()
    except ValueError:
        configs = {}
    for name, cfg in configs.items():
        h = _host(str(cfg.get("product_url_template", "")))
        if h:
            hosts.setdefault(h, name)
    return hosts


def resolve_record_source(record: dict, hosts: Optional[dict[str, str]] = None) -> Optional[str]:
    """出品記録 1 件の仕入先名。分からなければ None。"""
    name = (record.get("source_name") or "").strip().lower()
    if name:
        return name
    host = _host(record.get("product_url") or "")
    if not host:
        return None
    return (hosts if hosts is not None else known_source_hosts()).get(host)


# ---------------------------------------------------------------------------
# Shopify 商品 JSON (.js)
# ---------------------------------------------------------------------------

def product_js_url(product_url: str) -> Optional[str]:
    """商品ページ URL → 同じストア (en-us 等の市場パスも維持) の ``/products/<handle>.js``。"""
    if not product_url:
        return None
    parts = urlsplit(product_url)
    path = parts.path
    idx = path.find("/products/")
    if idx < 0 or not parts.netloc:
        return None
    handle = path[idx + len("/products/"):].split("/")[0]
    if not handle:
        return None
    for suffix in (".json", ".js"):
        if handle.endswith(suffix):
            handle = handle[: -len(suffix)]
    new_path = path[:idx] + "/products/" + handle + ".js"
    return urlunsplit((parts.scheme or "https", parts.netloc, new_path, "", ""))


def _size_of(variant: dict) -> str:
    return str(variant.get("option1") or variant.get("title") or "").strip()


def parse_shopify_product_js(data: dict) -> dict:
    """``.js`` の dict → {title, product_type, variants: [{size, price, available}]}。

    price は現地通貨の単位 (セント → /100)。
    """
    variants = []
    for v in data.get("variants") or []:
        try:
            price = float(v.get("price")) / 100.0
        except (TypeError, ValueError):
            price = None
        variants.append({
            "size": _size_of(v),
            "price": price,
            "available": bool(v.get("available")),
        })
    return {
        "title": data.get("title", ""),
        "product_type": data.get("type", "") or data.get("product_type", ""),
        "variants": variants,
    }


def fetch_product_snapshot(product_url: str, timeout: float = 15.0) -> dict:
    """公開商品データを 1 回取得する。失敗時は {"error": ...}。"""
    url = product_js_url(product_url)
    if not url:
        return {"error": f"商品 URL から .js を作れません: {product_url!r}"}
    try:
        import requests

        resp = requests.get(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                            timeout=timeout)
        resp.raise_for_status()
        return parse_shopify_product_js(resp.json())
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 判定 (純粋関数)
# ---------------------------------------------------------------------------

def split_sizes(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    return [s.strip() for s in items if s and s.strip()]


def evaluate_stock(snapshot: dict, listed_sizes: Iterable[str] | str | None = None) -> dict:
    """在庫判定。

    戻り値: {"status": "in_stock" | "partial" | "sold_out" | "error",
             "available_sizes": [...], "missing_listed_sizes": [...]}
    - listed_sizes が分かる場合は「出品したサイズのうち売切れたもの」を missing に入れ、
      全部売切なら sold_out、一部なら partial (BUYMA 側でそのサイズを在庫なしにする必要あり)
    - 分からない場合 (旧形式の記録) はどれか 1 サイズでも在庫があれば in_stock
    """
    if snapshot.get("error"):
        return {"status": "error", "error": snapshot["error"], "available_sizes": [], "missing_listed_sizes": []}
    variants = snapshot.get("variants") or []
    available = [v["size"] for v in variants if v.get("available")]
    listed = split_sizes(listed_sizes)
    if listed:
        avail_set = {s.lower() for s in available}
        missing = [s for s in listed if s.lower() not in avail_set]
        if len(missing) == len(listed):
            status = "sold_out"
        elif missing:
            status = "partial"
        else:
            status = "in_stock"
        return {"status": status, "available_sizes": available, "missing_listed_sizes": missing}
    return {"status": "in_stock" if available else "sold_out",
            "available_sizes": available, "missing_listed_sizes": []}


def price_for_listing(snapshot: dict, listed_sizes: Iterable[str] | str | None = None) -> Optional[float]:
    """価格追従に使う現在の仕入値。

    出品したサイズのうち在庫があるものの **最高値** (サイズで値段が違うとき赤字を避ける)。
    出品サイズが不明なら在庫ありバリアントの最高値。在庫が無ければ None。
    """
    variants = [v for v in (snapshot.get("variants") or []) if v.get("available") and v.get("price")]
    listed = {s.lower() for s in split_sizes(listed_sizes)}
    if listed:
        variants = [v for v in variants if v["size"].lower() in listed]
    if not variants:
        return None
    return max(v["price"] for v in variants)
