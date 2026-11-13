"""Pure session-intent strategy. No market-data, broker, or persistence dependency."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from hashlib import sha256
import json

from trading_bot.core.events.models import Side
from trading_bot.core.portfolio.precision import dec, floor_step, tick_price

VERSION = "laoer_tqqq_bounded_v1"
D = Decimal


@dataclass(frozen=True)
class Parameters:
    slices: int = 40
    target: Decimal = D(".10")
    generous: Decimal = D(".10")
    allocation: Decimal = D("1")
    interval: int = 1
    fee: Decimal = D(".0005")
    slip: Decimal = D(".0005")
    tick: Decimal = D(".01")
    reserve: Decimal = D("0")
    max_order: Decimal = D("10000")
    daily_orders: int = 3
    exposure: Decimal = D("1")
    fx_cost: Decimal = D("0")

    def __post_init__(self):
        for name in ("target","generous","allocation","fee","slip","tick","reserve","max_order","exposure","fx_cost"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if not (1 <= self.slices <= 1000 and self.interval >= 1 and 1 <= self.daily_orders <= 3
                and 0 < self.allocation <= 1 and 0 < self.exposure <= 1
                and 0 < self.target < 1 and 0 <= self.generous < 1
                and all(0 <= v < D(".1") for v in (self.fee,self.slip,self.fx_cost))
                and self.tick > 0 and self.reserve >= 0 and self.max_order > 0):
            raise ValueError("invalid strategy parameters")

    @property
    def digest(self):
        return sha256(json.dumps([VERSION,asdict(self)], sort_keys=True,default=str).encode()).hexdigest()


@dataclass
class Cycle:
    id: str
    started_at: str
    allocated: Decimal
    spent: Decimal = D(0)
    filled_days: set = field(default_factory=set)
    last_buy_index: int | None = None
    exhausted_at: str | None = None
    exhausted_mark: Decimal | None = None
    max_post_exhaustion_drop: Decimal = D(0)
    distribution_start: Decimal = D(0)


@dataclass(frozen=True)
class Intent:
    id: str
    session: str
    cycle_id: str
    side: Side
    kind: str
    quantity: Decimal
    limit: Decimal


class LaoerStrategy:
    def __init__(self, config=Parameters()):
        self.config = config

    def plan(self, *, day, index, opening_mark, cycle, quantity, average, cash):
        c = self.config
        intents = []

        def add(side, kind, qty, price):
            if qty > 0 and price > 0 and len(intents) < c.daily_orders:
                oid = sha256(f"{c.digest}|{cycle.id}|{day}|{kind}".encode()).hexdigest()
                intents.append(Intent(oid, day, cycle.id, side, kind, qty, price))

        if quantity:
            add(Side.SELL, "DAY_EXIT", quantity, tick_price(average*(1+c.target), c.tick, True))
        if (cycle.exhausted_at or len(cycle.filled_days) >= c.slices or
            (cycle.last_buy_index is not None and index-cycle.last_buy_index < c.interval)):
            return intents
        available = max(D(0), min(cycle.allocated-cycle.spent, cash-c.reserve))
        size = cycle.allocated/c.slices
        if not quantity:
            legs = [("OPEN_ENTRY", opening_mark*(1+c.slip), size)]
        else:
            legs = [("LOC_AVG",average,size/2), ("LOC_OPEN",opening_mark*(1+c.generous),size/2)]
        for kind, raw, budget in legs:
            price = tick_price(raw,c.tick,kind=="OPEN_ENTRY")
            if price <= 0:
                continue
            qty = floor_step(min(available,budget,c.max_order)/(price*(1+c.fee)),1)
            add(Side.BUY,kind,qty,price)
            available -= qty*price*(1+c.fee)
        return intents
