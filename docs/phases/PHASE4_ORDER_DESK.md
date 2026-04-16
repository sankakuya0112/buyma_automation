# PHASE4: Order Desk（受注管理・買付フロー）

## 概要

BUYMA で注文が入った際の一連の処理を自動化します。ただし **購入の最終承認は必ず人間が行います**。

フロー：
1. **Order Fetcher**: BUYMA から新規注文を検出
2. **Profitability Recheck**: 注文時点での在庫確認・利益再計算
3. **Cart Builder**: 仕入れ先サイトのカートに商品を入れる（チェックアウトは NOT 実施）
4. **Human Review Queue**: 人間が確認・承認・保留・却下を判断
5. **Proceed**: 承認後、人間が手動でチェックアウト

**CRITICAL**: 支払い・購入は自動化禁止。人間が必ず確認・実行すること。

**完了条件**: `app/order_desk/` ディレクトリ下に4つのモジュールが完成し、人間レビューのワークフローが機能すること。

---

## タスク4-1: 注文検出モジュール（app/order_desk/order_fetcher.py）

### 実施内容

BUYMA のマイページから新規注文を検出し、orders テーブルに記録します。

```python
# app/order_desk/order_fetcher.py

import logging
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright, Page
from app.core.models import Order, Listing, RankedProduct, OrderStatusEnum
from app.core.config import get_config
from app.listing.buyma_client import BUYMAClient

logger = logging.getLogger(__name__)

class OrderFetcher:
    """
    BUYMA マイページから新規注文を検出。
    orders テーブルに記録。
    """
    
    def __init__(self):
        self.config = get_config()
    
    def fetch_new_orders(self, session: Session) -> List[Dict]:
        """
        BUYMA から新規注文を取得。
        
        Returns:
            List[{
                'buyma_order_id': str,
                'listing_id': int,
                'ordered_at': datetime,
                'buyer_name': str,
                'buyer_address': str,
            }]
        """
        new_orders = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                client = BUYMAClient(page)
                client.login()
                
                # BUYMA マイページ → 注文管理
                page.goto("https://buyma.jp/mypage/order")
                page.wait_for_load_state("networkidle")
                
                # 新規注文一覧を取得
                order_elements = page.locator("[data-order-item]").all()
                
                for element in order_elements:
                    try:
                        order_data = self._extract_order_data(session, page, element)
                        if order_data:
                            new_orders.append(order_data)
                    except Exception as e:
                        logger.warning(f"Failed to extract order: {e}")
                        continue
                
                logger.info(f"Fetched {len(new_orders)} new orders")
            finally:
                browser.close()
        
        return new_orders
    
    def _extract_order_data(self, session: Session, page: Page, element) -> Dict:
        """
        注文要素から情報を抽出。
        """
        try:
            # 注文ID
            buyma_order_id = element.locator("[data-order-id]").get_attribute("data-order-id")
            
            # BUYMA item ID を抽出
            item_id = element.locator("[data-item-id]").get_attribute("data-item-id")
            
            # 対応する Listing を取得
            listing = session.query(Listing).filter(
                Listing.buyma_item_id == item_id
            ).first()
            
            if not listing:
                logger.warning(f"Listing not found for item {item_id}")
                return None
            
            # 注文日時
            ordered_at_text = element.locator("[data-ordered-at]").inner_text()
            ordered_at = datetime.fromisoformat(ordered_at_text)
            
            # 購入者情報
            buyer_name = element.locator("[data-buyer-name]").inner_text() or ""
            buyer_address = element.locator("[data-buyer-address]").inner_text() or ""
            
            return {
                'buyma_order_id': buyma_order_id,
                'listing_id': listing.id,
                'ordered_at': ordered_at,
                'buyer_name': buyer_name,
                'buyer_address': buyer_address,
            }
        except Exception as e:
            logger.error(f"Failed to extract order data: {e}")
            return None
    
    def save_orders(self, session: Session, order_data_list: List[Dict]) -> int:
        """
        取得した注文を orders テーブルに保存。
        既存注文は無視。
        
        Returns:
            新規保存した件数
        """
        saved_count = 0
        
        for data in order_data_list:
            # 既存注文チェック
            existing = session.query(Order).filter(
                Order.buyma_order_id == data['buyma_order_id']
            ).first()
            
            if existing:
                logger.info(f"Order {data['buyma_order_id']} already exists")
                continue
            
            # 新規作成
            listing = session.query(Listing).get(data['listing_id'])
            ranked = listing.ranked_product
            
            order = Order(
                buyma_order_id=data['buyma_order_id'],
                ranked_product_id=ranked.id,
                listing_id=data['listing_id'],
                ordered_at=data['ordered_at'],
                order_status=OrderStatusEnum.awaiting_confirmation.value,
            )
            session.add(order)
            saved_count += 1
            
            logger.info(f"Saved new order: {data['buyma_order_id']}")
        
        session.commit()
        return saved_count
    
    def run(self, session: Session) -> int:
        """
        注文検出 → 保存の一括実行。
        """
        orders = self.fetch_new_orders(session)
        count = self.save_orders(session, orders)
        return count
```

