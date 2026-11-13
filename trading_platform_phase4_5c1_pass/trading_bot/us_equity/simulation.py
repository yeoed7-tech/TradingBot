"""Session-scoped equity simulator using common RiskEngine, Fill and Portfolio."""
from dataclasses import asdict
from hashlib import sha256
import json
from decimal import Decimal

from trading_bot.config.settings import RiskConfig
from trading_bot.core.events.models import Fill, Side
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.core.portfolio.precision import dec, floor_step, tick_price
from trading_bot.core.risk.engine import RiskEngine
from trading_bot.strategies.laoer_tqqq import Cycle, LaoerStrategy, Parameters, VERSION

D = Decimal
SYMBOL = "TQQQ"


class EquitySimulationBroker:
    """Only the simulator sees future session high/close, after intents are frozen."""

    def fill(self, intent, bar, config, capacity=None):
        if intent.kind == "OPEN_ENTRY":
            price, timestamp = intent.limit, bar.opens
        elif intent.kind == "DAY_EXIT":
            trigger = tick_price(intent.limit/(1-config.slip),config.tick,True)
            if bar.open >= trigger:
                price, timestamp = intent.limit, bar.opens
            elif bar.high > trigger:
                # Daily data cannot locate intraday execution; timestamp is a proxy.
                price, timestamp = intent.limit, bar.closes
            else:
                return None
        elif intent.kind in ("LOC_AVG", "LOC_OPEN"):
            price = tick_price(bar.close*(1+config.slip),config.tick,True)
            if price > intent.limit:
                return None
            timestamp = bar.closes
        else:
            raise ValueError("unsupported intent")
        quantity = min(intent.quantity, floor_step(capacity, 1)) if capacity is not None else intent.quantity
        if quantity <= 0:
            return None
        return Fill(intent.id, timestamp, SYMBOL, VERSION, intent.side, quantity, price,
                    quantity*price*config.fee,
                    quantity*(price-(bar.open if intent.kind=="OPEN_ENTRY" else bar.close))
                    if intent.side==Side.BUY else D(0), intent.id+":sim:1")


