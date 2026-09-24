"""First Sale Sprint — 「最初の実売データ」を最短で取るための純ロジック。

## 問題の再定義 (2026-07-03)

本システムはこれまで open-loop だった: pricing / opportunity / demand の全係数が
仮定値のまま、実市場からの帰還信号 (自社出品のアクセス・ほしいもの・成約) を
消費するコードが 1 行も存在しなかった。opportunity.py 自身が
「係数は運用実績で較正する」と書きながら、運用実績を取る経路が未実装だった。

本モジュールは閉ループの起点:

    filter CSV → スプリント候補選定 → (ツールで下書き / 人間が公開)
      → funnel.py が自社出品の実測値を採取
      → decision_gate.py が「モデル自身の予測」を実測で検定

## 設計判断: 下書きはツール、公開は人間

残存する自動化の未解決課題 (発送地 radio / 未採取カテゴリ leaf / 未検証の
publish フロー) は、いずれも **自動公開だけ** を阻むものであり、
「ツールが保存した下書きを人間が管理画面で仕上げて公開する」経路は
今日すでに開通している (HANDOFF: 発送地未設定でも下書き保存は通る)。
よってスプリントは draft-by-tool / publish-by-human で走らせ、
自動公開の完成をボトルネックから外す。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# sale_probability は opportunity.py の定義により「月次」成約確率
DAYS_PER_MONTH = 30.0
# BUYMA 購入期限のデフォルト運用 (buyma_auto_listing は 90 日後を設定)
LISTING_LIFETIME_DAYS = 90.0


@dataclass
class SprintCandidate:
    """スプリント出品候補 1 件。row_index は filter CSV 内の 1-based 行番号
    (buyma_auto_listing.py の --from N とそのまま対応する)。"""

    row_index: int
    title: str
    vendor: str
    final_price_jpy: int
    expected_profit_jpy: int
    sale_probability: float
    opportunity_score: int
    product_url: str = ""
    product_type: str = ""
    # 公開後に埋まるフィールド
    item_id: Optional[str] = None
    published_at: Optional[str] = None  # ISO 文字列

    def to_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "title": self.title,
            "vendor": self.vendor,
            "final_price_jpy": self.final_price_jpy,
            "expected_profit_jpy": self.expected_profit_jpy,
            "sale_probability": self.sale_probability,
            "opportunity_score": self.opportunity_score,
            "product_url": self.product_url,
            "product_type": self.product_type,
            "item_id": self.item_id,
            "published_at": self.published_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SprintCandidate":
        return cls(
            row_index=int(d.get("row_index") or 0),
            title=d.get("title", ""),
            vendor=d.get("vendor", ""),
            final_price_jpy=int(d.get("final_price_jpy") or 0),
            expected_profit_jpy=int(d.get("expected_profit_jpy") or 0),
            sale_probability=float(d.get("sale_probability") or 0.0),
            opportunity_score=int(d.get("opportunity_score") or 0),
            product_url=d.get("product_url", ""),
            product_type=d.get("product_type", ""),
            item_id=d.get("item_id") or None,
            published_at=d.get("published_at") or None,
        )


def _to_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select_sprint_candidates(
    rows: list[dict],
    limit: int = 10,
    max_price_jpy: Optional[int] = None,
) -> list[SprintCandidate]:
    """filter CSV の行 (ファイル順) からスプリント候補を選ぶ。

    - action == "list" のみ (skip / review は除外)
    - final_price_jpy が正であること
    - opportunity_score 降順 (同点は expected_profit 降順)
    - row_index は **ファイル内の 1-based 位置** を保持する。
      buyma_auto_listing.py --from N は CSV のファイル順を参照するため、
      ソート後の順位ではなく元の行番号を渡さないと別商品を出品してしまう。
    """
    picked: list[SprintCandidate] = []
    for idx, row in enumerate(rows, start=1):
        action = (row.get("action") or "").strip().lower()
        if action != "list":
            continue
        price = _to_int(row.get("final_price_jpy") or row.get("selling_price_jpy"))
        if price <= 0:
            continue
        if max_price_jpy is not None and price > max_price_jpy:
            continue
        picked.append(
            SprintCandidate(
                row_index=idx,
                title=(row.get("title") or "").strip(),
                vendor=(row.get("vendor") or "").strip(),
                final_price_jpy=price,
                expected_profit_jpy=_to_int(
                    row.get("expected_profit_jpy") or row.get("profit_jpy")
                ),
                sale_probability=_to_float(row.get("sale_probability")),
                opportunity_score=_to_int(row.get("opportunity_score")),
                product_url=(row.get("product_url") or "").strip(),
                product_type=(row.get("product_type") or "").strip(),
            )
        )

    picked.sort(
        key=lambda c: (-c.opportunity_score, -c.expected_profit_jpy, c.row_index)
    )
    return picked[: max(0, limit)]


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def elapsed_days(published_at: Optional[str], as_of: datetime) -> float:
    """公開からの経過日数。未公開・不正値は 0。listing 寿命 (90日) で頭打ち。"""
    dt = _parse_iso(published_at) if published_at else None
    if dt is None:
        return 0.0
    days = (as_of - dt).total_seconds() / 86400.0
    return max(0.0, min(days, LISTING_LIFETIME_DAYS))


def expected_sales_lambda(items: list[SprintCandidate], as_of: datetime) -> float:
    """モデル自身の予測: 公開済み商品の期待成約数 λ。

    sale_probability は月次成約確率 (opportunity.py) なので、
    商品 i の寄与は p_i × (公開経過日数 / 30)。
    これがそのまま Poisson 検定 (decision_gate) の帰無仮説になる。
    """
    lam = 0.0
    for it in items:
        if not it.published_at:
            continue
        lam += max(0.0, it.sale_probability) * (
            elapsed_days(it.published_at, as_of) / DAYS_PER_MONTH
        )
    return lam


def exposure_months(items: list[SprintCandidate], as_of: datetime) -> float:
    """公開済み商品の露出量の合計 (商品・月)。rule of three の分母。"""
    return sum(
        elapsed_days(it.published_at, as_of) / DAYS_PER_MONTH
        for it in items
        if it.published_at
    )


def days_until_decisive(
    items: list[SprintCandidate],
    as_of: datetime,
    p0_threshold: float = 0.10,
) -> Optional[float]:
    """「成約 0 のままならモデルが棄却される」時点まであと何日かを概算する。

    P(0 | λ) = exp(-λ) < p0_threshold ⇔ λ > ln(1/p0_threshold)。
    公開済み全商品の日次ハザード Σp_i/30 が今後も一定と仮定して外挿する。
    公開済みが無い場合は None。
    """
    daily_rate = sum(
        max(0.0, it.sale_probability) / DAYS_PER_MONTH
        for it in items
        if it.published_at
    )
    if daily_rate <= 0:
        return None
    target_lambda = math.log(1.0 / p0_threshold)
    current = expected_sales_lambda(items, as_of)
    if current >= target_lambda:
        return 0.0
    return (target_lambda - current) / daily_rate


@dataclass
class SprintManifest:
    """data/first_sale_sprint.json の構造。"""

    created_at: str
    source_csv: str
    items: list[SprintCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "source_csv": self.source_csv,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SprintManifest":
        return cls(
            created_at=d.get("created_at", ""),
            source_csv=d.get("source_csv", ""),
            items=[SprintCandidate.from_dict(x) for x in d.get("items", [])],
        )

    def mark_published(
        self, row_index: int, item_id: str, published_at: str
    ) -> bool:
        """row_index の候補に item_id と公開日時を記録する。"""
        for it in self.items:
            if it.row_index == row_index:
                it.item_id = str(item_id)
                it.published_at = published_at
                return True
        return False

    def published_items(self) -> list[SprintCandidate]:
        return [it for it in self.items if it.published_at]
