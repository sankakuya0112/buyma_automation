# PHASE2: Guard（在庫・価格監視システム）

## 概要

PHASE1 で構築した基盤の上に、Guard（番人）機能を実装します。Guard は出品済みの商品について、1日1-2回の頻度で以下を監視します：

1. **在庫チェック**: 仕入れ先で商品がまだ入手可能か
2. **価格チェック**: 仕入れ先での価格が変動していないか
3. **自動停止・再出品**: 在庫がない場合は BUYMA 出品を自動停止、復帰時に自動再出品

**完了条件**: `app/guards/` ディレクトリ下に3つのモジュールが完成し、定期実行スクリプト（`scripts/run_guard.py`）で1日2回実行可能なこと。

---

## タスク2-1: 在庫監視モジュール（app/guards/stock_monitor.py）

### 実施内容

各出品の仕入れ先サイトにアクセスし、在庫状況を確認します。

```python
# app/guards/stock_monitor.py

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright, Page
from app.core.models import Listing, SourceProduct, InventoryCheck
from app.core.config import get_config
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class StockMonitor:
    """
    仕入れ先サイトの在庫をモニタリング。
    各出品に紐付いた source_product_url へアクセスし、availability を確認。
    """
    
    def __init__(self):
        self.config = get_config()
    
    def check_stock(self, session: Session, listing_id: int) -> Tuple[bool, Optional[str]]:
        """
        1件の出品について在庫チェックを実行。
        
        Args:
            session: DB セッション
            listing_id: 監視対象の listing ID
        
        Returns:
            (stock_available: bool, evidence_path: str or None)
            evidence_path: スクリーンショット保存パス（失敗時）
        """
        listing = session.query(Listing).get(listing_id)
        if not listing:
            logger.error(f"Listing {listing_id} not found")
            return False, None
        
        product = listing.ranked_product.source_product
        url = product.product_url
        
        logger.info(f"Checking stock for {listing_id}: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                page.goto(url, timeout=self.config.timeout_seconds * 1000)
                page.wait_for_load_state("networkidle")
                
                # 仕入れ先に応じた在庫確認ロジック
                stock_available = self._check_availability_baseblu(page)
                
                # InventoryCheck レコード作成
                current_price = self._extract_price(page)
                check = InventoryCheck(
                    source_product_id=product.id,
                    stock_available=stock_available,
                    price_at_check=current_price,
                    notes=f"Checked at {datetime.utcnow().isoformat()}",
                )
                session.add(check)
                session.commit()
                
                logger.info(f"Stock available: {stock_available}")
                return stock_available, None
            except Exception as e:
                logger.error(f"Failed to check stock: {e}")
                # スクリーンショット保存
                evidence_path = f"evidence/{listing_id}_{datetime.utcnow().timestamp()}.png"
                page.screenshot(path=evidence_path)
                return False, evidence_path
            finally:
                browser.close()
    
    def _check_availability_baseblu(self, page: Page) -> bool:
        """
        BaseBlu 固有の在庫確認ロジック。
        他の仕入れ先に応じてメソッドを追加。
        """
        try:
            # 例: "In Stock" というテキストを探す
            in_stock_element = page.locator("text=In Stock")
            is_visible = in_stock_element.is_visible()
            
            # または "Add to Cart" ボタンの有無で判定
            add_to_cart = page.locator("button:has-text('Add to Cart')")
            is_enabled = add_to_cart.is_enabled()
            
            return is_visible or is_enabled
        except Exception as e:
            logger.warning(f"Failed to extract availability: {e}")
            return False
    
    def _extract_price(self, page: Page) -> Optional[float]:
        """
        ページから現在の価格を抽出。
        """
        try:
            price_text = page.locator("[data-price]").inner_text()
            # "€99.99" → 99.99
            price = float(price_text.replace("€", "").replace(",", ".").strip())
            return price
        except Exception:
            return None
    
    def run_all(self, session: Session) -> dict:
        """
        全アクティブな出品の在庫チェック。
        
        Returns:
            {
                'total': 総チェック件数,
                'available': 在庫あり件数,
                'unavailable': 在庫なし件数,
                'failed': エラー件数,
            }
        """
        # 出品中 or 停止中のリスティングを対象
        listings = session.query(Listing).filter(
            Listing.listing_status.in_(["published", "stopped"])
        ).all()
        
        results = {
            'total': len(listings),
            'available': 0,
            'unavailable': 0,
            'failed': 0,
        }
        
        for listing in listings:
            try:
                stock_available, evidence = self.check_stock(session, listing.id)
                if stock_available:
                    results['available'] += 1
                else:
                    results['unavailable'] += 1
            except Exception as e:
                logger.error(f"Check failed for {listing.id}: {e}")
                results['failed'] += 1
        
        logger.info(f"Stock check completed: {results}")
        return results
```

