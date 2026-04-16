"""
app.guard.stock_monitor のユニットテスト。

実際の BaseBlu へのネットワークアクセスはモックする。
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.models import (
    Base,
    InventoryCheck,
    Listing,
    ListingEvent,
    RankedProduct,
    SourceProduct,
)
from app.guard.stock_monitor import StockCheckResult, StockMonitor


def _make_shopify_response(variants_available: list[bool], prices: list[str] = None):
    """Shopify product.json のモックレスポンスを生成する。"""
    if prices is None:
        prices = ["100.00"] * len(variants_available)
    variants = []
    for i, (avail, price) in enumerate(zip(variants_available, prices)):
        variants.append(
            {
                "id": 1000 + i,
                "available": avail,
                "price": price,
                "option1": f"Size {i}",
            }
        )
    return {"product": {"variants": variants}}


class TestStockMonitor(unittest.TestCase):
    """StockMonitor の在庫判定ロジックのテスト。"""

    def setUp(self):
        self.monitor = StockMonitor()

    @patch("app.guard.stock_monitor.requests.get")
    def test_baseblu_all_available(self, mock_get):
        """全 variant が available な場合、True を返す。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_shopify_response(
            [True, True, True], ["100.00", "90.00", "110.00"]
        )
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        available, price = self.monitor._check_baseblu(
            "https://www.baseblu.com/en-us/products/test-product"
        )
        self.assertTrue(available)
        self.assertAlmostEqual(price, 90.0)

    @patch("app.guard.stock_monitor.requests.get")
    def test_baseblu_all_sold_out(self, mock_get):
        """全 variant が sold out の場合、False を返す。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_shopify_response([False, False, False])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        available, price = self.monitor._check_baseblu(
            "https://www.baseblu.com/en-us/products/test-product"
        )
        self.assertFalse(available)
        self.assertIsNone(price)

    @patch("app.guard.stock_monitor.requests.get")
    def test_baseblu_partial_available(self, mock_get):
        """一部 variant のみ available の場合、True を返す。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_shopify_response(
            [False, True, False], ["100.00", "150.00", "200.00"]
        )
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        available, price = self.monitor._check_baseblu(
            "https://www.baseblu.com/en-us/products/test-product"
        )
        self.assertTrue(available)
        self.assertAlmostEqual(price, 150.0)

    @patch("app.guard.stock_monitor.requests.get")
    def test_baseblu_empty_variants(self, mock_get):
        """variants が空の場合、False を返す。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"product": {"variants": []}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        available, price = self.monitor._check_baseblu(
            "https://www.baseblu.com/en-us/products/test-product"
        )
        self.assertFalse(available)

    @patch("app.guard.stock_monitor.requests.get")
    def test_baseblu_json_url_construction(self, mock_get):
        """product URL に .json を付加して呼ぶことを確認。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_shopify_response([True])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        self.monitor._check_baseblu(
            "https://www.baseblu.com/en-us/products/gucci-bag"
        )
        called_url = mock_get.call_args[0][0]
        self.assertEqual(
            called_url,
            "https://www.baseblu.com/en-us/products/gucci-bag.json",
        )

    @patch("app.guard.stock_monitor.requests.get")
    def test_network_error_raises(self, mock_get):
        """ネットワークエラー時は例外が伝播する。"""
        import requests as req

        mock_get.side_effect = req.exceptions.ConnectionError("Network error")
        with self.assertRaises(req.exceptions.ConnectionError):
            self.monitor._check_baseblu("https://www.baseblu.com/en-us/products/test")


class TestStockCheckResult(unittest.TestCase):
    def test_basic_creation(self):
        r = StockCheckResult(listing_id=1, available=True, current_price=99.0)
        self.assertEqual(r.listing_id, 1)
        self.assertTrue(r.available)
        self.assertAlmostEqual(r.current_price, 99.0)
        self.assertIsNone(r.error)

    def test_error_result(self):
        r = StockCheckResult(listing_id=2, available=False, error="timeout")
        self.assertFalse(r.available)
        self.assertEqual(r.error, "timeout")


class TestStopAndRelistLogic(unittest.TestCase):
    """_stop / _relist のロジックテスト（DB なしのモック版）。"""

    def setUp(self):
        self.monitor = StockMonitor()

    def test_stop_changes_status(self):
        listing = MagicMock()
        listing.id = 1
        listing.listing_status = "published"
        listing.title = "Test Product"
        session = MagicMock()

        self.monitor._stop(session, listing)

        self.assertEqual(listing.listing_status, "stopped")
        self.assertIsNotNone(listing.stopped_at)
        session.add.assert_called_once()
        event = session.add.call_args[0][0]
        self.assertIsInstance(event, ListingEvent)
        self.assertEqual(event.event_type, "stopped")

    def test_relist_changes_status(self):
        listing = MagicMock()
        listing.id = 2
        listing.listing_status = "stopped"
        listing.title = "Test Product"
        session = MagicMock()

        self.monitor._relist(session, listing, 95.0)

        self.assertEqual(listing.listing_status, "published")
        self.assertIsNotNone(listing.relisted_at)
        session.add.assert_called_once()
        event = session.add.call_args[0][0]
        self.assertIsInstance(event, ListingEvent)
        self.assertEqual(event.event_type, "relisted")


if __name__ == "__main__":
    unittest.main()
