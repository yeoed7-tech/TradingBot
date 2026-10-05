from .base_strategy import Strategy, register
from trading_bot.core.events.models import Signal

@register('rsi')
class RSIMeanReversion(Strategy):
    def __init__(self, period=14, lower=30, upper=70, weight=0.4):
        if not isinstance(period,int) or period < 2 or not 0 < lower < upper < 100 or not 0 < weight <= 1:
            raise ValueError('invalid RSI parameters')
        self.period,self.lower,self.upper,self.weight = period,lower,upper,weight
        self.state = {}

    def snapshot_state(self):return {k:dict(v) for k,v in self.state.items()}

    def restore_state(self,state):self.state={k:dict(v) for k,v in state.items()}

    def on_data(self, bars, portfolio=None):
        result = []
        for symbol,b in bars.items():
            s = self.state.setdefault(symbol, {'last':b.close,'g':0.,'l':0.,'n':0,'target':0.})
            delta = b.close - s['last']
            if s['n'] > 0:
                g,l = max(delta,0),max(-delta,0)
                if s['n'] <= self.period:
                    s['g'] += g / self.period
                    s['l'] += l / self.period
                else:
                    s['g'] = (s['g']*(self.period-1)+g)/self.period
                    s['l'] = (s['l']*(self.period-1)+l)/self.period
            s['last'],s['n'] = b.close,s['n']+1
            target = None
            if s['n'] > self.period:
                rsi = 50 if s['g'] == s['l'] == 0 else (100 if s['l'] == 0 else 100-100/(1+s['g']/s['l']))
                if rsi < self.lower: s['target'] = self.weight
                if rsi > self.upper: s['target'] = 0.
                target = s['target']
            result.append(Signal(symbol,target,'rsi','Wilder RSI hysteresis'))
        return result