### 納品物チェックリスト

- [ ] `app/order_desk/order_fetcher.py` が作成されている
- [ ] OrderFetcher クラスに fetch_new_orders() メソッドが実装
- [ ] _extract_order_data() で注文情報を抽出
- [ ] save_orders() で orders テーブルに保存
- [ ] run() で一括実行可能

---

## タスク4-2: 利益再計算モジュール（app/order_desk/profitability_recheck.py）

### 実施内容

注文時点での為替レート・仕入れ先価格を再確認し、利益を再計算します。

```python
# app/order_desk/profitability_recheck.py

import logging
from datetime import datetime
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from app.core.models import Order, SourceProduct, InventoryCheck
from app.utils.currency import currency
from app.guards.stock_monitor import StockMonitor

logger = logging.getLogger(__name__)

class ProfitabilityRecheck:
    """
    注文時点での利益を再計算。
    - 現在の為替レート取得
    - 仕入れ先での在庫・価格を確認
    - 利益が負になっていないかチェック
    """
    
    def __init__(self):
        self.stock_monitor = StockMonitor()
    
    def recheck_order(self, session: Session, order_id: int) -> Tuple[bool, Optional[float]]:
        """
        1件の注文について利益再計算を実施。
        
        Args:
            session: DB セッション
            order_id: 再確認対象の order ID
        
        Returns:
            (stock_available: bool, recalculated_profit: float or None)
        """
        order = session.query(Order).get(order_id)
        listing = order.listing
        ranked = listing.ranked_product
        product = ranked.source_product
        
        logger.info(f"Rechecking order {order.buyma_order_id}: {product.title}")
        
        # Step 1: 在庫確認
        try:
            stock_available, _ = self.stock_monitor.check_stock(session, listing.id)
            order.rechecked_stock = True
        except Exception as e:
            logger.error(f"Stock recheck failed: {e}")
            stock_available = False
            order.rechecked_stock = False
        
        if not stock_available:
            logger.warning(f"Stock unavailable for order {order.buyma_order_id}")
            session.commit()
            return False, None
        
        # Step 2: 利益再計算
        try:
            # 現在の為替レート取得
            current_rate = currency.get_rate(product.currency, "JPY")
            
            # 直近の InventoryCheck から現在価格を取得
            latest_check = session.query(InventoryCheck).filter(
                InventoryCheck.source_product_id == product.id
            ).order_by(InventoryCheck.checked_at.desc()).first()
            
            current_source_price = latest_check.price_at_check if latest_check else product.source_price
            
            # 利益再計算（簡略版）
            # 実際の計算ロジックは filter_baseblu_profitable.py を参照
            buyma_price_jpy = listing.listing_price_jpy
            cost_in_jpy = current_source_price * current_rate
            
            # 手数料等を考慮（暫定値）
            buyma_fee_rate = 0.1  # 10%
            buyma_fee = buyma_price_jpy * buyma_fee_rate
            
            recalculated_profit = buyma_price_jpy - cost_in_jpy - buyma_fee
            recalculated_margin = (recalculated_profit / buyma_price_jpy) * 100
            
            order.rechecked_profit_jpy = recalculated_profit
            order.rechecked_margin_pct = recalculated_margin
            session.commit()
            
            logger.info(
                f"Profit recalculated: ¥{recalculated_profit:.0f} "
                f"(margin: {recalculated_margin:.1f}%)"
            )
            
            return True, recalculated_profit
        except Exception as e:
            logger.error(f"Profit recalculation failed: {e}")
            return False, None
    
    def recheck_all_pending(self, session: Session) -> dict:
        """
        awaiting_confirmation 状態の全注文について利益再計算。
        
        Returns:
            {
                'total': 確認件数,
                'stock_ok': 在庫ありの件数,
                'stock_ng': 在庫なしの件数,
            }
        """
        from app.core.models import OrderStatusEnum
        
        pending_orders = session.query(Order).filter(
            Order.order_status == OrderStatusEnum.awaiting_confirmation.value
        ).all()
        
        results = {
            'total': len(pending_orders),
            'stock_ok': 0,
            'stock_ng': 0,
        }
        
        for order in pending_orders:
            stock_ok, profit = self.recheck_order(session, order.id)
            if stock_ok:
                results['stock_ok'] += 1
            else:
                results['stock_ng'] += 1
        
        logger.info(f"Recheck completed: {results}")
        return results
```

