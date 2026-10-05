"""Paper engine accepts DATA ONLY; owns the same core session as BacktestEngine."""
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json
from collections import deque
from trading_bot.core.session import TradingSession
from trading_bot.core.events.models import Bar,TERMINAL
from trading_bot.core.events.market import FeedEvent,FeedState,InvalidMarketData,validate_bar
from trading_bot.core.exchange.upbit_public import TIMEFRAMES
from trading_bot.config.settings import Settings

class PaperTradingEngine:
    def __init__(self,settings,strategy,*,clock=None):
        p=settings.paper_trading
        values=settings.model_dump()
        values['initial_cash']=p.starting_cash
        values['bar_seconds']=TIMEFRAMES[p.timeframe]
        values['execution']['fee_rate']=p.fee_rate
        values['execution']['slippage_bps']=p.slippage_bps
        values['symbol_rules'][p.symbol]=p.market_rules.model_dump()
        self.settings=Settings.model_validate(values)
        self.session=TradingSession(self.settings,strategy,operational=True)
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.state=FeedState.DISCONNECTED
        self.last_bar=None
        self.last_quote=None
        self.last_quote_timestamp=None
        self.index=-1
        self.volumes={}
        self.snapshots=deque(maxlen=settings.persistence.recent_cache_limit)
        self.minimum_drawdown=0
        self.processed_bars=0
        self.normal_events=0

    @property
    def portfolio(self): return self.session.portfolio
    @property
    def risk(self): return self.session.risk
    @property
    def execution(self): return self.session.execution

    def pause(self,state,reason):
        self.state=state
        for order in self.execution.orders: self.execution.cancel(order,'feed_paused:'+reason)
        if state in {FeedState.FAILED,FeedState.INVALID_DATA}: self.risk.kill(reason)
        self.session.journal.record('feed_status',timestamp=self.clock(),state=state,reason=reason)

    def consume(self,event: FeedEvent):
        if not isinstance(event,FeedEvent): raise TypeError('paper consumes FeedEvent, not exchange objects')
        if event.state!=FeedState.NORMAL:
            self.pause(event.state,event.reason); return
        now=self.clock(); cfg=self.settings.paper_trading
        q=event.quote
        if q is None:
            self.pause(FeedState.STALE_DATA,'no executable quote'); return
        if q.symbol!=cfg.symbol:
            self.pause(FeedState.INVALID_DATA,'unexpected quote symbol'); return
        age=(now-q.timestamp).total_seconds()
        if age < -cfg.clock_skew_tolerance or (now-event.observed_at).total_seconds() < -cfg.clock_skew_tolerance:
            self.pause(FeedState.INVALID_DATA,'future event timestamp'); return
        if age>cfg.quote_max_age or (now-event.observed_at).total_seconds()>cfg.quote_max_age:
            self.pause(FeedState.STALE_DATA,'stale quote/event at execution'); return
        fresh=[]
        try:
            by_time={}
            for b in event.bars:
                validate_bar(b)
                if b.symbol!=cfg.symbol: raise InvalidMarketData('unexpected bar symbol')
                if int(b.timestamp.timestamp())%self.settings.bar_seconds: raise InvalidMarketData('unaligned bar')
                if b.timestamp+timedelta(seconds=self.settings.bar_seconds)>now:
                    raise InvalidMarketData('unfinished candle')
                if b.timestamp in by_time and by_time[b.timestamp]!=b: raise InvalidMarketData('conflicting bar')
                by_time[b.timestamp]=b
            fresh=[by_time[t] for t in sorted(by_time) if self.last_bar is None or t>self.last_bar.timestamp]
            previous=self.last_bar.timestamp if self.last_bar else None
            previous_close=self.last_bar.close if self.last_bar else None
            for b in fresh:
                reference=previous_close if previous_close is not None else b.open
                if abs(b.close/reference-1)>self.risk.config.max_price_jump:
                    raise InvalidMarketData("abnormal completed candle price")
                previous_close=b.close
                if previous and (b.timestamp-previous).total_seconds()!=self.settings.bar_seconds:
                    self.pause(FeedState.GAP,'noncontiguous consumer input'); return
                previous=b.timestamp
            latest=fresh[-1] if fresh else self.last_bar
            if latest is None or (now-latest.timestamp).total_seconds()-self.settings.bar_seconds>cfg.stale_data_timeout:
                self.pause(FeedState.STALE_DATA,'stale completed candle'); return
            if abs(q.mid/latest.close-1)>self.risk.config.max_price_jump or (self.last_quote is not None and abs(q.mid/self.last_quote.mid-1)>self.risk.config.max_price_jump):
                raise InvalidMarketData('abnormal quote price')
        except (ValueError,TypeError) as exc:
            self.pause(FeedState.INVALID_DATA,str(exc)); return
        # Repeated exchange book timestamps cannot refill top-of-book liquidity.
        duplicate_quote=self.last_quote_timestamp is not None and q.timestamp<=self.last_quote_timestamp
        if duplicate_quote:
            self.session.journal.record('duplicate_quote',timestamp=q.timestamp)
            if not fresh: return
        if event.recovered or self.state!=FeedState.NORMAL:
            for order in self.execution.orders: self.execution.cancel(order,'recovery_requires_new_decision')
        self.state=FeedState.NORMAL
        self.normal_events+=1
        prices={q.symbol:q.mid}
        mark=Bar(now,q.symbol,q.mid,q.mid,q.mid,q.mid,0)
        self.risk.check_open({q.symbol:mark})
        self.risk.observe(now,self.portfolio.equity(prices),self.portfolio.trades,self.portfolio.trade_offset)
        latest_signals=[]
        for b in fresh:
            self.index+=1
            self.risk.observe_bars({b.symbol:b})
            latest_signals=self.session.signals({b.symbol:b})
            self.last_bar=b
            self.volumes[b.symbol]=b.volume
            self.processed_bars+=1
            self.session.journal.record('market_data',**asdict(b))
        # Current quote only. Never call the broker against recovered historical opens.
        # delay_bars=1 means the first quote AFTER decision creation can execute.
        if self.last_quote is not None and not duplicate_quote:
            self.session.broker.process(self.execution,self.index+1,{q.symbol:mark},self.volumes,
                                        self.portfolio,self.risk,{q.symbol:q})
        if fresh and event.decision_allowed and not duplicate_quote:
            self.session.submit_signals(latest_signals,prices,now,self.index)
        if not duplicate_quote:
            self.last_quote=q
            self.last_quote_timestamp=q.timestamp
        snapshot={'timestamp':now.isoformat(),'feed_state':str(self.state),**self.portfolio.snapshot(prices),
                  'drawdown':self.portfolio.equity(prices)/self.risk.peak-1,'risk_killed':self.risk.killed}
        self.snapshots.append(snapshot)
        self.minimum_drawdown=min(self.minimum_drawdown,snapshot['drawdown'])
        self.session.journal.record('portfolio',**snapshot)
        self.session.journal.record('quote',**asdict(q))

    async def run(self,feed,max_events=None):
        seen=0
        try:
            async for event in feed:
                self.consume(event)
                seen+=1
                if self.state==FeedState.FAILED or (max_events is not None and seen>=max_events): break
        finally:
            for order in self.execution.orders: self.execution.cancel(order,'paper_run_ended')
        return self.summary()

    def summary(self):
        return {'mode':'paper','status':str(self.state),'processed_bars':self.processed_bars,
                'normal_events':self.normal_events,'simulated_orders':self.execution.order_count,
                'simulated_fills':self.portfolio.fill_count,'risk_killed':self.risk.killed,
                'kill_reason':self.risk.kill_reason,'last_snapshot':self.snapshots[-1] if self.snapshots else None,
                'cache_sizes':{'orders':len(self.execution.orders),'fills':len(self.portfolio.fills),
                    'events':len(self.session.journal.events),'snapshots':len(self.snapshots),
                    'trades':len(self.portfolio.trades),'execution_events':len(self.execution.events),
                    'risk_events':len(self.risk.events)},
                'cache_limit':self.settings.persistence.recent_cache_limit,
                'position_cost_basis':{s:p.cost for s,p in self.portfolio.positions.items() if p.quantity>0},
                'open_orders':[o.id for o in self.execution.orders if o.status not in TERMINAL],
                'risk_state':{'peak':self.risk.peak,'day_start':self.risk.day_start,
                              'week_start':self.risk.week_start,'killed':self.risk.killed},
                'market_cursor':self.last_bar.timestamp.isoformat() if self.last_bar else None,
                'execution_backend':'SimulationBroker',
                'return':(self.snapshots[-1]['equity']/self.portfolio.initial_cash-1) if self.snapshots else None,
                'max_drawdown':self.minimum_drawdown}

    def save(self,directory,extra=None):
        out=Path(directory);out.mkdir(parents=True,exist_ok=True)
        def write(name,value):
            (out/name).write_text(json.dumps(value,default=str,indent=2,allow_nan=False),encoding='utf-8')
        write('summary.json',{**self.summary(),**(extra or {})})
        write('config.json',self.settings.model_dump())
        write('orders.json',[asdict(o) for o in self.execution.orders])
        write('fills.json',list(self.portfolio.fills))
        write('snapshots.json',list(self.snapshots))
        for f in self.portfolio.fills: self.session.journal.record('execution',**f)
        for e in [*self.execution.events,*self.risk.events]:self.session.journal.events.append(e)
        self.session.journal.save(out/'events.jsonl')