class ResearchAccount:
    def __init__(self, initial_cash, config=Parameters(), broker=None):
        self.config = config
        self.strategy = LaoerStrategy(config)
        self.portfolio = Portfolio(initial_cash)
        # Nonbinding research loss thresholds: measure drawdowns, do not hide them.
        # The actual buy capacity and a latched kill remain enforced.
        self.risk = RiskEngine(RiskConfig(max_gross_weight=float(config.exposure),
            max_symbol_weight=float(config.exposure), daily_loss=1, weekly_loss=1,
            max_drawdown=1, max_consecutive_losses=100000), initial_cash)
        self.broker = broker or EquitySimulationBroker()
        self.cycle = None
        self.cycles = []
        self.dividends = D(0)
        self.intents = {}
        self.fills = {}
        self.filled_by_order = {}
        self.fill_digest = "0"*64
        self.rows = []
        self.last_day = None
        self.index = 0
        self.failed = False

    def apply_fill(self, fill, marks, day, intent):
        p, c, cycle = self.portfolio, self.config, self.cycle
        prior = self.fills.get(fill.fill_id)
        if prior is not None:
            if prior == fill and self.intents.get(fill.order_id)==intent and intent.session==day:
                return False
            self.risk.kill("duplicate_fill_conflict")
            raise ValueError("conflicting fill")
        valid = (fill.fill_id and self.intents.get(fill.order_id) == intent and
                 fill.order_id == intent.id and fill.symbol == SYMBOL and fill.side == intent.side
                 and cycle and cycle.id == intent.cycle_id and day == intent.session
                 and (self.last_day is None or day > str(self.last_day))
                 and fill.timestamp.tzinfo is not None and fill.price > 0 and fill.quantity > 0
                 and fill.quantity == int(fill.quantity) and fill.fee >= 0)
        if not valid:
            self.risk.kill("unknown_or_invalid_fill")
            raise ValueError("unknown or invalid fill")
        prev = self.filled_by_order.get(intent.id,D(0))
        if prev+fill.quantity > intent.quantity or (
            fill.price > intent.limit if fill.side == Side.BUY else fill.price < intent.limit):
            self.risk.kill("unexpected_fill")
            raise ValueError("unexpected fill amount or price")
        spend = fill.quantity*fill.price+fill.fee
        if fill.side == Side.BUY and (
            cycle.spent+spend > cycle.allocated or p.cash-spend < c.reserve
            or spend > c.max_order or (day not in cycle.filled_days and len(cycle.filled_days)>=c.slices)):
            self.risk.kill("fill_breaks_budget")
            raise ValueError("fill exceeds strategy risk budget")
        p.apply(fill, marks)
        self.fills[fill.fill_id] = fill
        self.fill_digest = sha256((self.fill_digest+json.dumps(asdict(fill),default=str,
                                                               sort_keys=True)).encode()).hexdigest()
        self.filled_by_order[intent.id] = prev+fill.quantity
        if fill.side == Side.BUY:
            cycle.spent += spend
            cycle.filled_days.add(day)
            cycle.last_buy_index = self.index
        return True

    def step(self, bar, capacity=None):
        if self.failed or (self.last_day and bar.day <= self.last_day):
            raise ValueError("failed or repeated session")
        try:
            return self._step(bar, capacity)
        except Exception:
            self.failed = True
            self.risk.kill("session_failed")
            raise

    def _step(self, bar, capacity):
        c, p = self.config, self.portfolio
        day = str(bar.day)
        if not bar.opens < bar.closes or not 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open,bar.close) <= bar.high:
            raise ValueError("invalid session")
        if bar.split < 1 or bar.split != int(bar.split) or bar.dividend < 0:
            raise ValueError("unsupported corporate action")
        pos = p.positions.get(SYMBOL)
        if pos and pos.quantity:
            pos.quantity *= bar.split
            self.dividends += pos.quantity*bar.dividend
        self.risk.observe(bar.opens,p.equity({SYMBOL:bar.open})+self.dividends,p.trades)
        if self.cycle is None:
            allocated = max(D(0), min(p.cash*c.allocation,p.cash-c.reserve))
            self.cycle = Cycle(f"{VERSION}:{day}",day,allocated,distribution_start=self.dividends)
        cycle = self.cycle
        quantity = p.quantity(SYMBOL)
        average = p.positions[SYMBOL].cost/quantity if quantity else D(0)
        intents = self.strategy.plan(day=day,index=self.index,opening_mark=bar.open,cycle=cycle,
                                     quantity=quantity,average=average,cash=p.cash)
        self.intents.update({i.id:i for i in intents})
        sold = False
        for i in intents:
            if i.side==Side.BUY and (sold or not self.risk.check(i.side).allowed):
                continue
            f = self.broker.fill(i,bar,c,capacity)
            if not f:
                continue
            mark = bar.open if f.timestamp == bar.opens else bar.close
            marks = {SYMBOL:mark}
            if i.side==Side.BUY:
                room = floor_step(self.risk.buy_capacity(SYMBOL,p,marks,f.price,c.fee),1)
                if room < f.quantity:
                    f = self.broker.fill(i,bar,c,min(f.quantity,room))
                    if not f:
                        continue
            self.apply_fill(f,marks,day,i)
            sold |= i.side==Side.SELL
        quantity = p.quantity(SYMBOL)
        if sold and quantity==0:
            self.cycles.append(self.cycle_record(bar, completed=True))
            self.cycle = None
        elif quantity:
            remaining = min(cycle.allocated-cycle.spent,p.cash-c.reserve)
            if not cycle.exhausted_at and (len(cycle.filled_days)>=c.slices or remaining<c.tick or
                    remaining < min(bar.close,p.positions[SYMBOL].cost/quantity)*(1+c.fee)):
                cycle.exhausted_at = day
                cycle.exhausted_mark = bar.close
            if cycle.exhausted_at:
                # Compare on a constant share scale across forward splits.
                if cycle.exhausted_at != day:
                    cycle.exhausted_mark /= bar.split
                cycle.max_post_exhaustion_drop = min(cycle.max_post_exhaustion_drop,
                                                     bar.low/cycle.exhausted_mark-1 if cycle.exhausted_at!=day else D(0))
        market = p.gross({SYMBOL:bar.close})
        equity = p.cash+market+self.dividends
        cost = p.positions[SYMBOL].cost if quantity else D(0)
        self.risk.observe(bar.closes,equity,p.trades)
        self.rows.append({"date":day,"equity":equity,"cash":p.cash,"market_value":market,
                          "distribution_receivable":self.dividends,"quantity":quantity,
                          "unrealized":market-cost,"realized":p.realized_total,"fees":p.fees_total,
                          "utilization":market/equity})
        self.last_day = bar.day
        self.index += 1
        return self.rows[-1]

    def cycle_record(self, bar, *, completed):
        c = self.cycle
        if c is None:
            return None
        from datetime import date
        return {**asdict(c),"filled_days":sorted(c.filled_days),"completed":completed,"end":str(bar.day),
                "used_tranches":len(c.filled_days),
                "usage":c.spent/c.allocated if c.allocated else D(0),
                "calendar_days":(bar.day-date.fromisoformat(c.started_at)).days+1,
                "exhausted_days":(bar.day-date.fromisoformat(c.exhausted_at)).days+1 if c.exhausted_at else 0,
                "distribution_pnl":self.dividends-c.distribution_start}

    def snapshot(self):
        p = self.portfolio
        cycle = None if self.cycle is None else {**asdict(self.cycle),"filled_days":sorted(self.cycle.filled_days)}
        return {"config_hash":self.config.digest,"strategy_version":VERSION,
                "cursor":str(self.last_day),"cycle":cycle,"cash":p.cash,
                "remaining_cash":None if cycle is None else min(p.cash,self.cycle.allocated-self.cycle.spent),
                "number_of_buys":None if cycle is None else len(self.cycle.filled_days),
                "quantity":p.quantity(SYMBOL),"average_entry":p.positions[SYMBOL].cost/p.quantity(SYMBOL)
                if p.quantity(SYMBOL) else D(0),
                "current_target":tick_price(p.positions[SYMBOL].cost/p.quantity(SYMBOL)*(1+self.config.target),
                                             self.config.tick,True) if p.quantity(SYMBOL) else None,
                "pending_orders":[],"realized_pnl":p.realized_total,"fees":p.fees_total,
                "distributions":self.dividends,"fill_count":len(self.fills),"fill_digest":self.fill_digest,
                "risk_killed":self.risk.killed,"risk_reason":self.risk.kill_reason,
                "risk_peak":self.risk.peak,"risk_last_equity":self.risk.last_equity,
                "risk_day_start":self.risk.day_start,"risk_week_start":self.risk.week_start,
                "risk_consecutive_losses":self.risk.consecutive_losses,
                "last_fills":{i.id:self.filled_by_order.get(i.id,D(0)) for i in self.intents.values()
                    if i.session==str(self.last_day)},
                "last_intents":[asdict(i) for i in
                    self.intents.values() if i.session==str(self.last_day)]}