### 納品物チェックリスト

- [ ] `app/order_desk/profitability_recheck.py` が作成されている
- [ ] ProfitabilityRecheck クラスに recheck_order() メソッドが実装
- [ ] 在庫確認と利益再計算を実施
- [ ] 為替レートを取得して計算
- [ ] recheck_all_pending() で全pending注文を処理

---

## タスク4-3: カート構築モジュール（app/order_desk/cart_builder.py）

### 実施内容

仕入れ先サイトへアクセスし、カートに商品を入れます。**チェックアウトは実施しない**。

```python
# app/order_desk/cart_builder.py

import logging
from datetime import datetime
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright, Page
from app.core.models import Order, CartQueue
from app.core.config import get_config

logger = logging.getLogger(__name__)

class CartBuilder:
    """
    仕入れ先のカートに商品を入れる。
    チェックアウト・支払いは人間が実施する。
    """
    
    def __init__(self):
        self.config = get_config()
    
    def add_to_cart(self, session: Session, order_id: int) -> Tuple[bool, Optional[str]]:
        """
        1件の注文について、仕入れ先のカートに追加。
        
        Args:
            session: DB セッション
            order_id: 対象 order ID
        
        Returns:
            (success: bool, cart_url: str or None)
        """
        order = session.query(Order).get(order_id)
        product = order.ranked_product.source_product
        url = product.product_url
        
        logger.info(f"Adding to cart: {product.title}")
        logger.warning("REMINDER: Cart addition is NOT purchase. Human must confirm checkout.")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                # 商品ページへアクセス
                page.goto(url, timeout=self.config.timeout_seconds * 1000)
                page.wait_for_load_state("networkidle")
                
                # カートに追加
                # サイト固有のロジックが必要（例：サイズ選択等）
                add_to_cart_button = page.locator("button:has-text('Add to Cart')")
                add_to_cart_button.click()
                page.wait_for_load_state("networkidle")
                
                # サイズ・色が必須の場合は選択
                self._select_variant(page, product)
                
                # 最終確認ボタンをクリック
                final_add_button = page.locator("button:has-text('Add to Bag')")
                if final_add_button.is_visible():
                    final_add_button.click()
                    page.wait_for_load_state("networkidle")
                
                # カートページへ移動
                cart_url = page.goto("https://www.baseblu.com/cart")  # 例
                
                # CartQueue に記録
                cart_queue = CartQueue(
                    order_id=order.id,
                    source_url=url,
                    cart_status="pending",
                    human_review_status="awaiting_review",
                )
                session.add(cart_queue)
                session.commit()
                
                logger.info(f"Added to cart: {product.title}")
                return True, cart_url
            except Exception as e:
                logger.error(f"Failed to add to cart: {e}")
                return False, None
            finally:
                browser.close()
    
    def _select_variant(self, page: Page, product) -> None:
        """
        商品のバリアント（サイズ・色）を選択。
        """
        try:
            # 例：サイズ選択
            if product.color:
                color_selector = page.locator(f"select:has-text('{product.color}')")
                color_selector.click()
            
            logger.debug("Variant selected")
        except Exception as e:
            logger.warning(f"Variant selection failed: {e}")
    
    def add_all_pending(self, session: Session) -> dict:
        """
        human_review_status="approved" の全注文のカートに追加。
        
        Returns:
            {
                'total': 対象件数,
                'success': 成功件数,
                'failed': 失敗件数,
            }
        """
        pending_carts = session.query(CartQueue).filter(
            CartQueue.human_review_status == "approved",
            CartQueue.cart_status == "pending"
        ).all()
        
        results = {
            'total': len(pending_carts),
            'success': 0,
            'failed': 0,
        }
        
        for cart in pending_carts:
            success, _ = self.add_to_cart(session, cart.order_id)
            if success:
                results['success'] += 1
                cart.cart_status = "ready_for_checkout"
            else:
                results['failed'] += 1
            session.commit()
        
        logger.info(f"Add to cart completed: {results}")
        return results
```