### 納品物チェックリスト

- [ ] `app/guards/stock_monitor.py` が作成されている
- [ ] StockMonitor クラスに check_stock() メソッドが実装
- [ ] _check_availability_baseblu() で在庫判定ロジックが実装
- [ ] _extract_price() で仕入れ先の現在価格を抽出
- [ ] run_all() で全出品のチェック実行
- [ ] inventory_checks テーブルに結果が保存

---

## タスク2-2: 価格監視モジュール（app/guards/price_monitor.py）

### 実施内容

仕入れ先での価格変動を検出し、利益率が大幅に悪化した場合には警告を生成します。

```python
# app/guards/price_monitor.py

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.models import SourceProduct, InventoryCheck, RankedProduct
from typing import List, Dict

logger = logging.getLogger(__name__)

class PriceMonitor:
    """
    仕入れ先価格の変動監視。
    直近の InventoryCheck レコードと 過去のレコードを比較。
    """
    
    PRICE_CHANGE_THRESHOLD_PCT = 10.0  # 10%以上の価格変動で警告
    
    def __init__(self):
        pass
    
    def detect_price_changes(self, session: Session) -> List[Dict]:
        """
        直近24時間での価格変動を検出。
        
        Returns:
            List[{
                'product_id': int,
                'old_price': float,
                'new_price': float,
                'change_pct': float,
                'impact_on_profit_jpy': float,
            }]
        """
        changes = []
        
        # 全 SourceProduct を確認
        products = session.query(SourceProduct).all()
        
        for product in products:
            # 直近2回の InventoryCheck を取得
            checks = session.query(InventoryCheck).filter(
                InventoryCheck.source_product_id == product.id
            ).order_by(InventoryCheck.checked_at.desc()).limit(2).all()
            
            if len(checks) < 2:
                continue  # 比較できない
            
            new_check = checks[0]
            old_check = checks[1]
            
            if not new_check.price_at_check or not old_check.price_at_check:
                continue
            
            # 価格変動率
            change_pct = (
                (new_check.price_at_check - old_check.price_at_check) / old_check.price_at_check * 100
            )
            
            if abs(change_pct) > self.PRICE_CHANGE_THRESHOLD_PCT:
                # 利益への影響を計算
                ranked = session.query(RankedProduct).filter(
                    RankedProduct.source_product_id == product.id
                ).first()
                
                if ranked:
                    profit_impact = (new_check.price_at_check - old_check.price_at_check)
                    
                    changes.append({
                        'product_id': product.id,
                        'product_title': product.title,
                        'old_price': old_check.price_at_check,
                        'new_price': new_check.price_at_check,
                        'change_pct': change_pct,
                        'impact_on_profit_jpy': profit_impact,
                        'listing_id': self._find_listing_id(session, product.id),
                    })
                    
                    logger.warning(
                        f"Price change detected: {product.title} "
                        f"{old_check.price_at_check} → {new_check.price_at_check} "
                        f"({change_pct:+.1f}%)"
                    )
        
        return changes
    
    def _find_listing_id(self, session: Session, product_id: int) -> int:
        """SourceProduct に紐付く Listing を取得。"""
        from app.core.models import Listing
        listing = session.query(Listing).join(RankedProduct).filter(
            RankedProduct.source_product_id == product_id
        ).first()
        return listing.id if listing else None
    
    def generate_alert(self, changes: List[Dict]) -> None:
        """
        価格変動アラートをログに出力。
        必要に応じてメール・Slack等に連携。
        """
        if not changes:
            logger.info("No significant price changes")
            return
        
        alert_message = f"Price change alert ({len(changes)} products)\n"
        for change in changes:
            alert_message += (
                f"  - {change['product_title']}: "
                f"{change['old_price']} → {change['new_price']} "
                f"({change['change_pct']:+.1f}%) "
                f"→ Profit impact: ¥{change['impact_on_profit_jpy']:+.0f}\n"
            )
        
        logger.warning(alert_message)
```

### 納品物チェックリスト

- [ ] `app/guards/price_monitor.py` が作成されている
- [ ] PriceMonitor クラスに detect_price_changes() メソッドが実装
- [ ] 直近2回の InventoryCheck を比較して価格変動を検出
- [ ] 変動率が閾値を超えた場合にアラート生成
- [ ] generate_alert() でログに警告を出力

