"""Spot accounting: every persistent amount is Decimal, never a binary float."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from collections import deque
from trading_bot.core.events.models import Fill, Side
from trading_bot.core.portfolio.precision import dec, ledger

ZERO=Decimal(0)

@dataclass
class Position:
    quantity: Decimal=ZERO
    cost: Decimal=ZERO  # remaining cost basis including entry fees
    opened_at: datetime|None=None
    realized: Decimal=ZERO
    sold_quantity: Decimal=ZERO
    def __post_init__(self):
        self.quantity=dec(self.quantity);self.cost=dec(self.cost)
        self.realized=dec(self.realized);self.sold_quantity=dec(self.sold_quantity)

class Portfolio:
    def __init__(self,cash,history_limit=None):
        cash=ledger(cash)
        if cash<=0:raise ValueError('invalid starting cash')
        self.initial_cash=self.cash=cash
        self.positions:dict[str,Position]={}
        self.history_limit=history_limit
        self.trades=deque(maxlen=history_limit) if history_limit else []
        self.fills=deque(maxlen=history_limit) if history_limit else []
        self.realized_total=ZERO;self.fees_total=ZERO
        self.fill_count=0;self.trade_offset=0

    def quantity(self,symbol):return self.positions.get(symbol,Position()).quantity
    def gross(self,prices):
        return ledger(sum((p.quantity*dec(prices[s]) for s,p in self.positions.items() if p.quantity>0),ZERO))
    def equity(self,prices):return ledger(self.cash+self.gross(prices))

    def apply(self,fill:Fill,prices):
        q=dec(fill.quantity);price=dec(fill.price);fee=ledger(fill.fee)
        if q<=0 or price<=0 or fee<0:raise ValueError('invalid fill')
        p=self.positions.setdefault(fill.symbol,Position())
        value=ledger(q*price);realized=ZERO
        if fill.side==Side.BUY:
            if value+fee>self.cash:raise ValueError('insufficient cash')
            if p.quantity==0:p.opened_at=fill.timestamp
            self.cash=ledger(self.cash-value-fee)
            p.quantity+=q;p.cost=ledger(p.cost+value+fee)
        else:
            if q>p.quantity:raise ValueError('cannot short spot holdings')
            with localcontext() as ctx:
                ctx.prec=65
                basis=p.cost if q==p.quantity else ledger(p.cost*q/p.quantity)
            realized=ledger(value-fee-basis)
            self.cash=ledger(self.cash+value-fee)
            p.quantity-=q;p.cost=ledger(p.cost-basis)
            p.realized=ledger(p.realized+realized);p.sold_quantity+=q
            if p.quantity==0:
                if self.history_limit and len(self.trades)==self.history_limit:self.trade_offset+=1
                self.trades.append({'symbol':fill.symbol,'strategy':fill.strategy,'opened_at':p.opened_at,
                    'closed_at':fill.timestamp,'pnl':p.realized,'quantity':p.sold_quantity,
                    'holding_seconds':(fill.timestamp-p.opened_at).total_seconds()})
                self.positions[fill.symbol]=Position()
        self.realized_total=ledger(self.realized_total+realized)
        self.fees_total=ledger(self.fees_total+fee)
        self.fill_count+=1
        self.fills.append({**fill.__dict__,'quantity':q,'price':price,'fee':fee,
                           'slippage':dec(fill.slippage),'signal':fill.side.value,
                           'portfolio_value':self.equity(prices),'pnl':realized,
                           'fill_id':fill.fill_id})
        return realized

    def snapshot(self,prices):
        positions={s:{'quantity':p.quantity,'average_entry_price':ledger(p.cost/p.quantity),
                      'unrealized_pnl':ledger(p.quantity*dec(prices[s])-p.cost)}
                   for s,p in self.positions.items() if p.quantity>0}
        return {'cash':self.cash,'equity':self.equity(prices),'positions':positions,
                'unrealized_pnl':ledger(sum((x['unrealized_pnl'] for x in positions.values()),ZERO)),
                'realized_pnl':self.realized_total,'fees':self.fees_total}