### 納品物チェックリスト

- [ ] `app/order_desk/cart_builder.py` が作成されている
- [ ] CartBuilder クラスに add_to_cart() メソッドが実装
- [ ] _select_variant() でサイズ・色を選択
- [ ] CartQueue レコードを作成
- [ ] add_all_pending() で approved のカートをまとめて追加

---

## タスク4-4: 人間レビューキュー（app/order_desk/human_review_queue.py）

### 実施内容

注文の詳細をまとめたレビューチェックリストを生成し、人間が承認・保留・却下を判断します。

```python
# app/order_desk/human_review_queue.py

import logging
from datetime import datetime
from typing import List, Dict
from sqlalchemy.orm import Session
from app.core.models import Order, OrderStatusEnum, CartQueue
import json

logger = logging.getLogger(__name__)

class HumanReviewQueue:
    """
    注文のレビューキュー生成。
    人間が確認・判断するための詳細情報を整理。
    """
    
    def generate_review_checklist(self, session: Session, order_id: int) -> Dict:
        """
        1件の注文について、レビュー用チェックリストを生成。
        
        Returns:
            {
                'order_id': int,
                'buyma_order_id': str,
                'product': {...},
                'listing': {...},
                'profitability': {...},
                'stock_check': {...},
                'review_items': [...],
                'recommendation': str,
            }
        """
        order = session.query(Order).get(order_id)
        listing = order.listing
        ranked = listing.ranked_product
        product = ranked.source_product
        
        checklist = {
            'order_id': order.id,
            'buyma_order_id': order.buyma_order_id,
            'ordered_at': order.ordered_at.isoformat(),
            
            # 商品情報
            'product': {
                'brand': product.brand,
                'title': product.title,
                'sku': product.sku,
                'color': product.color,
                'source_price_original': product.source_price,
                'source_url': product.product_url,
            },
            
            # BUYMA出品情報
            'listing': {
                'listing_price_jpy': listing.listing_price_jpy,
                'title': listing.title,
                'buyma_item_id': listing.buyma_item_id,
            },
            
            # 利益情報
            'profitability': {
                'est_profit_jpy_original': ranked.est_profit_jpy,
                'est_margin_pct_original': ranked.est_margin_pct,
                'rechecked_profit_jpy': order.rechecked_profit_jpy,
                'rechecked_margin_pct': order.rechecked_margin_pct,
            },
            
            # 在庫確認
            'stock_check': {
                'rechecked_at': order.ordered_at.isoformat(),
                'stock_available': order.rechecked_stock,
                'notes': order.human_notes or "No notes",
            },
            
            # レビュー項目
            'review_items': [
                {
                    'item': '在庫確認',
                    'status': 'OK' if order.rechecked_stock else 'NG',
                    'action': '在庫がある場合のみ進行',
                },
                {
                    'item': '利益確認',
                    'status': 'OK' if order.rechecked_profit_jpy >= 0 else 'NG',
                    'action': '利益が負の場合は却下',
                },
                {
                    'item': '価格妥当性',
                    'status': 'PENDING',
                    'action': '仕入れ先との価格ズレを確認',
                },
                {
                    'item': '購入者情報',
                    'status': 'PENDING',
                    'action': '詐欺リスク等をチェック',
                },
            ],
            
            # 推奨判定
            'recommendation': self._generate_recommendation(order),
        }
        
        return checklist
    
    def _generate_recommendation(self, order: Order) -> str:
        """
        注文の自動推奨判定。
        人間の最終判定を支援。
        """
        if not order.rechecked_stock:
            return "REJECT: Stock unavailable"
        
        if order.rechecked_profit_jpy is not None and order.rechecked_profit_jpy < 0:
            return "REJECT: Negative profit"
        
        if order.rechecked_margin_pct is not None and order.rechecked_margin_pct < 10:
            return "HOLD: Low margin - requires human decision"
        
        return "APPROVE: Meets all criteria"
    
    def generate_queue_report(self, session: Session) -> List[Dict]:
        """
        awaiting_confirmation 状態の全注文について、
        レビューチェックリストを一括生成。
        
        Returns:
            List[{review_checklist_dict}, ...]
        """
        pending_orders = session.query(Order).filter(
            Order.order_status == OrderStatusEnum.awaiting_confirmation.value
        ).all()
        
        report = []
        for order in pending_orders:
            checklist = self.generate_review_checklist(session, order.id)
            report.append(checklist)
        
        logger.info(f"Generated review queue for {len(report)} orders")
        return report
    
    def save_review_decision(self, session: Session, order_id: int,
                            decision: str, notes: str = "") -> bool:
        """
        人間のレビュー決定を保存。
        
        Args:
            session: DB セッション
            order_id: 注文ID
            decision: "approved" / "hold" / "rejected"
            notes: 人間のコメント
        
        Returns:
            成功 True
        """
        order = session.query(Order).get(order_id)
        
        if decision not in ["approved", "hold", "rejected"]:
            logger.error(f"Invalid decision: {decision}")
            return False
        
        # 決定を保存
        order.human_decision = decision
        order.human_notes = notes
        order.human_reviewed_at = datetime.utcnow()
        
        # order_status を更新
        if decision == "approved":
            order.order_status = OrderStatusEnum.approved.value
            
            # CartQueue を作成（カート追加待ち）
            cart_queue = CartQueue(
                order_id=order.id,
                source_url=order.ranked_product.source_product.product_url,
                human_review_status="approved",
            )
            session.add(cart_queue)
        elif decision == "rejected":
            order.order_status = OrderStatusEnum.rejected.value
        else:  # hold
            order.order_status = OrderStatusEnum.awaiting_confirmation.value
        
        session.commit()
        logger.info(f"Order {order.buyma_order_id}: {decision} - {notes}")
        return True
    
    def export_queue_to_json(self, session: Session, output_file: str = "order_review_queue.json") -> None:
        """
        レビューキューを JSON ファイルに出力。
        人間が確認しやすい形式。
        """
        report = self.generate_queue_report(session)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Review queue exported to {output_file}")
```

