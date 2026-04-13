"""ステータス定義（Lane, ListingStatus等）"""

import enum


class ListingStatusEnum(enum.Enum):
    draft = "draft"
    published = "published"
    stopped = "stopped"
    relisted = "relisted"
    archived = "archived"


class LaneEnum(enum.Enum):
    core = "core"
    long_tail = "long_tail"
    hold = "hold"
    reject = "reject"


class OrderStatusEnum(enum.Enum):
    awaiting_confirmation = "awaiting_confirmation"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"
    cancelled = "cancelled"


class GovernorDecisionEnum(enum.Enum):
    pending = "pending"
    approved = "approved"
    hold = "hold"
    reject = "reject"


class StockStatusEnum(enum.Enum):
    in_stock = "in_stock"
    limited = "limited"
    out_of_stock = "out_of_stock"


class CartStatusEnum(enum.Enum):
    pending = "pending"
    ready_for_checkout = "ready_for_checkout"
    completed = "completed"
