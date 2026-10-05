from dataclasses import dataclass
from datetime import timedelta
import pandas as pd
from trading_bot.data.feeds import HistoricalFeed
from trading_bot.core.session import TradingSession
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.core.risk.engine import RiskEngine
from trading_bot.core.execution.engine import ExecutionEngine, SimulationBroker
from trading_bot.monitoring.events import EventJournal

@dataclass
class BacktestResult:
    equity: pd.DataFrame
    fills: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    journal: EventJournal
    settings: object
    label: str
    killed: bool
    kill_reason: str

class BacktestEngine:
    def __init__(self,settings): self.settings=settings

    def run(self,frame,strategy,label='strategy',trade_start=None):
        return self.run_feed(HistoricalFeed(frame,self.settings.bar_seconds),strategy,label,trade_start)

    def run_feed(self,data,strategy,label="strategy",trade_start=None):
        settings=self.settings
        if strategy.__class__.__name__=='VolatilityBreakout' and settings.bar_seconds!=86400:
            raise ValueError('breakout requires daily candles')
        session=TradingSession(settings,strategy)
        p,risk=session.portfolio,session.risk
        execution,broker,journal=session.execution,session.broker,session.journal
        rows=[]
        previous_volumes={}
        initial_prices=None
        benchmark_units=None
        start=pd.Timestamp(trade_start) if trade_start is not None else None
        if start is not None and start.tzinfo is None: start=start.tz_localize('UTC')
        active=False
        for i,(t,bars) in enumerate(data.batches()):
            eligible=start is None or pd.Timestamp(t)>=start
            if eligible and not active:
                active=True
                initial_prices={s:b.open for s,b in bars.items()}
                # Gross frictionless, equal-weight B&H reference, explicitly labeled.
                benchmark_units={s:settings.initial_cash/len(bars)/b.open for s,b in bars.items()}
                rows.append({'timestamp':t,'equity':p.cash,'cash':p.cash,'gross':0.,'benchmark':p.cash,
                             **{f'position:{s}':0. for s in bars}})
            opens={s:b.open for s,b in bars.items()}
            closes={s:b.close for s,b in bars.items()}
            if active:
                risk.check_open(bars)
                risk.observe(t,p.equity(opens),p.trades)
                broker.process(execution,i,bars,previous_volumes,p,risk)
            risk.observe_bars(bars)
            # End-of-bar events and signals occur at bar CLOSE, never before fills.
            end=t+timedelta(seconds=settings.bar_seconds)
            if active: risk.observe(end-timedelta(microseconds=1),p.equity(closes),p.trades)
            signals=session.signals(bars)
            if len({s.symbol for s in signals}) != len(signals): raise ValueError('one target per symbol required')
            if active:
                for s,b in bars.items(): journal.record('market_data',**b.__dict__)
                # Reduce before adding risk. Order execution at next open follows this order.
                signals=sorted(signals,key=lambda s: 0 if s.target_weight==0 else 1)
                for signal in signals:
                    journal.record('signal',timestamp=end,**signal.__dict__)
                    execution.propose(signal,p,closes,risk,end,i)
                row={'timestamp':end,'equity':p.equity(closes),'cash':p.cash,'gross':p.gross(closes),
                     'benchmark':sum(benchmark_units[s]*b.close for s,b in bars.items()),
                     **{f'position:{s}':p.quantity(s) for s in bars}}
                rows.append(row)
                journal.record('portfolio',**row)
            previous_volumes={s:b.volume for s,b in bars.items()}
        if not active: raise ValueError('trade_start is outside dataset')
        for o in execution.orders: execution.cancel(o,'end_of_data')
        for event in execution.events+risk.events: journal.events.append(event)
        for fill in p.fills: journal.record('execution',**fill)
        for o in execution.orders: journal.record('order',**o.__dict__)
        equity=pd.DataFrame(rows).set_index('timestamp')
        # Research/plotting boundary: accounting has already completed in Decimal.
        for column in equity.columns:equity[column]=equity[column].astype(float)
        return BacktestResult(equity,pd.DataFrame(p.fills),
            pd.DataFrame(p.trades),pd.DataFrame([o.__dict__ for o in execution.orders]),journal,settings,label,risk.killed,risk.kill_reason)