### 納品物チェックリスト

- [ ] `app/order_desk/human_review_queue.py` が作成されている
- [ ] HumanReviewQueue クラスに generate_review_checklist() メソッドが実装
- [ ] _generate_recommendation() で自動推奨判定を生成
- [ ] generate_queue_report() で全pending注文のレビュー一覧を生成
- [ ] save_review_decision() で人間の判定を保存
- [ ] export_queue_to_json() で JSON 出力

---

## タスク4-5: Order Desk メインスクリプト（scripts/run_order_desk.py）

### 実施内容

Order Desk のすべての処理を統合するメインスクリプト。

```python
# scripts/run_order_desk.py

#!/usr/bin/env python3
"""
Order Desk 実行スクリプト。
注文検出 → 利益再計算 → カート構築 → 人間レビュー

Usage:
    python3 scripts/run_order_desk.py [OPTIONS]

Options:
    --review    : レビューキューを生成・エクスポート
    --add-cart  : 承認済みの注文をカートに追加
"""

import sys
import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_config
from app.core.logger import setup_logger
from app.core.models import Base
from app.order_desk.order_fetcher import OrderFetcher
from app.order_desk.profitability_recheck import ProfitabilityRecheck
from app.order_desk.cart_builder import CartBuilder
from app.order_desk.human_review_queue import HumanReviewQueue

logger = setup_logger("run_order_desk")

def main():
    parser = argparse.ArgumentParser(description="Order Desk workflow")
    parser.add_argument("--review", action="store_true", help="Generate review queue")
    parser.add_argument("--add-cart", action="store_true", help="Add approved orders to cart")
    
    args = parser.parse_args()
    
    logger.info("=== Order Desk started ===")
    
    # DB 初期化
    config = get_config()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    
    try:
        # Step 1: 注文検出
        logger.info("Step 1: Fetching new orders...")
        fetcher = OrderFetcher()
        new_order_count = fetcher.run(session)
        logger.info(f"Fetched {new_order_count} new orders")
        
        # Step 2: 利益再計算
        logger.info("Step 2: Rechecking profitability...")
        recheck = ProfitabilityRecheck()
        recheck_results = recheck.recheck_all_pending(session)
        logger.info(f"Recheck results: {recheck_results}")
        
        # Step 3: レビューキュー生成（オプション）
        if args.review:
            logger.info("Step 3: Generating review queue...")
            review_queue = HumanReviewQueue()
            review_queue.export_queue_to_json(session)
            logger.info("Review queue exported to order_review_queue.json")
            logger.warning("HUMAN ACTION REQUIRED: Review order_review_queue.json and make decisions")
        
        # Step 4: カート追加（オプション）
        if args.add_cart:
            logger.info("Step 4: Adding approved orders to cart...")
            cart_builder = CartBuilder()
            cart_results = cart_builder.add_all_pending(session)
            logger.info(f"Cart addition results: {cart_results}")
            logger.warning("HUMAN ACTION REQUIRED: Review cart and proceed to checkout")
        
        logger.info("=== Order Desk completed ===")
    finally:
        session.close()

if __name__ == "__main__":
    main()
```

