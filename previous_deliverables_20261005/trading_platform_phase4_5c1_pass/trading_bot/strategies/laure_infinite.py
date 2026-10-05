from .base_strategy import Strategy, register
from trading_bot.core.events.models import Signal

@register('laure')
class LaureInfiniteStrategy(Strategy):
    """
    Laure's Infinite Buying Method (라오어 무한매수법) for Crypto.
    Divides capital into `parts` and buys 1 part every `interval_seconds`.
    Sells all (target=0.0) when current profit >= `profit_target`.
    """
    def __init__(self, parts=40, profit_target=0.10, interval_seconds=86400):
        if not isinstance(parts, int) or parts <= 0:
            raise ValueError("parts must be a positive integer")
        if not (0 < profit_target < 100):
            raise ValueError("profit_target must be between 0 and 100")
        
        self.parts = parts
        self.profit_target = profit_target
        self.interval_seconds = interval_seconds
        self.state = {}

    def snapshot_state(self):
        return {k: dict(v) for k, v in self.state.items()}

    def restore_state(self, state):
        self.state = {k: dict(v) for k, v in state.items()}

    def on_data(self, bars, portfolio=None):
        signals = []
        for symbol, b in bars.items():
            st = self.state.setdefault(symbol, {'last_buy_ts': 0, 'parts_filled': 0})
            
            # 1. Take Profit Check
            if portfolio:
                pos = portfolio.positions.get(symbol)
                # If position doesn't exist or we hit 0 quantity manually, reset
                if not pos or pos.quantity <= 0:
                    if st['parts_filled'] > 0:
                        st['parts_filled'] = 0
                else:
                    avg_cost = float(pos.cost / pos.quantity)
                    profit = (b.close / avg_cost) - 1.0
                    
                    if profit >= self.profit_target:
                        signals.append(Signal(symbol, 0.0, 'laure', f'Take profit at {profit*100:.2f}%'))
                        st['parts_filled'] = 0
                        continue
            
            # 2. Infinite Buying Schedule
            now_ts = b.timestamp.timestamp()
            if st['parts_filled'] < self.parts:
                if (now_ts - st['last_buy_ts']) >= self.interval_seconds:
                    st['parts_filled'] += 1
                    st['last_buy_ts'] = now_ts
                    
                    target = st['parts_filled'] / self.parts
                    signals.append(Signal(symbol, target, 'laure', f'Buy part {st["parts_filled"]}/{self.parts}'))
            
        return signals