---

## タスク2-3: 自動停止・再出品モジュール（app/guards/listing_guard.py）

### 実施内容

在庫チェック結果に基づいて、BUYMA出品を自動停止・再出品します。

```python
# app/guards/listing_guard.py

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright
from app.core.models import Listing, ListingStatusEnum, ListingEvent
from app.listing.buyma_client import BUYMAClient
from app.core.config import get_config
from typing import Tuple

logger = logging.getLogger(__name__)

class ListingGuard:
    """
    Listing を監視し、在庫状況に応じて自動停止・再出品。
    """
    
    def __init__(self):
        self.config = get_config()
    
    def stop_listing(self, session: Session, listing_id: int) -> bool:
        """
        BUYMA 出品を停止。
        
        Args:
            session: DB セッション
            listing_id: 停止対象の listing ID
        
        Returns:
            成功 True / 失敗 False
        """
        listing = session.query(Listing).get(listing_id)
        if not listing:
            logger.error(f"Listing {listing_id} not found")
            return False
        
        if listing.listing_status == "stopped":
            logger.info(f"Listing {listing_id} already stopped")
            return True
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.config.headless)
                page = browser.new_page()
                
                try:
                    client = BUYMAClient(page)
                    client.login()
                    
                    # BUYMA マイページ → 出品中 → 該当商品 → 停止
                    page.goto(f"https://buyma.jp/sell/items/{listing.buyma_item_id}/edit")
                    page.wait_for_load_state("networkidle")
                    
                    # 停止ボタンをクリック
                    page.click("button[data-action=stop-listing]")
                    page.wait_for_load_state("networkidle")
                    
                    # DB 更新
                    listing.listing_status = ListingStatusEnum.stopped.value
                    listing.stopped_at = datetime.utcnow()
                    
                    # Event ログ
                    event = ListingEvent(
                        listing_id=listing.id,
                        event_type="stopped",
                        detail={"reason": "stock_unavailable"},
                    )
                    session.add(event)
                    session.commit()
                    
                    logger.info(f"Stopped listing {listing_id}")
                    return True
                finally:
                    browser.close()
        except Exception as e:
            logger.error(f"Failed to stop listing {listing_id}: {e}")
            return False
    
    def relist_listing(self, session: Session, listing_id: int) -> bool:
        """
        停止中の出品を再出品。
        
        Args:
            session: DB セッション
            listing_id: 再出品対象の listing ID
        
        Returns:
            成功 True / 失敗 False
        """
        listing = session.query(Listing).get(listing_id)
        if not listing:
            logger.error(f"Listing {listing_id} not found")
            return False
        
        if listing.listing_status != "stopped":
            logger.info(f"Listing {listing_id} is not stopped, skipping")
            return True
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.config.headless)
                page = browser.new_page()
                
                try:
                    client = BUYMAClient(page)
                    client.login()
                    
                    # 停止中の出品を再出品
                    page.goto(f"https://buyma.jp/sell/items/{listing.buyma_item_id}/edit")
                    page.wait_for_load_state("networkidle")
                    
                    # 再出品ボタンをクリック
                    page.click("button[data-action=relist]")
                    page.wait_for_load_state("networkidle")
                    
                    # DB 更新
                    listing.listing_status = ListingStatusEnum.relisted.value
                    listing.relisted_at = datetime.utcnow()
                    
                    # Event ログ
                    event = ListingEvent(
                        listing_id=listing.id,
                        event_type="relisted",
                        detail={"reason": "stock_available"},
                    )
                    session.add(event)
                    session.commit()
                    
                    logger.info(f"Relisted listing {listing_id}")
                    return True
                finally:
                    browser.close()
        except Exception as e:
            logger.error(f"Failed to relist listing {listing_id}: {e}")
            return False
    
    def sync_with_stock(self, session: Session) -> dict:
        """
        全出品の在庫状況と BUYMA出品ステータスを同期。
        - stock_available=False かつ listing_status=published → 停止
        - stock_available=True かつ listing_status=stopped → 再出品
        
        Returns:
            {
                'stopped': 停止した件数,
                'relisted': 再出品した件数,
            }
        """
        from app.core.models import InventoryCheck
        
        results = {'stopped': 0, 'relisted': 0}
        
        # 全 Listing を確認
        listings = session.query(Listing).filter(
            Listing.listing_status.in_(["published", "stopped"])
        ).all()
        
        for listing in listings:
            product = listing.ranked_product.source_product
            
            # 直近の InventoryCheck を取得
            latest_check = session.query(InventoryCheck).filter(
                InventoryCheck.source_product_id == product.id
            ).order_by(InventoryCheck.checked_at.desc()).first()
            
            if not latest_check:
                continue
            
            # 同期処理
            if not latest_check.stock_available and listing.listing_status == "published":
                # 在庫なし & 出品中 → 停止
                if self.stop_listing(session, listing.id):
                    results['stopped'] += 1
            
            elif latest_check.stock_available and listing.listing_status == "stopped":
                # 在庫あり & 停止中 → 再出品
                if self.relist_listing(session, listing.id):
                    results['relisted'] += 1
        
        logger.info(f"Sync completed: {results}")
        return results
```