### 実行例

```bash
# Step 1-2: 注文検出 & 利益再計算
python3 scripts/run_order_desk.py

# Step 3: レビューキュー生成
python3 scripts/run_order_desk.py --review

# 人間が order_review_queue.json で承認/却下を判定
# （スクリプトで自動判定するのではなく、手動ファイル編集）

# Step 4: 承認済み注文をカートに追加
python3 scripts/run_order_desk.py --add-cart

# 人間がブラウザで確認 & チェックアウト実行
```

### 納品物チェックリスト

- [ ] `scripts/run_order_desk.py` が作成されている
- [ ] 4つのモジュール（fetcher, recheck, cart_builder, review_queue）を統合
- [ ] --review, --add-cart オプションが実装
- [ ] 人間の判定を待つフローが設計されている

---

## ワークフローのまとめ

```
BUYMA注文発生
    ↓
[自動] Step 1: OrderFetcher が注文検出 → orders テーブルに記録
    ↓
[自動] Step 2: ProfitabilityRecheck が在庫・利益を再計算
    ↓
[自動] Step 3: HumanReviewQueue が order_review_queue.json を生成
    ↓
[人間] レビューキューを確認 → 承認/却下をファイルに記載 → スクリプト実行
    ↓
[自動] Step 4: CartBuilder がカートに追加 → CartQueue.cart_status = "ready_for_checkout"
    ↓
[人間] ブラウザでカートを確認 → チェックアウト実行 → 支払い完了
```

---

## ディレクトリ構成の更新

PHASE4 完了後：

```
app/
├── order_desk/
│   ├── __init__.py
│   ├── order_fetcher.py          ← BUYMA注文検出
│   ├── profitability_recheck.py  ← 利益再計算
│   ├── cart_builder.py           ← カート構築
│   └── human_review_queue.py     ← 人間レビューキュー
├── ranker/
├── guards/
├── core/
├── scouts/
├── listing/
└── utils/

scripts/
├── run_pipeline.py    ← PHASE1
├── run_guard.py       ← PHASE2
├── run_ranker.py      ← PHASE3
└── run_order_desk.py  ← PHASE4
```

---

## 最終チェックリスト（PHASE4 完了）

- [ ] `app/order_desk/` ディレクトリが作成されている
- [ ] 4つのモジュールが実装されている
- [ ] orders, cart_queue テーブルが正しく連携
- [ ] 人間の最終確認フロー（JSON ファイル確認 → 手動チェックアウト）が設計されている
- [ ] 支払い処理は自動化されていない（人間が必ず実行）
- [ ] `scripts/run_order_desk.py` が実装され、実行可能

