"""Exchange-independent Decimal order decisions and deterministic simulation."""
from decimal import Decimal
from collections import deque
from trading_bot.core.events.models import Order,Fill,Side,Status,OrderType,TERMINAL
from trading_bot.core.portfolio.precision import dec,ledger,floor_step,tick_price

class ExecutionEngine:
    def __init__(self,settings,history_limit=None):
        self.settings=settings;self.history_limit=history_limit
        self.orders=deque() if history_limit else [];self.ids=set()
        self.events=deque(maxlen=history_limit) if history_limit else []
        self.intent_writer=None
        self.order_count=0

    def submit(self,order):
        if order.id in self.ids:return False
        if any(o.symbol==order.symbol and o.status not in TERMINAL for o in self.orders):
            raise ValueError('active order already exists for symbol')
        if self.intent_writer is not None:
            row=self.intent_writer(order)
            if row is not None and row.status!='CREATED':return False
        order.transition(Status.SUBMITTED)
        self.orders.append(order);self.ids.add(order.id);self.order_count+=1
        if self.history_limit:
            while len(self.orders)>self.history_limit:
                old=next((o for o in self.orders if o.status in TERMINAL),None)
                if old is None:break # active orders are never evicted
                self.orders.remove(old);self.ids.discard(old.id)
        return True

    def active(self,symbol):return next((o for o in self.orders if o.symbol==symbol and o.status not in TERMINAL),None)
    def cancel(self,order,reason='user_cancel'):
        if order.status not in TERMINAL:order.transition(Status.CANCELLED,reason)

    def propose(self,signal,portfolio,prices,risk,timestamp,index):
        if signal.symbol not in prices:raise ValueError('signal contains unknown symbol')
        if signal.target_weight is None:return
        symbol=signal.symbol;rule=self.settings.rules_for(symbol)
        mark=dec(prices[symbol]);equity=portfolio.equity(prices)
        target=dec(risk.target_weight(symbol,signal.target_weight,prices[symbol]))
        desired=floor_step(equity*target/mark,rule.quantity_step)
        delta=desired-portfolio.quantity(symbol)
        current=self.active(symbol)
        side=Side.BUY if delta>0 else Side.SELL
        tolerance=equity*dec(risk.config.rebalance_tolerance)
        if current:
            if side!=current.side or abs(delta)*mark<=tolerance:
                self.cancel(current,'target_changed')
            else:return
        if abs(delta)*mark<=tolerance and target!=0:return
        q=floor_step(abs(delta),rule.quantity_step)
        if q<=0 or q<dec(rule.min_quantity) or q*mark<dec(rule.min_notional):return
        decision=risk.check(side)
        self.events.append({'timestamp':timestamp,'event':'risk_decision','symbol':symbol,
                            'allowed':decision.allowed,'reason':decision.reason})
        if not decision.allowed:return
        limit=signal.limit_price
        if limit is not None:limit=tick_price(limit,rule.tick_for(limit),side==Side.SELL)
        order=Order(symbol,side,q,signal.strategy,timestamp,index+self.settings.execution.delay_bars,
                    signal.order_type,limit)
        self.submit(order)

class SimulationBroker:
    """Bar model with bounded prior-volume/book capacity; no private API."""
    def __init__(self,settings):self.settings=settings

    def process(self,execution,index,bars,previous_volumes,portfolio,risk,quotes=None):
        prices={s:b.open for s,b in bars.items()};c=self.settings.execution
        used={}
        for order in execution.orders:
            if order.status in TERMINAL or index<order.eligible_bar:continue
            if risk.killed and order.side==Side.BUY:
                execution.cancel(order,'kill_switch');continue
            if index>=order.eligible_bar+c.expiry_bars:
                execution.cancel(order,'expired');continue
            b=bars[order.symbol];rule=self.settings.rules_for(order.symbol)
            buy=order.side==Side.BUY
            quote=quotes.get(order.symbol) if quotes else None
            reference=dec((quote.ask if buy else quote.bid) if quote else b.open)
            raw_price=reference*(1+dec(c.slippage_bps)/10000*(1 if buy else -1))
            price=tick_price(raw_price,rule.tick_for(raw_price),buy)
            if order.order_type==OrderType.LIMIT:
                if (buy and price>order.limit_price) or (not buy and price<order.limit_price):continue
            slippage_bps=abs(price/dec(b.open)-1)*10000
            decision=risk.check(order.side,slippage_bps)
            if not decision.allowed:
                order.transition(Status.REJECTED,decision.reason);continue
            capacity=dec(previous_volumes.get(order.symbol,0))*dec(c.max_volume_participation)-used.get(order.symbol,Decimal(0))
            if quote:
                book_capacity=dec(quote.ask_quantity if buy else quote.bid_quantity)*dec(self.settings.paper_trading.max_book_participation)
                capacity=min(capacity,book_capacity-used.get(order.symbol,Decimal(0)))
            q=min(order.remaining,max(Decimal(0),capacity))
            if buy:q=min(q,risk.buy_capacity(order.symbol,portfolio,prices,price,c.fee_rate))
            else:q=min(q,portfolio.quantity(order.symbol))
            q=floor_step(q,rule.quantity_step)
            if order.remaining<dec(rule.min_quantity) and order.filled==0:
                order.transition(Status.REJECTED,'min_quantity');continue
            if q<=0:
                if capacity>0:execution.cancel(order,'cash_or_position_or_risk_capacity')
                continue
            if q*price<dec(rule.min_notional) and order.filled==0 and order.remaining*price<dec(rule.min_notional):
                order.transition(Status.REJECTED,'min_notional');continue
            fee=ledger(q*price*dec(c.fee_rate))
            order.fills_seen+=1
            fill=Fill(order.id,b.timestamp,order.symbol,order.strategy,order.side,q,price,fee,
                      ledger(q*abs(price-dec(b.open))),f'paper:{order.id}:{order.fills_seen}')
            portfolio.apply(fill,prices)
            used[order.symbol]=used.get(order.symbol,Decimal(0))+q
            order.filled+=q
            order.transition(Status.FILLED if order.remaining<dec(rule.quantity_step)/2 else Status.PARTIALLY_FILLED)
            risk.observe(b.timestamp,portfolio.equity(prices),portfolio.trades,portfolio.trade_offset)
