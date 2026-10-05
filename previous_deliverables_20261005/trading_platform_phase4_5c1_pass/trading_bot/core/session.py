"""Core state and strategy dispatch shared by historical and paper orchestration."""
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.core.risk.engine import RiskEngine
from trading_bot.core.execution.engine import ExecutionEngine,SimulationBroker
from trading_bot.monitoring.events import EventJournal

class TradingSession:
    def __init__(self,settings,strategy,*,operational=False):
        if strategy.__class__.__name__=='VolatilityBreakout' and settings.bar_seconds!=86400:
            raise ValueError('breakout requires daily candles')
        self.settings=settings
        self.strategy=strategy
        limit=settings.persistence.recent_cache_limit if operational else None
        self.portfolio=Portfolio(settings.initial_cash,history_limit=limit)
        self.risk=RiskEngine(settings.risk,settings.initial_cash,history_limit=limit)
        self.execution=ExecutionEngine(settings,history_limit=limit)
        self.broker=SimulationBroker(settings)
        self.journal=EventJournal(max_events=limit if operational else None)

    def signals(self,bars):
        signals=self.strategy.on_data(bars, portfolio=self.portfolio)
        if len({s.symbol for s in signals})!=len(signals): raise ValueError('one target per symbol required')
        if any(s.symbol not in bars for s in signals): raise ValueError('signal contains unknown symbol')
        return sorted(signals,key=lambda s:0 if s.target_weight==0 else 1)

    def submit_signals(self,signals,prices,timestamp,index):
        for signal in signals:
            self.journal.record('signal',timestamp=timestamp,**signal.__dict__)
            self.execution.propose(signal,self.portfolio,prices,self.risk,timestamp,index)
