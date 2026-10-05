from dataclasses import dataclass
from collections import deque
from decimal import Decimal
from trading_bot.core.events.models import Side
from trading_bot.core.portfolio.precision import dec, floor_step

@dataclass(frozen=True)
class Decision:
    allowed:bool
    reason:str

class RiskEngine:
    def __init__(self,config,initial_cash,history_limit=None):
        self.config=config
        self.peak=dec(initial_cash);self.last_equity=dec(initial_cash)
        self.day=self.week=None
        self.day_start=self.week_start=dec(initial_cash)
        self.killed=False;self.kill_reason=''
        self.consecutive_losses=0;self.trades_seen=0
        self.tr={};self.previous_close={};self.events=deque(maxlen=history_limit) if history_limit else []

    def kill(self,reason):
        if not self.killed:
            self.killed=True;self.kill_reason=reason
            self.events.append({'event':'kill_switch','reason':reason})

    def observe(self,timestamp,equity,trades,trade_offset=0):
        equity=dec(equity)
        day=timestamp.date();week=timestamp.isocalendar()[:2]
        if day!=self.day:self.day,self.day_start=day,self.last_equity
        if week!=self.week:self.week,self.week_start=week,self.last_equity
        self.peak=max(self.peak,equity)
        start=max(0,self.trades_seen-trade_offset)
        for trade in list(trades)[start:]:
            self.consecutive_losses=self.consecutive_losses+1 if trade['pnl']<0 else 0
        self.trades_seen=trade_offset+len(trades)
        c=self.config
        if equity<=0:self.kill('nonpositive_equity')
        elif equity/self.peak-1<=-dec(c.max_drawdown):self.kill('max_drawdown')
        elif equity/self.day_start-1<=-dec(c.daily_loss):self.kill('daily_loss')
        elif equity/self.week_start-1<=-dec(c.weekly_loss):self.kill('weekly_loss')
        elif self.consecutive_losses>=c.max_consecutive_losses:self.kill('consecutive_losses')
        self.last_equity=equity

    def check_open(self,bars):
        for symbol,b in bars.items():
            prev=self.previous_close.get(symbol)
            if prev is not None and abs(b.open/prev-1)>self.config.max_price_jump:
                self.kill(f'abnormal_open:{symbol}')

    def observe_bars(self,bars):
        for symbol,b in bars.items():
            prev=self.previous_close.get(symbol,b.open)
            if abs(b.close/prev-1)>self.config.max_price_jump:self.kill(f'abnormal_close:{symbol}')
            tr=max(b.high-b.low,abs(b.high-prev),abs(b.low-prev))
            self.tr.setdefault(symbol,deque(maxlen=self.config.atr_period)).append(tr)
            self.previous_close[symbol]=b.close

    def target_weight(self,symbol,requested,price):
        c=self.config
        if c.sizing=='fixed_fractional':cap=c.fixed_fraction
        else:
            values=self.tr.get(symbol,())
            if len(values)<c.atr_period:return 0.
            atr=sum(values)/len(values)
            cap=0. if atr<=0 else c.risk_per_trade*price/(c.atr_multiple*atr)
        return max(0.,min(requested,cap,c.max_symbol_weight))

    def buy_capacity(self,symbol,portfolio,prices,fill_price,fee_rate):
        equity=portfolio.equity(prices);c=self.config
        mark=dec(prices[symbol]);price=dec(fill_price);fee=dec(fee_rate)
        own=portfolio.quantity(symbol)*mark;gross=portfolio.gross(prices)
        delta=mark-price*(1+fee)
        symbol_room=(dec(c.max_symbol_weight)*equity-own)/(mark-dec(c.max_symbol_weight)*delta)
        gross_room=(dec(c.max_gross_weight)*equity-gross)/(mark-dec(c.max_gross_weight)*delta)
        return max(Decimal(0),min(portfolio.cash/(price*(1+fee)),symbol_room,gross_room))

    def check(self,side,slippage_bps=0):
        if dec(slippage_bps)>dec(self.config.max_slippage_bps):self.kill('excess_slippage')
        if side==Side.BUY and self.killed:return Decision(False,self.kill_reason)
        return Decision(True,'reduce_exposure' if side==Side.SELL else 'approved')
