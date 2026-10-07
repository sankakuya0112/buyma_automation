"""2026-10 の原価計算修正のテスト。

- 仕入先ごとの VAT の扱い (baseblu は VAT 抜き表示 → 控除 0、VAT 込み表示は rate/(1+rate))
- 為替: 手動指定 > ECB キャッシュ > 固定値、× 安全バッファ。計算関数は通信しない
- BUYMA 定額成約手数料 (55〜220 円) と振込手数料 385 円 (環境変数で変更可)
- 海外カード手数料は 商品代 + 国際送料 に掛かる
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import fx  # noqa: E402
from app.core.pricing import (  # noqa: E402
    BANK_TRANSFER_FEE_JPY,
    PricingParams,
    _solve_breakeven_price,
    bank_transfer_fee_jpy,
    buyma_fixed_fee_jpy,
    calculate_pricing,
    decide_final_price,
    resolve_exchange_rate,
    vat_extraction_rate,
)
from app.core.sources import BasebluSource, ConfigSource, get_source  # noqa: E402
from app.core.sources.base import resolve_vat_refund_rate  # noqa: E402
from app.core.sources.config_source import validate_source_config  # noqa: E402

ECB_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time='2026-10-06'>
      <Cube currency='USD' rate='1.1269'/>
      <Cube currency='JPY' rate='178.15'/>
      <Cube currency='GBP' rate='0.84880'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""

BASE_CFG = {
    "products_json_url": "https://example.com/collections/sale/products.json",
    "product_url_template": "https://example.com/products/{handle}",
    "currency": "EUR", "country": "IT", "landed_cost_basis": "DDU",
}


class VatTest(unittest.TestCase):
    def test_extraction_rate_for_22_percent(self):
        # €122 (VAT 込み) → €100: 控除率 0.22/1.22 = 0.1803。0.167 ではない
        self.assertAlmostEqual(vat_extraction_rate(0.22), 0.1803, places=4)
        self.assertAlmostEqual(122 * (1 - vat_extraction_rate(0.22)), 100.0, delta=0.01)
        self.assertEqual(vat_extraction_rate(0.0), 0.0)

    def test_baseblu_price_is_ex_vat(self):
        s = BasebluSource()
        self.assertEqual(s.vat_treatment, "none")
        self.assertEqual(s.vat_refund_rate, 0.0)
        r = calculate_pricing(s.get_pricing_params(sale_price=665.57, category="CLOTHING"))
        self.assertEqual(r.vat_refund_jpy, 0.0)

    def test_evidence_ratio(self):
        """IT 向け 812.00 EUR と en-us 665.57 EUR は 22% VAT の差 (根拠の数値を固定)。"""
        self.assertAlmostEqual(812.00 / 1.22, 665.57, places=2)

    def test_resolve_vat_refund_rate(self):
        self.assertEqual(resolve_vat_refund_rate("none", 0.22), 0.0)
        self.assertAlmostEqual(resolve_vat_refund_rate("deducted_at_checkout", 0.22), 0.1803, places=4)
        self.assertAlmostEqual(resolve_vat_refund_rate("deducted_at_checkout", 0.20), 0.1667, places=4)
        with self.assertRaises(ValueError):
            resolve_vat_refund_rate("deducted_at_checkout", 0.0)   # 率なしは止める
        with self.assertRaises(ValueError):
            resolve_vat_refund_rate("refund", 0.22)

    def test_config_vat_inclusive_source(self):
        src = ConfigSource("ex", dict(BASE_CFG, vat_treatment="deducted_at_checkout", local_vat_rate=0.22))
        self.assertAlmostEqual(src.vat_refund_rate, 0.1803, places=4)
        params = src.get_pricing_params(sale_price=122.0, category="bag")
        r = calculate_pricing(params)
        self.assertAlmostEqual(r.source_price_jpy - r.vat_refund_jpy, 100.0 * params.exchange_rate, delta=2.0)

    def test_config_defaults_to_no_deduction(self):
        self.assertEqual(ConfigSource("ex", dict(BASE_CFG)).vat_refund_rate, 0.0)

    def test_legacy_nonzero_vat_refund_rate_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_source_config("ex", dict(BASE_CFG, vat_refund_rate=0.167))
        self.assertIn("vat_treatment", str(ctx.exception))
        validate_source_config("ex", dict(BASE_CFG, vat_refund_rate=0.0))  # 0 は互換で許可

    def test_conflicting_legacy_rate_rejected(self):
        with self.assertRaises(ValueError):
            validate_source_config("ex", dict(BASE_CFG, vat_treatment="none", vat_refund_rate=0.1))

    def test_bad_local_vat_rate_rejected(self):
        for bad in (22, -0.1, "x"):
            with self.assertRaises(ValueError, msg=bad):
                validate_source_config("ex", dict(BASE_CFG, vat_treatment="deducted_at_checkout",
                                                  local_vat_rate=bad))

    def test_pricing_default_no_vat_deduction(self):
        self.assertEqual(PricingParams(source_price=100.0).vat_refund_rate, 0.0)


class FxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache = self.tmp / "fx.json"
        self.env = mock.patch.dict(os.environ, {"FX_CACHE_PATH": str(self.cache)}, clear=False)
        self.env.start()
        for k in ("EUR_TO_JPY", "USD_TO_JPY", "FX_BUFFER_PCT"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_parse_ecb_xml(self):
        d = fx.parse_ecb_daily_xml(ECB_SAMPLE)
        self.assertEqual(d["date"], "2026-10-06")
        self.assertAlmostEqual(d["jpy_per"]["EUR"], 178.15)
        self.assertAlmostEqual(d["jpy_per"]["USD"], 178.15 / 1.1269, places=3)
        self.assertAlmostEqual(d["jpy_per"]["GBP"], 178.15 / 0.8488, places=3)
        with self.assertRaises(ValueError):
            fx.parse_ecb_daily_xml("<xml/>")

    def test_default_when_no_cache(self):
        rate, origin = fx.base_rate_with_origin("EUR")
        self.assertEqual(origin, "default")
        self.assertEqual(rate, 186.0)

    def test_cache_used_and_buffer_applied(self):
        fx.save_cache({"date": date.today().isoformat(), "jpy_per": {"EUR": 178.15}})
        self.assertEqual(fx.base_rate("EUR"), 178.15)
        self.assertAlmostEqual(fx.effective_rate("EUR"), 178.15 * 1.03, places=3)  # 既定 3%

    def test_env_override_wins_over_cache(self):
        fx.save_cache({"date": date.today().isoformat(), "jpy_per": {"EUR": 178.15}})
        with mock.patch.dict(os.environ, {"EUR_TO_JPY": "170", "FX_BUFFER_PCT": "0"}):
            self.assertEqual(fx.base_rate_with_origin("EUR"), (170.0, "env"))
            self.assertEqual(fx.effective_rate("EUR"), 170.0)

    def test_buffer_parsing(self):
        for raw, expected in (("0.05", 0.05), ("5", 0.05), ("-1", 0.0), ("abc", 0.03), ("", 0.03)):
            with mock.patch.dict(os.environ, {"FX_BUFFER_PCT": raw}):
                self.assertAlmostEqual(fx.buffer_pct(), expected, msg=raw)

    def test_stale_cache_still_used(self):
        old = (date.today() - timedelta(days=30)).isoformat()
        fx.save_cache({"date": old, "jpy_per": {"EUR": 175.0}})
        self.assertEqual(fx.base_rate_with_origin("EUR"), (175.0, f"cache:{old}"))
        self.assertEqual(fx.cache_age_days(fx.load_cache()), 30)

    def test_jpy_is_one(self):
        self.assertEqual(fx.effective_rate("JPY"), 1.0)

    def test_unknown_currency_raises(self):
        with self.assertRaises(ValueError):
            fx.effective_rate("CHF")
        with self.assertRaises(ValueError):
            resolve_exchange_rate("CHF")   # 以前は 1.0 (原価ほぼ 0) を返していた

    def test_refresh_writes_cache(self):
        fake = mock.Mock(text=ECB_SAMPLE)
        fake.raise_for_status = mock.Mock()
        with mock.patch("requests.get", return_value=fake):
            res = fx.refresh_rates()
        self.assertTrue(res["ok"])
        self.assertEqual(json.loads(self.cache.read_text())["jpy_per"]["EUR"], 178.15)

    def test_refresh_failure_is_soft(self):
        with mock.patch("requests.get", side_effect=OSError("offline")):
            res = fx.refresh_rates()
        self.assertFalse(res["ok"])
        self.assertFalse(self.cache.exists())

    def test_source_params_use_effective_rate_for_goods_and_shipping(self):
        fx.save_cache({"date": date.today().isoformat(), "jpy_per": {"EUR": 178.15}})
        params = get_source("baseblu").get_pricing_params(sale_price=200.0, category="BAGS")
        self.assertAlmostEqual(params.exchange_rate, 178.15 * 1.03, places=3)
        self.assertAlmostEqual(params.shipping_jpy, 50.0 * params.exchange_rate, places=2)


class FeeTest(unittest.TestCase):
    def test_fixed_fee_tiers(self):
        cases = [(5000, 55), (9999, 55), (10000, 110), (19999, 110), (20000, 165),
                 (99999, 165), (100000, 220), (800000, 220)]
        for price, fee in cases:
            self.assertEqual(buyma_fixed_fee_jpy(price, True), fee, price)
        self.assertEqual(buyma_fixed_fee_jpy(50000, False), 0.0)

    def test_fixed_fee_env_toggle(self):
        with mock.patch.dict(os.environ, {"BUYMA_FIXED_FEE_ENABLED": "0"}):
            self.assertEqual(buyma_fixed_fee_jpy(50000), 0.0)
        with mock.patch.dict(os.environ, {"BUYMA_FIXED_FEE_ENABLED": "1"}):
            self.assertEqual(buyma_fixed_fee_jpy(50000), 165.0)

    def test_transfer_fee_default_and_override(self):
        self.assertEqual(BANK_TRANSFER_FEE_JPY, 385.0)
        with mock.patch.dict(os.environ, {"BUYMA_TRANSFER_FEE_JPY": "220"}):
            self.assertEqual(bank_transfer_fee_jpy(), 220.0)
            r = calculate_pricing(PricingParams(source_price=100.0, category="bag"))
            self.assertEqual(r.bank_transfer_fee_jpy, 220.0)
        os.environ.pop("BUYMA_TRANSFER_FEE_JPY", None)
        r = calculate_pricing(PricingParams(source_price=100.0, category="bag"))
        self.assertEqual(r.bank_transfer_fee_jpy, 385.0)

    def test_profit_includes_fixed_fee_and_target_margin_kept(self):
        p = PricingParams(source_price=300.0, category="bag", exchange_rate=180.0)
        r = calculate_pricing(p)
        self.assertEqual(r.buyma_fixed_fee_jpy, buyma_fixed_fee_jpy(r.selling_price_jpy, True))
        expected = r.selling_price_jpy * (1 - 0.077) - r.buyma_fixed_fee_jpy - r.total_cost_jpy
        self.assertAlmostEqual(r.profit_jpy, expected, places=1)
        self.assertGreaterEqual(r.margin_pct, 25.0)   # 定額手数料を引いても目標 25% を守る

    def test_fixed_fee_reduces_profit_vs_disabled(self):
        on = calculate_pricing(PricingParams(source_price=300.0, category="bag", exchange_rate=180.0,
                                             apply_fixed_fee=True))
        off = calculate_pricing(PricingParams(source_price=300.0, category="bag", exchange_rate=180.0,
                                              apply_fixed_fee=False))
        self.assertGreaterEqual(on.selling_price_jpy, off.selling_price_jpy)
        self.assertEqual(off.buyma_fixed_fee_jpy, 0.0)

    def test_breakeven_includes_fixed_fee(self):
        cost = 50000.0
        with_fee = _solve_breakeven_price(cost, 0.077, 0.0, category="BAGS", apply_fixed_fee=True)
        without = _solve_breakeven_price(cost, 0.077, 0.0, category="BAGS", apply_fixed_fee=False)
        self.assertGreaterEqual(with_fee, without)
        # breakeven で floor 利益 (¥8,000) が守られている
        profit = with_fee * (1 - 0.077) - buyma_fixed_fee_jpy(with_fee, True) - cost
        self.assertGreaterEqual(profit, 8000 - 1)

    def test_decision_profit_includes_fixed_fee(self):
        r = calculate_pricing(PricingParams(source_price=300.0, category="bag", exchange_rate=180.0))
        d = decide_final_price(r, market=None, category="BAGS")
        expected = d.final_price_jpy * (1 - 0.077) - buyma_fixed_fee_jpy(d.final_price_jpy, True) - r.total_cost_jpy
        self.assertAlmostEqual(d.expected_profit_jpy, round(expected), delta=1)

    def test_card_fee_includes_international_shipping(self):
        p = PricingParams(source_price=200.0, category="bag", exchange_rate=180.0,
                          shipping_jpy=50 * 180.0, purchase_fx_fee_rate=0.022)
        r = calculate_pricing(p)
        self.assertAlmostEqual(r.purchase_fx_fee_jpy, (200 + 50) * 180.0 * 0.022, places=2)


if __name__ == "__main__":
    unittest.main()
