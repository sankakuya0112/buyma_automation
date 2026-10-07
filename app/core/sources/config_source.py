"""data/sources.json から仕入先を組み立てる ConfigSource。

新しい仕入先を追加するのに Python コードを書かなくて済むようにするための層。
`data/sources.json` に 1 ブロック追加すれば

    python3 scripts/shopify_sales_to_csv.py --source <キー名>
    python3 scripts/filter_baseblu_profitable.py --source <キー名>

がそのまま動く。baseblu / italist のように専用クラスがある仕入先は
そちらが優先される (app/core/sources/__init__.py:get_source)。

設計上の約束:
  - 設定値が壊れていたら **黙って既定値で動かさず** ValueError を投げる。
    原価計算に直結するため、誤った値で出品するより止まる方が安全。
  - landed_cost_basis / VAT の扱いが不明な仕入先は DDU + vat_treatment="none" にする。
    原価を高めに見積もる = 赤字出品より機会損失を選ぶ、という安全側の倒し方。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.sources.base import VAT_TREATMENTS, BaseSource, resolve_vat_refund_rate

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_SOURCES_PATH = PROJECT_ROOT / "data" / "sources.json"

# 必須キー (欠けていたら ValueError)
REQUIRED_KEYS = (
    "products_json_url",
    "product_url_template",
    "currency",
    "country",
    "landed_cost_basis",
)

VALID_LANDED_COST_BASIS = ("DDP", "DDU")
VALID_STATUS = ("verified", "unverified", "disabled")
SUPPORTED_PLATFORMS = ("shopify",)

# 設定ファイルのキャッシュ (パス文字列 -> 設定 dict)
_config_cache: dict[str, dict[str, dict]] = {}


# ---------------------------------------------------------------------------
# 読み込み・検証
# ---------------------------------------------------------------------------

def load_source_configs(
    path: str | Path | None = None, *, force_reload: bool = False
) -> dict[str, dict]:
    """data/sources.json を読み込んで {source名: 設定dict} を返す。

    ファイルが存在しない場合は空 dict (専用クラスだけで動く従来構成に戻る)。
    JSON が壊れている場合は ValueError。
    """
    target = Path(path) if path is not None else DEFAULT_SOURCES_PATH
    key = str(target)
    if not force_reload and key in _config_cache:
        return _config_cache[key]

    if not target.exists():
        _config_cache[key] = {}
        return {}

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target} の JSON が壊れています: {exc}") from exc

    sources = raw.get("sources")
    if not isinstance(sources, dict):
        raise ValueError(f"{target} に 'sources' オブジェクトがありません")

    configs: dict[str, dict] = {}
    for name, cfg in sources.items():
        if name.startswith("_"):
            continue  # コメント用のキーは無視
        if not isinstance(cfg, dict):
            raise ValueError(f"{target}: sources.{name} がオブジェクトではありません")
        validate_source_config(name, cfg)
        configs[name.strip().lower()] = cfg

    _config_cache[key] = configs
    return configs


def _require_rate(name: str, cfg: dict, field: str, default: float) -> float:
    """0.0-1.0 の割合フィールドを取り出す。範囲外は ValueError。"""
    value = cfg.get(field, default)
    if value is None:
        value = default
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"sources.{name}.{field} が数値ではありません: {value!r}") from exc
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"sources.{name}.{field} は 0.0-1.0 の範囲で指定してください: {rate}")
    return rate


def validate_source_config(name: str, cfg: dict) -> None:
    """設定 1 件を検証する。問題があれば ValueError を投げる。"""
    missing = [k for k in REQUIRED_KEYS if not str(cfg.get(k) or "").strip()]
    if missing:
        raise ValueError(f"sources.{name} に必須項目がありません: {', '.join(missing)}")

    basis = str(cfg["landed_cost_basis"]).upper()
    if basis not in VALID_LANDED_COST_BASIS:
        raise ValueError(
            f"sources.{name}.landed_cost_basis は {'/'.join(VALID_LANDED_COST_BASIS)} "
            f"のいずれかにしてください: {cfg['landed_cost_basis']!r}"
        )

    platform = str(cfg.get("platform", "shopify")).lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            f"sources.{name}.platform は現在 {'/'.join(SUPPORTED_PLATFORMS)} のみ対応です: {platform!r}"
        )

    status = str(cfg.get("status", "unverified")).lower()
    if status not in VALID_STATUS:
        raise ValueError(
            f"sources.{name}.status は {'/'.join(VALID_STATUS)} のいずれかにしてください: {status!r}"
        )

    if "{handle}" not in str(cfg["product_url_template"]):
        raise ValueError(
            f"sources.{name}.product_url_template に {{handle}} が含まれていません: "
            f"{cfg['product_url_template']!r}"
        )

    resolve_config_vat(name, cfg)  # VAT の扱いを検証 (不正なら ValueError)

    for field, default in (
        ("purchase_fx_fee_rate", 0.0),
        ("customs_handling_rate", BaseSource.customs_handling_rate),
    ):
        _require_rate(name, cfg, field, default)

    for field in (
        "shipping_flat_local", "free_shipping_threshold_local", "domestic_shipping_jpy",
        "customs_handling_min_jpy",
    ):
        value = cfg.get(field)
        if value is None:
            continue
        try:
            if float(value) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sources.{name}.{field} は 0 以上の数値か null にしてください: {value!r}") from exc


def resolve_config_vat(name: str, cfg: dict) -> tuple[str, float, float]:
    """設定から (vat_treatment, local_vat_rate, 控除率) を決める。

    - 新形式: "vat_treatment": "none" | "deducted_at_checkout" (+ "local_vat_rate": 0.22)
    - 旧形式の "vat_refund_rate" は 0.0 のときだけ受け付ける ("none" と同じ)。
      0.167 のような手書きの控除率は「VAT 抜き価格への二重控除」「22% 国での控除不足」の
      どちらも起こすので、明示的な vat_treatment への書き換えを求めて止める。
    """
    treatment = cfg.get("vat_treatment")
    local_rate_raw = cfg.get("local_vat_rate", 0.0)
    try:
        local_rate = float(local_rate_raw or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"sources.{name}.local_vat_rate が数値ではありません: {local_rate_raw!r}") from exc
    if not 0.0 <= local_rate < 0.5:
        raise ValueError(f"sources.{name}.local_vat_rate は 0.0-0.5 の割合で指定してください: {local_rate}")

    legacy = None
    if "vat_refund_rate" in cfg and cfg.get("vat_refund_rate") is not None:
        legacy = _require_rate(name, cfg, "vat_refund_rate", 0.0)

    if treatment is None:
        if legacy and legacy > 0:
            raise ValueError(
                f"sources.{name}.vat_refund_rate={legacy} は廃止しました。"
                '"vat_treatment": "none" (表示価格がそのまま請求される) か '
                '"deducted_at_checkout" + "local_vat_rate" (VAT 込み表示で会計時に外れる) で書いてください'
            )
        treatment = "none"
    treatment = str(treatment).strip().lower()
    if treatment not in VAT_TREATMENTS:
        raise ValueError(f"sources.{name}.vat_treatment は {'/'.join(VAT_TREATMENTS)} のいずれか: {treatment!r}")
    try:
        refund = resolve_vat_refund_rate(treatment, local_rate)
    except ValueError as exc:
        raise ValueError(f"sources.{name}: {exc}") from exc
    if legacy is not None and abs(legacy - refund) > 1e-4:
        raise ValueError(
            f"sources.{name}.vat_refund_rate={legacy} が vat_treatment から決まる控除率 {refund} と矛盾します "
            "(vat_refund_rate を削除してください)"
        )
    return treatment, local_rate, refund


def get_source_config(name: str, path: str | Path | None = None) -> Optional[dict]:
    """1 件の設定を返す。未定義または disabled なら None。"""
    cfg = load_source_configs(path).get((name or "").strip().lower())
    if cfg is None:
        return None
    if str(cfg.get("status", "unverified")).lower() == "disabled":
        return None
    return cfg


def available_source_names(path: str | Path | None = None) -> list[str]:
    """disabled を除いた設定済み仕入先名 (アルファベット順)。"""
    return sorted(
        name for name, cfg in load_source_configs(path).items()
        if str(cfg.get("status", "unverified")).lower() != "disabled"
    )


# ---------------------------------------------------------------------------
# Source 実装
# ---------------------------------------------------------------------------

class ConfigSource(BaseSource):
    """data/sources.json の 1 エントリから作られる仕入先。"""

    def __init__(self, name: str, config: dict[str, Any]):
        validate_source_config(name, config)
        self.config = config
        self.name = (name or "").strip().lower()
        self.display_name = str(config.get("display_name") or self.name)
        self.status = str(config.get("status", "unverified")).lower()
        self.platform = str(config.get("platform", "shopify")).lower()
        self.currency = str(config["currency"]).upper()
        self.country = str(config["country"]).upper()
        self.landed_cost_basis = str(config["landed_cost_basis"]).upper()  # type: ignore[assignment]
        self.vat_treatment, self.local_vat_rate, _ = resolve_config_vat(self.name, config)
        self.purchase_fx_fee_rate = _require_rate(self.name, config, "purchase_fx_fee_rate", 0.0)
        self.domestic_shipping_jpy = float(config.get("domestic_shipping_jpy") or 0.0)
        # 省略時は BaseSource の既定値 (DHL 受取人払い 2,200 円 / 2%)
        handling_min = config.get("customs_handling_min_jpy")
        self.customs_handling_min_jpy = (
            float(handling_min) if handling_min is not None else BaseSource.customs_handling_min_jpy
        )
        self.customs_handling_rate = _require_rate(
            self.name, config, "customs_handling_rate", BaseSource.customs_handling_rate
        )
        self.products_json_url = str(config["products_json_url"])
        self.product_url_template = str(config["product_url_template"])
        self.request_delay_sec = float(config.get("request_delay_sec") or 1.0)
        self.notes = str(config.get("notes") or "")

        flat = config.get("shipping_flat_local")
        threshold = config.get("free_shipping_threshold_local")
        self.shipping_flat_local = float(flat) if flat is not None else None
        self.free_shipping_threshold_local = float(threshold) if threshold is not None else None

    @property
    def is_verified(self) -> bool:
        return self.status == "verified"

    def product_url(self, handle: str) -> str:
        """Shopify handle から商品ページ URL を組み立てる。"""
        if not handle:
            return ""
        return self.product_url_template.replace("{handle}", handle)

    def shipping_cost_local(self, sale_price: float) -> Optional[float]:
        """日本向け国際送料 (現地通貨)。設定が無ければ None (重量推定に fallback)。"""
        if self.shipping_flat_local is None:
            return None
        if (
            self.free_shipping_threshold_local is not None
            and sale_price >= self.free_shipping_threshold_local
        ):
            return 0.0
        return self.shipping_flat_local

    def fetch_products(self, limit: Optional[int] = None) -> Iterable[dict]:
        raise NotImplementedError(
            f"{self.name} の取得は scripts/shopify_sales_to_csv.py --source {self.name} を使用してください。"
        )

    def __repr__(self) -> str:  # pragma: no cover - デバッグ表示用
        return (
            f"ConfigSource(name={self.name!r}, currency={self.currency!r}, "
            f"landed_cost_basis={self.landed_cost_basis!r}, status={self.status!r})"
        )
