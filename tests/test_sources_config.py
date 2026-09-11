"""data/sources.json 設定ベースの仕入先 (ConfigSource) のユニットテスト。

設定ミスは原価計算 = 出品価格に直結するため、「壊れた設定は黙って通さない」
ことを重点的に検証する。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pricing import PricingParams  # noqa: E402
from app.core.sources import (  # noqa: E402
    BasebluSource,
    ConfigSource,
    ItalistSource,
    REGISTERED_SOURCES,
    get_source,
    known_source_names,
)
from app.core.sources.config_source import (  # noqa: E402
    DEFAULT_SOURCES_PATH,
    available_source_names,
    get_source_config,
    load_source_configs,
    validate_source_config,
)

VALID_CONFIG = {
    "display_name": "Example Boutique",
    "status": "unverified",
    "platform": "shopify",
    "products_json_url": "https://example.com/collections/sale/products.json",
    "product_url_template": "https://example.com/products/{handle}",
    "currency": "EUR",
    "country": "IT",
    "landed_cost_basis": "DDU",
    "vat_refund_rate": 0.167,
    "purchase_fx_fee_rate": 0.022,
    "domestic_shipping_jpy": 1000.0,
    "shipping_flat_local": 30.0,
    "free_shipping_threshold_local": 500.0,
    "request_delay_sec": 1.5,
    "notes": "テスト用",
}


def _write_config(sources: dict) -> Path:
    """一時ファイルに sources.json を書いてパスを返す。"""
    d = Path(tempfile.mkdtemp())
    path = d / "sources.json"
    path.write_text(json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8")
    return path


class ValidationTest(unittest.TestCase):
    """壊れた設定は ValueError で止まる。"""

    def test_valid_config_passes(self):
        validate_source_config("example", dict(VALID_CONFIG))  # 例外が出なければ OK

    def test_missing_required_key_raises(self):
        for key in ("products_json_url", "product_url_template", "currency",
                    "country", "landed_cost_basis"):
            cfg = dict(VALID_CONFIG)
            del cfg[key]
            with self.assertRaises(ValueError, msg=f"{key} 欠落が検出されない"):
                validate_source_config("example", cfg)

    def test_empty_required_value_raises(self):
        cfg = dict(VALID_CONFIG, currency="  ")
        with self.assertRaises(ValueError):
            validate_source_config("example", cfg)

    def test_invalid_landed_cost_basis_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_source_config("example", dict(VALID_CONFIG, landed_cost_basis="FOB"))
        self.assertIn("landed_cost_basis", str(ctx.exception))

    def test_landed_cost_basis_is_case_insensitive(self):
        validate_source_config("example", dict(VALID_CONFIG, landed_cost_basis="ddp"))

    def test_unsupported_platform_raises(self):
        with self.assertRaises(ValueError):
            validate_source_config("example", dict(VALID_CONFIG, platform="magento"))

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            validate_source_config("example", dict(VALID_CONFIG, status="maybe"))

    def test_product_url_template_without_handle_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_source_config("example", dict(VALID_CONFIG,
                                                   product_url_template="https://example.com/p/"))
        self.assertIn("handle", str(ctx.exception))

    def test_rate_out_of_range_raises(self):
        for field, bad in (("vat_refund_rate", 1.5), ("vat_refund_rate", -0.1),
                           ("purchase_fx_fee_rate", 2.0)):
            with self.assertRaises(ValueError, msg=f"{field}={bad} が検出されない"):
                validate_source_config("example", dict(VALID_CONFIG, **{field: bad}))

    def test_rate_as_percent_is_rejected(self):
        """16.7 (%) と 0.167 (率) の取り違えを検出する。"""
        with self.assertRaises(ValueError):
            validate_source_config("example", dict(VALID_CONFIG, vat_refund_rate=16.7))

    def test_non_numeric_rate_raises(self):
        with self.assertRaises(ValueError):
            validate_source_config("example", dict(VALID_CONFIG, vat_refund_rate="high"))

    def test_negative_shipping_raises(self):
        with self.assertRaises(ValueError):
            validate_source_config("example", dict(VALID_CONFIG, shipping_flat_local=-1))

    def test_null_shipping_allowed(self):
        validate_source_config("example", dict(VALID_CONFIG, shipping_flat_local=None,
                                               free_shipping_threshold_local=None))


class LoadConfigTest(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        path = Path(tempfile.mkdtemp()) / "nope.json"
        self.assertEqual(load_source_configs(path), {})

    def test_broken_json_raises(self):
        path = Path(tempfile.mkdtemp()) / "sources.json"
        path.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_source_configs(path)

    def test_missing_sources_key_raises(self):
        path = Path(tempfile.mkdtemp()) / "sources.json"
        path.write_text(json.dumps({"note": "x"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_source_configs(path)

    def test_invalid_entry_raises_with_source_name(self):
        path = _write_config({"broken": dict(VALID_CONFIG, landed_cost_basis="XX")})
        with self.assertRaises(ValueError) as ctx:
            load_source_configs(path)
        self.assertIn("broken", str(ctx.exception))

    def test_underscore_keys_are_ignored(self):
        path = _write_config({"_comment": "これは無視される", "example": dict(VALID_CONFIG)})
        self.assertEqual(set(load_source_configs(path)), {"example"})

    def test_names_are_lowercased(self):
        path = _write_config({"ExAmPle": dict(VALID_CONFIG)})
        self.assertIn("example", load_source_configs(path))

    def test_disabled_source_excluded_from_available_and_get(self):
        path = _write_config({
            "live": dict(VALID_CONFIG),
            "old": dict(VALID_CONFIG, status="disabled"),
        })
        self.assertEqual(available_source_names(path), ["live"])
        self.assertIsNotNone(get_source_config("live", path))
        self.assertIsNone(get_source_config("old", path))


class ConfigSourceTest(unittest.TestCase):
    def setUp(self):
        self.source = ConfigSource("example", dict(VALID_CONFIG))

    def test_metadata(self):
        self.assertEqual(self.source.name, "example")
        self.assertEqual(self.source.currency, "EUR")
        self.assertEqual(self.source.country, "IT")
        self.assertEqual(self.source.landed_cost_basis, "DDU")
        self.assertFalse(self.source.is_verified)

    def test_metadata_dict_matches_csv_columns(self):
        self.assertEqual(
            self.source.metadata_dict(),
            {"source_name": "example", "currency": "EUR", "landed_cost_basis": "DDU"},
        )

    def test_currency_and_basis_are_normalised_to_upper(self):
        s = ConfigSource("example", dict(VALID_CONFIG, currency="eur", landed_cost_basis="ddp"))
        self.assertEqual(s.currency, "EUR")
        self.assertEqual(s.landed_cost_basis, "DDP")

    def test_product_url(self):
        self.assertEqual(self.source.product_url("my-bag"), "https://example.com/products/my-bag")
        self.assertEqual(self.source.product_url(""), "")

    def test_shipping_below_threshold_is_flat(self):
        self.assertEqual(self.source.shipping_cost_local(100.0), 30.0)

    def test_shipping_at_or_above_threshold_is_free(self):
        self.assertEqual(self.source.shipping_cost_local(500.0), 0.0)
        self.assertEqual(self.source.shipping_cost_local(900.0), 0.0)

    def test_shipping_without_threshold_is_always_flat(self):
        s = ConfigSource("example", dict(VALID_CONFIG, free_shipping_threshold_local=None))
        self.assertEqual(s.shipping_cost_local(10_000.0), 30.0)

    def test_shipping_without_flat_falls_back_to_weight_model(self):
        s = ConfigSource("example", dict(VALID_CONFIG, shipping_flat_local=None))
        self.assertIsNone(s.shipping_cost_local(100.0))
        params = s.get_pricing_params(sale_price=100.0, category="bag")
        self.assertIsNone(params.shipping_jpy)   # None → calculate_pricing が重量推定

    def test_get_pricing_params_propagates_config(self):
        params = self.source.get_pricing_params(sale_price=200.0, category="bag")
        self.assertIsInstance(params, PricingParams)
        self.assertEqual(params.currency, "EUR")
        self.assertEqual(params.landed_cost_basis, "DDU")
        self.assertAlmostEqual(params.vat_refund_rate, 0.167)
        self.assertAlmostEqual(params.purchase_fx_fee_rate, 0.022)
        self.assertAlmostEqual(params.domestic_shipping_jpy, 1000.0)
        self.assertIsNotNone(params.shipping_jpy)   # 30 EUR を円換算した値

    def test_invalid_config_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            ConfigSource("example", dict(VALID_CONFIG, landed_cost_basis="FOB"))

    def test_fetch_products_points_to_script(self):
        with self.assertRaises(NotImplementedError) as ctx:
            list(self.source.fetch_products())
        self.assertIn("shopify_sales_to_csv.py", str(ctx.exception))


class GetSourceResolutionTest(unittest.TestCase):
    """解決順: 専用クラス → sources.json → baseblu フォールバック。"""

    def test_dedicated_class_wins(self):
        self.assertIsInstance(get_source("baseblu"), BasebluSource)
        self.assertIsInstance(get_source("italist"), ItalistSource)

    def test_config_source_resolved(self):
        s = get_source("antonioli")
        self.assertIsInstance(s, ConfigSource)
        self.assertEqual(s.name, "antonioli")

    def test_unknown_name_falls_back_to_baseblu(self):
        s = get_source("totally_unknown_shop")
        self.assertIsInstance(s, BasebluSource)
        self.assertEqual(s.name, "baseblu")

    def test_empty_name_falls_back_to_baseblu(self):
        self.assertEqual(get_source("").name, "baseblu")
        self.assertEqual(get_source(None).name, "baseblu")

    def test_case_insensitive(self):
        self.assertEqual(get_source("ANTONIOLI").name, "antonioli")

    def test_known_source_names_includes_both_kinds(self):
        names = known_source_names()
        self.assertIn("baseblu", names)
        self.assertIn("antonioli", names)


class RealConfigFileTest(unittest.TestCase):
    """リポジトリ同梱の data/sources.json が常に妥当であること。"""

    def setUp(self):
        self.configs = load_source_configs(DEFAULT_SOURCES_PATH, force_reload=True)

    def test_file_exists_and_has_entries(self):
        self.assertTrue(DEFAULT_SOURCES_PATH.exists())
        self.assertGreater(len(self.configs), 0)

    def test_every_entry_builds_a_source(self):
        for name, cfg in self.configs.items():
            source = ConfigSource(name, cfg)
            self.assertTrue(source.products_json_url.startswith("https://"),
                            f"{name}: products_json_url は https で始めること")
            self.assertTrue(source.product_url("x").startswith("https://"))

    def test_dedicated_classes_and_config_do_not_drift(self):
        """専用クラスと sources.json の両方にある仕入先は値が一致していること。

        二重管理による事故 (VAT 二重控除など) を防ぐためのガード。
        """
        for name, cls in REGISTERED_SOURCES.items():
            cfg = self.configs.get(name)
            if cfg is None:
                continue
            dedicated = cls()
            config_based = ConfigSource(name, cfg)
            for field in ("currency", "country", "landed_cost_basis",
                          "vat_refund_rate", "purchase_fx_fee_rate", "domestic_shipping_jpy"):
                self.assertEqual(
                    getattr(dedicated, field), getattr(config_based, field),
                    f"{name}.{field} が app/core/sources/{name}.py と data/sources.json で食い違っています",
                )
            for price in (10.0, 100.0, 900.0, 5000.0):
                self.assertEqual(
                    dedicated.shipping_cost_local(price),
                    config_based.shipping_cost_local(price),
                    f"{name}: 送料の計算結果が食い違っています (価格 {price})",
                )

    def test_unverified_sources_use_conservative_defaults(self):
        """未検証の仕入先は原価を高めに見積もる側に倒しておく。

        VAT 還付を仮定すると原価を過小評価し、赤字出品につながるため。
        """
        for name, cfg in self.configs.items():
            if str(cfg.get("status")).lower() != "unverified":
                continue
            self.assertEqual(
                float(cfg.get("vat_refund_rate", 0.0)), 0.0,
                f"{name}: 未検証のうちは vat_refund_rate=0.0 にすること",
            )

    def test_every_entry_has_notes(self):
        for name, cfg in self.configs.items():
            self.assertTrue(str(cfg.get("notes") or "").strip(),
                            f"{name}: notes に根拠・未確認事項を書くこと")


if __name__ == "__main__":
    unittest.main()
