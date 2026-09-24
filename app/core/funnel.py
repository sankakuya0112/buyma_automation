"""自社出品ファネルの実測 — BUYMA 出品リストのアクセス/ほしいもの/成約の解析。

closed-loop 化の観測レイヤ。scripts/track_listing_funnel.py (Mac 実行) が
取得した HTML をここの純粋関数で解析し、data/funnel_history.json に
スナップショットとして蓄積する。decision_gate.py がこれを消費する。

PLUSELECT の BuyManager が「アクセス/ほしいもの/カート集計」を実運用して
いた通り、これらは出品者自身のページから読める一次需要データであり、
成約 (遅い・まばら) より 2〜3 桁速く返ってくる先行指標。

⚠️ セレクタ規約: 実 DOM は初回 Mac 実走の --debug-html ダンプで確定する
(update_listed_prices._dump_edit_page_state と同じ運用)。ここでは
「item_id リンクで行を区切り、行チャンク内のラベル付き数値を拾う」
という DOM 構造に依存しない正規表現方式を採る。
"""

from __future__ import annotations

import re
from typing import Optional

# 出品リスト行の区切りに使う item_id の出現パターン。
# 出品リスト内のリンクは /item/{id} (公開ページ) と
# /my/sell/{id}/edit (編集ページ) の 2 系統が想定される。
_ITEM_ID_RE = re.compile(r"/(?:item|my/sell)/(\d{6,})")

# 行チャンク内のカウント: 「ラベル ... 数値」を最大 40 文字の隙間まで許容
_COUNT_PATTERNS = {
    "access": re.compile(r"アクセス[^0-9]{0,40}([\d,]+)"),
    "wish": re.compile(r"(?:ほしいもの|欲しいもの|お気に入り)[^0-9]{0,40}([\d,]+)"),
    "cart": re.compile(r"カート[^0-9]{0,40}([\d,]+)"),
}

# 出品ステータスの既知トークン (先勝ち)
_STATUS_TOKENS = ["取引中", "売り切れ", "売切れ", "SOLD", "停止中", "下書き", "出品中"]

_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<a[^>]*/(?:item|my/sell)/\d{6,}[^>]*>([^<]{4,120})</a>")


def parse_count(text: Optional[str]) -> int:
    """'1,234' → 1234。None/不正値は 0。"""
    if not text:
        return 0
    try:
        return int(text.replace(",", "").strip())
    except ValueError:
        return 0


def extract_seller_items(html: str) -> list[dict]:
    """出品リストページ HTML から 1 出品 = 1 dict を抽出する。

    戻り値 dict: {item_id, title, status, access, wish, cart}
    同一 item_id の重複出現 (画像リンクとタイトルリンク等) は最初の
    出現位置で 1 チャンクにまとめる。
    """
    if not html:
        return []

    # item_id の初出位置で行チャンクに分割する
    seen: dict[str, int] = {}
    for m in _ITEM_ID_RE.finditer(html):
        item_id = m.group(1)
        if item_id not in seen:
            seen[item_id] = m.start()
    if not seen:
        return []

    ordered = sorted(seen.items(), key=lambda kv: kv[1])
    bounds = [pos for _, pos in ordered] + [len(html)]

    items: list[dict] = []
    for i, (item_id, _) in enumerate(ordered):
        chunk = html[bounds[i]: bounds[i + 1]]
        text = _TAG_RE.sub(" ", chunk)

        title = ""
        tm = _TITLE_RE.search(chunk)
        if tm:
            title = tm.group(1).strip()

        status = ""
        for token in _STATUS_TOKENS:
            if token in text:
                status = token
                break

        counts = {}
        for key, pat in _COUNT_PATTERNS.items():
            cm = pat.search(text)
            counts[key] = parse_count(cm.group(1)) if cm else 0

        items.append(
            {
                "item_id": item_id,
                "title": title,
                "status": status,
                "access": counts["access"],
                "wish": counts["wish"],
                "cart": counts["cart"],
            }
        )
    return items


def count_sold(items: list[dict]) -> int:
    """スナップショット内の成約済み (売切/取引中) 件数。"""
    return sum(
        1 for it in items if it.get("status") in ("売り切れ", "売切れ", "SOLD", "取引中")
    )


def diff_snapshots(prev: Optional[dict], curr: dict) -> dict:
    """前回スナップショットとの差分 (Δアクセス/Δほしいもの/新規成約)。

    prev が None (初回) なら delta は curr の絶対値をそのまま返す。
    戻り値: {"per_item": [{item_id, title, access, wish, d_access, d_wish}],
             "totals": {...}}
    """
    prev_map = {}
    if prev:
        prev_map = {it["item_id"]: it for it in prev.get("items", [])}

    per_item = []
    totals = {"access": 0, "wish": 0, "d_access": 0, "d_wish": 0}
    for it in curr.get("items", []):
        old = prev_map.get(it["item_id"], {})
        d_access = it.get("access", 0) - old.get("access", 0)
        d_wish = it.get("wish", 0) - old.get("wish", 0)
        per_item.append(
            {
                "item_id": it["item_id"],
                "title": it.get("title", ""),
                "status": it.get("status", ""),
                "access": it.get("access", 0),
                "wish": it.get("wish", 0),
                "d_access": d_access,
                "d_wish": d_wish,
            }
        )
        totals["access"] += it.get("access", 0)
        totals["wish"] += it.get("wish", 0)
        totals["d_access"] += d_access
        totals["d_wish"] += d_wish

    totals["sold"] = count_sold(curr.get("items", []))
    totals["new_sold"] = totals["sold"] - (count_sold(prev.get("items", [])) if prev else 0)
    return {"per_item": per_item, "totals": totals}


def latest_metrics_by_item(history: dict) -> dict[str, dict]:
    """funnel_history.json 全体から item_id → 最新の実測値を引くインデックス。"""
    result: dict[str, dict] = {}
    for snap in history.get("snapshots", []):
        for it in snap.get("items", []):
            result[it["item_id"]] = {**it, "ts": snap.get("ts", "")}
    return result


def weekly_access_rates(
    history: dict, item_ids: list[str], as_of_days: dict[str, float]
) -> list[float]:
    """公開済み各商品の「週あたりアクセス数」を最新スナップショットから算出。

    as_of_days: item_id → 公開からの経過日数。1 日未満は 1 日として扱い、
    0 除算と初日の過大評価を防ぐ。
    """
    latest = latest_metrics_by_item(history)
    rates = []
    for item_id in item_ids:
        metrics = latest.get(item_id)
        if metrics is None:
            continue
        days = max(1.0, as_of_days.get(item_id, 1.0))
        rates.append(metrics.get("access", 0) / days * 7.0)
    return rates
