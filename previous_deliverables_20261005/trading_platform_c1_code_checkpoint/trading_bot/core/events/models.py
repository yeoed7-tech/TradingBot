"""Exchange-independent contracts. Timestamps are UTC bar OPEN times."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import uuid4
import math
from decimal import Decimal
from trading_bot.core.portfolio.precision import dec

class Side(StrEnum):
    BUY = 'BUY'
    SELL = 'SELL'

class OrderType(StrEnum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'

class Status(StrEnum):
    CREATED = 'CREATED'
    SUBMITTED = 'SUBMITTED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    REJECTED = 'REJECTED'
    FAILED = 'FAILED'

TERMINAL = {Status.FILLED, Status.CANCELLED, Status.REJECTED, Status.FAILED}

@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True)
class Signal:
    symbol: str
    target_weight: float | None  # None = HOLD, 0 = exit, positive = target allocation
    strategy: str
    reason: str = ''
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None

    def __post_init__(self):
        if self.target_weight is not None and not 0 <= self.target_weight <= 1:
            raise ValueError('target weight must be in [0,1]')
        if self.order_type == OrderType.LIMIT and (self.limit_price is None or not math.isfinite(self.limit_price) or self.limit_price <= 0):
            raise ValueError('limit price required')

@dataclass
class Order:
    symbol: str
    side: Side
    quantity: Decimal
    strategy: str
    created_at: datetime
    eligible_bar: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    status: Status = Status.CREATED
    filled: Decimal = Decimal(0)
    fills_seen: int = 0
    reason: str = ''

    def __post_init__(self):
        self.quantity=dec(self.quantity);self.filled=dec(self.filled)
        if self.quantity<=0 or self.filled<0 or self.filled>self.quantity:
            raise ValueError('quantity/fill invalid')
        if self.limit_price is not None:self.limit_price=dec(self.limit_price)
        if self.order_type == OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError('limit price required')

    @property
    def remaining(self):
        return max(Decimal(0), self.quantity - self.filled)

    def transition(self, status: Status, reason: str = ''):
        allowed = {
            Status.CREATED: {Status.SUBMITTED, Status.REJECTED, Status.FAILED, Status.CANCELLED},
            Status.SUBMITTED: {Status.PARTIALLY_FILLED, *TERMINAL},
            Status.PARTIALLY_FILLED: {Status.PARTIALLY_FILLED, *TERMINAL},
        }
        if status not in allowed.get(self.status, set()):
            raise ValueError(f'illegal transition {self.status} -> {status}')
        self.status, self.reason = status, reason

@dataclass(frozen=True)
class Fill:
    order_id: str
    timestamp: datetime
    symbol: str
    strategy: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    slippage: Decimal  # quote-currency cost relative to unadjusted price
    fill_id: str | None = None
    def __post_init__(self):
        for key in ('quantity','price','fee','slippage'):
            object.__setattr__(self,key,dec(getattr(self,key)))
