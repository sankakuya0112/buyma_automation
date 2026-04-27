"""
app.governors.rules.GovernorRules のユニットテスト。

個別チェック (check_sku / check_price / check_category / check_brand /
check_images / check_profit_margin) と evaluate() の総合判定を検証する。

brands.json / categories.json は実ファイルではなく _load_json_set を
patch してテスト固有のセットを注入する (環境差を排除するため)。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models import Base, RankedProduct, SourceProduct
from app.governors import rules as rules_mod
from app.governors.rules import GovernorRules


def _fake_loader(filename: str):
    """テスト用の brands/categories セットを返すローダー。"""
    if filename == "brands.json":
        return {"gucci", "prada"}
    if filename == "categories.json":
        return {"bags", "clothing"}
    return set()


def _make_product(**overrides) -> SourceProduct:
    """正常系のデフォルト値で SourceProduct を作る。"""
    defaults = dict(
        source_name="baseblu",
        product_url="https://example.com/product/1",
        brand="gucci",
        title="Test Product",
        sku="ABC-123",
        category="BAGS",
        source_price=500.0,
        currency="EUR",
        shipping_cost=0.0,
        image_urls=["https://example.com/img1.jpg"],
        sub_images=[],
        description_en="A test product",
        stock_status="in_stock",
    )
    defaults.update(overrides)
    return SourceProduct(**defaults)


def _make_ranked(**overrides) -> RankedProduct:
    defaults = dict(
        source_product_id=1,
        est_profit_jpy=5000.0,
        est_margin_pct=25.0,
        competitor_count=0,
        lane="core",
        rank_score=80.0,
    )
    defaults.update(overrides)
    return RankedProduct(**defaults)


class TestGovernorIndividualChecks(unittest.TestCase):
    """個別チェックメソッドの正常系/異常系。"""

    def setUp(self):
        # in-memory DB
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        # _load_json_set をテスト用にスタブ
        self._patcher = patch.object(rules_mod, "_load_json_set", side_effect=_fake_loader)
        self._patcher.start()
        self.governor = GovernorRules(self.session)

    def tearDown(self):
        self._patcher.stop()
        self.session.close()
        self.engine.dispose()

    # ----- SKU -----
    def test_check_sku_present(self):
        product = _make_product(sku="SKU-001")
        ok, reason = self.governor.check_sku(product)
        self.assertTrue(ok)
        self.assertEqual(reason, "SKU OK")

    def test_check_sku_missing(self):
        product = _make_product(sku=None)
        ok, reason = self.governor.check_sku(product)
        self.assertFalse(ok)
        self.assertEqual(reason, "SKU missing")

    def test_check_sku_whitespace_only(self):
        """空白のみの SKU は missing 扱い。"""
        product = _make_product(sku="   ")
        ok, reason = self.governor.check_sku(product)
        self.assertFalse(ok)
        self.assertEqual(reason, "SKU missing")

    # ----- price -----
    def test_check_price_normal(self):
        product = _make_product(source_price=500.0)
        ok, reason = self.governor.check_price(product)
        self.assertTrue(ok)
        self.assertEqual(reason, "Price OK")

    def test_check_price_zero_or_negative(self):
        product = _make_product(source_price=0)
        ok, reason = self.governor.check_price(product)
        self.assertFalse(ok)
        self.assertIn("Abnormal price", reason)

        product2 = _make_product(source_price=-100)
        ok, reason = self.governor.check_price(product2)
        self.assertFalse(ok)
        self.assertIn("Abnormal price", reason)

    def test_check_price_too_high(self):
        product = _make_product(source_price=200_000)
        ok, reason = self.governor.check_price(product)
        self.assertFalse(ok)
        self.assertIn("Abnormal price", reason)

    # ----- category -----
    def test_check_category_known(self):
        """fake loader が返す 'bags' (lower) と一致する。"""
        product = _make_product(category="BAGS")
        ok, reason = self.governor.check_category(product)
        self.assertTrue(ok)
        self.assertEqual(reason, "Category OK")

    def test_check_category_unknown(self):
        product = _make_product(category="UNKNOWN_CAT")
        ok, reason = self.governor.check_category(product)
        self.assertFalse(ok)
        self.assertIn("Unknown category", reason)

    def test_check_category_missing(self):
        product = _make_product(category=None)
        ok, reason = self.governor.check_category(product)
        self.assertFalse(ok)
        self.assertEqual(reason, "Category missing")

    # ----- brand -----
    def test_check_brand_known(self):
        product = _make_product(brand="gucci")
        ok, reason = self.governor.check_brand(product)
        self.assertTrue(ok)
        self.assertEqual(reason, "Brand OK")

    def test_check_brand_case_insensitive(self):
        """大文字でも (lower 比較で) 一致する。"""
        product = _make_product(brand="GUCCI")
        ok, reason = self.governor.check_brand(product)
        self.assertTrue(ok)

    def test_check_brand_unknown(self):
        product = _make_product(brand="non-existent-brand")
        ok, reason = self.governor.check_brand(product)
        self.assertFalse(ok)
        self.assertIn("Unknown brand", reason)

    # ----- images -----
    def test_check_images_present(self):
        product = _make_product(image_urls=["a.jpg", "b.jpg"])
        ok, reason = self.governor.check_images(product)
        self.assertTrue(ok)
        self.assertIn("2 found", reason)

    def test_check_images_empty(self):
        product = _make_product(image_urls=[])
        ok, reason = self.governor.check_images(product)
        self.assertFalse(ok)
        self.assertEqual(reason, "No images")

    # ----- profit margin -----
    def test_check_profit_margin_normal(self):
        ranked = _make_ranked(est_margin_pct=25.0)
        ok, reason = self.governor.check_profit_margin(ranked)
        self.assertTrue(ok)
        self.assertEqual(reason, "Margin OK")

    def test_check_profit_margin_too_high(self):
        ranked = _make_ranked(est_margin_pct=85.0)
        ok, reason = self.governor.check_profit_margin(ranked)
        self.assertFalse(ok)
        self.assertIn("Suspiciously high margin", reason)


class TestGovernorEvaluate(unittest.TestCase):
    """evaluate() の総合判定。"""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        self._patcher = patch.object(rules_mod, "_load_json_set", side_effect=_fake_loader)
        self._patcher.start()
        self.governor = GovernorRules(self.session)

    def tearDown(self):
        self._patcher.stop()
        self.session.close()
        self.engine.dispose()

    def test_all_pass_returns_approved(self):
        product = _make_product()
        ranked = _make_ranked()
        decision, reason = self.governor.evaluate(product, ranked)
        self.assertEqual(decision, "approved")
        self.assertEqual(reason, "All checks passed")

    def test_one_failure_returns_reject(self):
        product = _make_product(sku=None)  # SKU missing
        ranked = _make_ranked()
        decision, reason = self.governor.evaluate(product, ranked)
        self.assertEqual(decision, "reject")
        self.assertIn("SKU missing", reason)

    def test_multiple_failures_concatenated(self):
        """複数の失敗理由が "; " で連結される。"""
        product = _make_product(sku=None, brand="unknown_brand", image_urls=[])
        ranked = _make_ranked()
        decision, reason = self.governor.evaluate(product, ranked)
        self.assertEqual(decision, "reject")
        self.assertIn("SKU missing", reason)
        self.assertIn("No images", reason)
        self.assertIn(";", reason)


if __name__ == "__main__":
    unittest.main()
