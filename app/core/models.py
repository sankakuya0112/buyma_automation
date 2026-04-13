"""SQLAlchemy ORM 全テーブル定義"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# テーブル1: source_products
# ---------------------------------------------------------------------------

class SourceProduct(Base):
    """
    仕入れ先サイトから取得した商品情報。
    各スクレイパーが保存責任を持つ。
    """

    __tablename__ = "source_products"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(50), nullable=False)       # "baseblu", "yoox", "ssense" etc.
    product_url = Column(String(500), nullable=False, unique=True)
    brand = Column(String(100), nullable=False)
    title = Column(String(300), nullable=False)
    sku = Column(String(100), nullable=True)               # 品番（メーカー品番）
    color = Column(String(100), nullable=True)
    category = Column(String(100), nullable=True)          # 仕入れ先でのカテゴリ
    source_price = Column(Float, nullable=False)           # 現地価格
    currency = Column(String(3), default="EUR", nullable=False)  # "EUR", "USD", "GBP"
    shipping_cost = Column(Float, default=0.0, nullable=False)

    # JSONカラム: 複数の画像URL、サブ画像群
    image_urls = Column(JSON, default=list)                # [url1, url2, ...]
    sub_images = Column(JSON, default=list)                # [{"url": ..., "alt_text": ...}, ...]

    description_en = Column(Text, nullable=True)           # 英語版商品説明
    stock_status = Column(String(20), default="in_stock")  # "in_stock", "limited", "out_of_stock"
    scraped_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    ranked_products = relationship("RankedProduct", back_populates="source_product")
    inventory_checks = relationship("InventoryCheck", back_populates="source_product")


# ---------------------------------------------------------------------------
# テーブル2: ranked_products
# ---------------------------------------------------------------------------

class RankedProduct(Base):
    """
    source_products を評価した結果。
    - Governor: approved/hold/reject を判定
    - Ranker:   est_profit_jpy, est_margin_pct, lane を算出
    """

    __tablename__ = "ranked_products"

    id = Column(Integer, primary_key=True)
    source_product_id = Column(
        Integer, ForeignKey("source_products.id"), nullable=False
    )

    # Profitability
    est_profit_jpy = Column(Float, nullable=False)         # 推定利益（円）
    est_margin_pct = Column(Float, nullable=False)         # 利益率（%）

    # Competition Analysis
    competitor_count = Column(Integer, default=0)
    competitor_min_price = Column(Float, nullable=True)    # BUYMA 内での最低価格

    # Lane assignment
    lane = Column(String(20), nullable=False)              # "core", "long_tail", "hold", "reject"
    rank_score = Column(Float, nullable=False)             # 0.0 - 100.0
    decision_reason = Column(Text, nullable=True)

    # Governance
    governor_decision = Column(String(20), default="pending")  # "approved", "hold", "reject"
    governor_notes = Column(Text, nullable=True)

    ranked_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    source_product = relationship("SourceProduct", back_populates="ranked_products")
    listings = relationship("Listing", back_populates="ranked_product")
    orders = relationship("Order", back_populates="ranked_product")


# ---------------------------------------------------------------------------
# テーブル3: listings
# ---------------------------------------------------------------------------

class Listing(Base):
    """
    BUYMA 上の出品。出品状況、価格、説明文を記録。
    Publisher が作成し、Guard と Support が更新する。
    """

    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    ranked_product_id = Column(
        Integer, ForeignKey("ranked_products.id"), nullable=False
    )
    buyma_item_id = Column(String(50), nullable=True)      # BUYMA 内部 item ID

    # Listing Status: "draft" → "published" → "stopped" → "relisted" → "archived"
    listing_status = Column(String(20), default="draft", nullable=False)

    listing_price_jpy = Column(Float, nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)

    # Timestamps
    listed_at = Column(DateTime, nullable=True)            # 出品日時
    stopped_at = Column(DateTime, nullable=True)           # 停止日時
    relisted_at = Column(DateTime, nullable=True)          # 再出品日時

    # Relationships
    ranked_product = relationship("RankedProduct", back_populates="listings")
    events = relationship("ListingEvent", back_populates="listing")
    orders = relationship("Order", back_populates="listing")


# ---------------------------------------------------------------------------
# テーブル4: listing_events
# ---------------------------------------------------------------------------

class ListingEvent(Base):
    """
    出品に対するアクション履歴：停止、再出品、価格変更等。
    Guard や Support が記録する。
    """

    __tablename__ = "listing_events"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)

    event_type = Column(String(50), nullable=False)
    # "published", "stopped", "relisted", "price_updated", "stock_check_failed" etc.

    detail = Column(JSON, nullable=True)                   # {"old_price": 50000, "new_price": 48000}
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    listing = relationship("Listing", back_populates="events")


# ---------------------------------------------------------------------------
# テーブル5: inventory_checks
# ---------------------------------------------------------------------------

class InventoryCheck(Base):
    """
    Guard が定期的に実施する在庫確認。
    仕入れ先サイトでの入手可能性・現在価格を記録。
    """

    __tablename__ = "inventory_checks"

    id = Column(Integer, primary_key=True)
    source_product_id = Column(
        Integer, ForeignKey("source_products.id"), nullable=False
    )

    checked_at = Column(DateTime, default=datetime.utcnow)
    stock_available = Column(Boolean, nullable=False)
    price_at_check = Column(Float, nullable=True)          # 現在の仕入れ価格
    notes = Column(Text, nullable=True)                    # スクリーンショットパス等

    # Relationships
    source_product = relationship("SourceProduct", back_populates="inventory_checks")


# ---------------------------------------------------------------------------
# テーブル6: orders
# ---------------------------------------------------------------------------

class Order(Base):
    """
    BUYMA 上で発生した注文。
    売上確定後、人間が買付を承認・保留・却下する。
    """

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    buyma_order_id = Column(String(50), nullable=False, unique=True)
    ranked_product_id = Column(
        Integer, ForeignKey("ranked_products.id"), nullable=False
    )
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)

    ordered_at = Column(DateTime, nullable=False)
    order_status = Column(String(20), default="awaiting_confirmation", nullable=False)
    # "awaiting_confirmation" → "approved" → "rejected" → "completed" → "cancelled"

    # 利益の再計算（注文時の為替・価格で再算出）
    rechecked_stock = Column(Boolean, default=False)
    rechecked_profit_jpy = Column(Float, nullable=True)
    rechecked_margin_pct = Column(Float, nullable=True)

    # 人間の決定
    human_decision = Column(String(20), nullable=True)     # "approved", "hold", "rejected"
    human_notes = Column(Text, nullable=True)
    human_reviewed_at = Column(DateTime, nullable=True)

    # Relationships
    ranked_product = relationship("RankedProduct", back_populates="orders")
    listing = relationship("Listing", back_populates="orders")
    cart_queue = relationship("CartQueue", back_populates="order", uselist=False)


# ---------------------------------------------------------------------------
# テーブル7: cart_queue
# ---------------------------------------------------------------------------

class CartQueue(Base):
    """
    仕入れ先サイトのカートに入れた商品。
    自動化は「カートまで」。チェックアウト・支払いは人間が実施。
    """

    __tablename__ = "cart_queue"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)

    source_url = Column(String(500), nullable=False)
    cart_added_at = Column(DateTime, default=datetime.utcnow)
    cart_status = Column(String(20), default="pending", nullable=False)
    # "pending", "ready_for_checkout", "completed"

    human_review_status = Column(String(20), default="awaiting_review", nullable=False)
    # "awaiting_review", "approved", "rejected"
    checkout_ready = Column(Boolean, default=False)

    # Relationships
    order = relationship("Order", back_populates="cart_queue")


# ---------------------------------------------------------------------------
# テーブル8: daily_metrics
# ---------------------------------------------------------------------------

class DailyMetrics(Base):
    """
    毎日の業績集計。Reporter が実施。
    """

    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True)

    # Listing metrics
    total_listings = Column(Integer, default=0)
    new_listings = Column(Integer, default=0)
    stopped_listings = Column(Integer, default=0)

    # Order metrics
    orders_count = Column(Integer, default=0)
    revenue_jpy = Column(Float, default=0.0)
    profit_jpy = Column(Float, default=0.0)

    recorded_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# DB 初期化
# ---------------------------------------------------------------------------

def init_db(db_path: str):
    """SQLite データベースを初期化してエンジンを返す。"""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine
