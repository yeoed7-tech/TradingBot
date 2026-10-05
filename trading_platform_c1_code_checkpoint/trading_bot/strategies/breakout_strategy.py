from .base_strategy import Strategy, register
from trading_bot.core.events.models import Signal

@register('breakout')
class VolatilityBreakout(Strategy):
    """Daily close-confirmed breakout; next-bar execution, not intraday touch fill."""
    def __init__(self,k=0.5,weight=0.4):
        if not 0 < k <= 2 or not 0 < weight <= 1:
            raise ValueError('invalid breakout parameters')
        self.k,self.weight,self.previous = k,weight,{}

    def snapshot_state(self):
        from dataclasses import asdict
        return {k:{**asdict(v),"timestamp":v.timestamp.isoformat()} for k,v in self.previous.items()}

    def restore_state(self,state):
        from datetime import datetime
        from trading_bot.core.events.models import Bar
        self.previous={k:Bar(datetime.fromisoformat(v["timestamp"]),v["symbol"],v["open"],v["high"],v["low"],v["close"],v["volume"]) for k,v in state.items()}

    def on_data(self,bars):
        result=[]
        for symbol,b in bars.items():
            prev=self.previous.get(symbol)
            target=None if prev is None else (self.weight if b.close > b.open+self.k*(prev.high-prev.low) else 0.)
            result.append(Signal(symbol,target,'breakout','daily close-confirmed breakout'))
            self.previous[symbol]=b
        return result
