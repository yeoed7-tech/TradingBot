"""Immutable public-data messages. No adapter or executable callback is carried."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from trading_bot.core.events.models import Bar

class InvalidMarketData(ValueError): pass

class FeedState(StrEnum):
    NORMAL='NORMAL'
    DISCONNECTED='DISCONNECTED'
    STALE_DATA='STALE_DATA'
    GAP='GAP'
    INVALID_DATA='INVALID_DATA'
    FAILED='FAILED'
    RECONCILIATION_REQUIRED='RECONCILIATION_REQUIRED'


def utc_ms(value):
    if not isinstance(value,(float,int)) or not math.isfinite(value) or value<=0:
        raise InvalidMarketData('invalid millisecond timestamp')
    return datetime.fromtimestamp(value/1000,timezone.utc)


def positive(value):
    if value is None or not math.isfinite(float(value)) or float(value)<=0:
        raise InvalidMarketData('nonpositive or nonfinite price/quantity')
    return float(value)


def validate_bar(b):
    if b.timestamp.tzinfo is None: raise InvalidMarketData('timestamp requires timezone')
    for v in (b.open,b.high,b.low,b.close): positive(v)
    if not math.isfinite(b.volume) or b.volume<0: raise InvalidMarketData('invalid volume')
    if b.low>min(b.open,b.close) or b.high<max(b.open,b.close) or b.low>b.high:
        raise InvalidMarketData('inconsistent OHLC')

@dataclass(frozen=True)
class Quote:
    symbol: str
    timestamp: datetime  # exchange timestamp, not local receive time
    bid: float
    ask: float
    bid_quantity: float
    ask_quantity: float

    def __post_init__(self):
        if self.timestamp.tzinfo is None: raise InvalidMarketData('quote must be timezone-aware')
        for v in (self.bid,self.ask,self.bid_quantity,self.ask_quantity): positive(v)
        if self.bid>self.ask: raise InvalidMarketData('crossed order book')

    @property
    def mid(self): return (self.bid+self.ask)/2

@dataclass(frozen=True)
class FeedEvent:
    observed_at: datetime
    state: FeedState
    bars: tuple[Bar,...]=()
    quote: Quote | None=None
    reason: str=''
    recovered: bool=False
    # A feed event can update indicators without authorizing a new decision.
    decision_allowed: bool=True
