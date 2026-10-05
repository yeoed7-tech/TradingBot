from .base_strategy import Strategy
from trading_bot.core.events.models import Signal

class StrategyPortfolio(Strategy):
    """Weighted targets, with each sleeve's last target retained across HOLD.

    Net-position accounting only; per-sleeve PnL attribution is a later feature.
    """
    def __init__(self, sleeves):
        if not sleeves or any(w < 0 for w,_ in sleeves) or sum(w for w,_ in sleeves)>1+1e-12:
            raise ValueError('nonnegative sleeve weights must sum to <= 1')
        self.sleeves=sleeves
        self.targets={}

    def on_data(self,bars):
        for i,(_,strategy) in enumerate(self.sleeves):
            for signal in strategy.on_data(bars):
                if signal.target_weight is not None:
                    self.targets[i,signal.symbol]=signal.target_weight
        return [Signal(s,sum(w*self.targets.get((i,s),0.) for i,(w,_) in enumerate(self.sleeves)),
                       'ensemble','weighted sleeve targets') for s in bars]