### 納品物チェックリスト

- [ ] `app/guards/listing_guard.py` が作成されている
- [ ] ListingGuard クラスに stop_listing() メソッドが実装
- [ ] relist_listing() メソッドが実装
- [ ] sync_with_stock() で全出品と在庫状況を同期
- [ ] ListingEvent にて停止・再出品イベントを記録

---

## タスク2-4: Guard 定期実行スクリプト（scripts/run_guard.py）

### 実施内容

Guard のすべての処理を定期実行するメインスクリプト。

```python
# scripts/run_guard.py

#!/usr/bin/env python3
"""
Guard 定期実行スクリプト。
1日1-2回、以下を実行：
  1. Stock Monitor: 仕入れ先の在庫確認
  2. Price Monitor: 価格変動検出
  3. Listing Guard: 出品の自動停止・再出品

Usage:
    python3 scripts/run_guard.py
"""

import sys
from pathlib import Path
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_config
from app.core.logger import setup_logger
from app.core.models import Base
from app.guards.stock_monitor import StockMonitor
from app.guards.price_monitor import PriceMonitor
from app.guards.listing_guard import ListingGuard

logger = setup_logger("run_guard")

def main():
    logger.info("=== Guard started ===")
    
    # DB 初期化
    config = get_config()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    
    try:
        # Step 1: Stock Monitor
        logger.info("Step 1: Checking inventory...")
        stock_monitor = StockMonitor()
        stock_results = stock_monitor.run_all(session)
        logger.info(f"Stock check results: {stock_results}")
        
        # Step 2: Price Monitor
        logger.info("Step 2: Detecting price changes...")
        price_monitor = PriceMonitor()
        changes = price_monitor.detect_price_changes(session)
        price_monitor.generate_alert(changes)
        
        # Step 3: Listing Guard
        logger.info("Step 3: Syncing listing status...")
        listing_guard = ListingGuard()
        sync_results = listing_guard.sync_with_stock(session)
        logger.info(f"Sync results: {sync_results}")
        
        logger.info("=== Guard completed ===")
    finally:
        session.close()

if __name__ == "__main__":
    main()
```

### 実行スケジュール

crontab または Task Scheduler で以下のように定期実行：

```bash
# 毎日 08:00 と 20:00 に実行
0 8,20 * * * cd /path/to/buyma_automation && python3 scripts/run_guard.py >> logs/guard_cron.log 2>&1
```

### 納品物チェックリスト

- [ ] `scripts/run_guard.py` が作成されている
- [ ] StockMonitor, PriceMonitor, ListingGuard の3つを順序実行
- [ ] 各処理結果がログに記録される
- [ ] クロンジョブで定期実行可能な設計

---

## ディレクトリ構成の更新

PHASE2 完了後、以下のように `app/guards/` ディレクトリが追加：

```
app/
├── guards/
│   ├── __init__.py
│   ├── stock_monitor.py     ← 仕入れ先の在庫確認
│   ├── price_monitor.py     ← 価格変動検出
│   └── listing_guard.py     ← 出品の自動停止・再出品
├── core/
├── scouts/
├── listing/
└── utils/

scripts/
├── run_pipeline.py          ← PHASE1（出品パイプライン）
└── run_guard.py             ← PHASE2（監視パイプライン）
```

---

## 最終チェックリスト（PHASE2 完了）

- [ ] `app/guards/` ディレクトリが作成されている
- [ ] 3つのモジュール（stock_monitor, price_monitor, listing_guard）が実装
- [ ] `scripts/run_guard.py` が実装され、定期実行可能
- [ ] inventory_checks テーブルに毎回のチェック結果が保存
- [ ] listing_events テーブルに停止・再出品イベントが記録
- [ ] 価格変動がログ/アラートとして検出される

