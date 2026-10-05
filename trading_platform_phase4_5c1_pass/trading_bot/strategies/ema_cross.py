from .base_strategy import Strategy, register
from trading_bot.core.events.models import Signal

@register('ema_cross')
class EMACross(Strategy):
    def __init__(self, fast=20, slow=100, weight=0.4):
        if not isinstance(fast,int) or not isinstance(slow,int) or not 1 <= fast < slow or not 0 < weight <= 1:
            raise ValueError('require integer 1 <= fast < slow and 0 < weight <= 1')
        self.fast, self.slow, self.weight, self.state = fast, slow, weight, {}

    def snapshot_state(self):return {k:list(v) for k,v in self.state.items()}

    def restore_state(self,state):self.state={k:tuple(v) for k,v in state.items()}

    def on_data(self, bars):
        result = []
        for symbol, b in bars.items():
            f, s, n = self.state.get(symbol, (b.close,b.close,0))
            f += 2 / (self.fast + 1) * (b.close - f)
            s += 2 / (self.slow + 1) * (b.close - s)
            n += 1
            self.state[symbol] = (f,s,n)
            target = None if n < self.slow else (self.weight if f > s else 0.0)
            result.append(Signal(symbol,target,'ema_cross','EMA trend regime'))
        return result
