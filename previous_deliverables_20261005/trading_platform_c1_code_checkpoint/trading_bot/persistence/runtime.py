"""Durable paper coordinator. Never receives exchange order methods."""
import asyncio
from sqlalchemy import select, func
from trading_bot.core.events.market import FeedState
from trading_bot.persistence.ledger import PaperLedger, ReconciliationRequired
from trading_bot.persistence.models import AccountRow, PositionRow, OrderRow, RiskStateRow, FillRow, MarketCursorRow
from trading_bot.paper_trading.engine import PaperTradingEngine

class SimulationStateProvider:
    def __init__(self,engine):self.engine=engine
    def snapshot(self):
        p=self.engine.portfolio
        return {'cash':p.cash,'positions':{s:(x.quantity,x.cost) for s,x in p.positions.items() if x.quantity>0},
                'orders':{o.id:(o.status.value,o.filled) for o in self.engine.execution.orders},
                'order_count':self.engine.execution.order_count,
                'risk_killed':self.engine.risk.killed,
                'realized':p.realized_total,'fees':p.fees_total,
                'fill_count':p.fill_count,'cursor':self.engine.last_bar.timestamp.isoformat() if self.engine.last_bar else None,
                'risk_peak':self.engine.risk.peak,'risk_day_start':self.engine.risk.day_start,
                'risk_week_start':self.engine.risk.week_start,'risk_trades_seen':self.engine.risk.trades_seen}

class ReconciliationEngine:
    def __init__(self,ledger,provider):self.ledger=ledger;self.provider=provider
    def check(self):
        actual=self.provider.snapshot()
        with self.ledger.Session() as s:
            a=s.get(AccountRow,self.ledger.account)
            positions={p.symbol:(p.quantity,p.cost) for p in s.scalars(select(PositionRow).where(PositionRow.account==self.ledger.account)) if p.quantity>0}
            identifiers=list(actual['orders'])
            orders={o.internal_order_id:(o.status,o.filled) for o in s.scalars(
                select(OrderRow).where(OrderRow.internal_order_id.in_(identifiers)))} if identifiers else {}
            active={o.internal_order_id for o in s.scalars(select(OrderRow).where(
                OrderRow.status.in_(['CREATED','SUBMITTED','PARTIALLY_FILLED'])))}
            order_count=s.scalar(select(func.count(OrderRow.internal_order_id))) or 0
            risk=s.get(RiskStateRow,self.ledger.account)
            cfg=self.provider.engine.settings.paper_trading
            cursor=s.get(MarketCursorRow,(cfg.exchange,cfg.symbol,cfg.timeframe))
            expected={'cash':a.cash,'positions':positions,'orders':orders,
                      'risk_killed':risk.killed if risk else False,
                      'realized':a.realized_pnl,'fees':a.fees,
                      'fill_count':a.fill_count,'order_count':order_count,
                      'cursor':cursor.timestamp if cursor else None,
                      'risk_peak':risk.peak if risk else self.provider.engine.risk.peak,
                      'risk_day_start':risk.day_start if risk else self.provider.engine.risk.day_start,
                      'risk_week_start':risk.week_start if risk else self.provider.engine.risk.week_start,
                      'risk_trades_seen':risk.trades_seen if risk else self.provider.engine.risk.trades_seen}
        if any(expected[k]!=actual[k] for k in ('cash','realized','fees','risk_peak','risk_day_start','risk_week_start','fill_count','order_count','risk_trades_seen','cursor','risk_killed','orders','positions')) or not active.issubset(set(identifiers)):
            raise ReconciliationRequired('paper broker/account state differs from database')
        return True

class PaperOutboxStatusProvider:
    """Paper CREATED intents have no broker submission; cancel after inspection.

    Any other unknown state remains unresolved and halts. This is deliberately
    not a live exchange status provider.
    """
    def __init__(self,ledger):self.ledger=ledger
    def status(self,identifier):
        with self.ledger.Session() as s:
            row=s.scalar(select(OrderRow).where(OrderRow.client_order_id==identifier))
            return 'CANCELLED' if row and row.status=='CREATED' else None

class DurablePaperTrading:
    def __init__(self,settings,strategy_factory,ledger):
        self.settings=settings;self.strategy_factory=strategy_factory;self.ledger=ledger
        strategy=strategy_factory()
        from trading_bot.persistence.lease import WriterLease
        self.lease=None
        if settings.persistence.single_writer:
            self.lease=WriterLease(ledger,settings.strategy.name,ttl=settings.persistence.lease_ttl)
            self.lease.acquire()
            ledger.lease=self.lease
        identity=f'{type(strategy).__module__}:{type(strategy).__qualname__}'
        try:self.run_id=ledger.start_run(settings,strategy_version=identity)
        except BaseException:
            if self.lease:self.lease.release()
            raise
        self.engine=PaperTradingEngine(settings,strategy)
        ledger.reconcile_outbox(PaperOutboxStatusProvider(ledger))
        self.cursor_ms=ledger.restore(self.engine,self.run_id)
        self.engine.execution.intent_writer=lambda order:ledger.intent(self.run_id,order)
        self.reconciler=ReconciliationEngine(ledger,SimulationStateProvider(self.engine))
        self.blocked=False
        self.reconciler.check()
        if ledger.unresolved_intents():
            # A prior paper intent with no known result requires inspection.
            self.block('unknown outbox status after restart')

    def block(self,reason,*,latch=True):
        self.blocked=True
        self.engine.pause(FeedState.RECONCILIATION_REQUIRED,reason)
        self.ledger.event('RECONCILIATION_ERROR',reason,'ERROR',run_id=self.run_id)
        with self.ledger.Session.begin() as s:
            from trading_bot.persistence.models import StrategyRun
            s.get(StrategyRun,self.run_id).status='RECONCILIATION_REQUIRED' if latch else 'PAUSED'

    def consume(self,event,*,fault=None):
        if self.blocked:return
        try:
            self.reconciler.check()
        except ReconciliationRequired as exc:
            self.block(str(exc))
            raise
        try:
            if self.lease:self.lease.renew()
            self.engine.consume(event)
            self.ledger.checkpoint(self.run_id,self.engine,event,fault=fault)
            if self.lease:
                self.lease.heartbeat('strategy')
                if event.quote is not None:self.lease.heartbeat('market_feed')
        except Exception as exc:
            # No further decision using a dirty in-memory state.
            self.block(f'checkpoint failed: {type(exc).__name__}',latch=False)
            raise
        if self.engine.state in {FeedState.DISCONNECTED,FeedState.GAP,FeedState.STALE_DATA,FeedState.FAILED,FeedState.INVALID_DATA}:
            self.ledger.event(self.engine.state.value,'feed paused','WARNING',run_id=self.run_id)

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(self.lease.ttl/3)
            try:self.lease.renew()
            except Exception as exc:
                self.block(f'heartbeat lost: {type(exc).__name__}',latch=False)
                raise

    async def run(self,feed,max_events=None,*,heartbeat_task=None):
        if self.cursor_ms is not None:
            feed.last_ms=self.cursor_ms
        n=0
        heartbeat=heartbeat_task or (asyncio.create_task(self._heartbeat_loop()) if self.lease else None)
        owns_heartbeat=heartbeat is not None and heartbeat is not heartbeat_task
        try:
            async for event in feed:
                if heartbeat and heartbeat.done():
                    heartbeat.result() # fail closed
                self.consume(event)
                n+=1
                if self.blocked or self.engine.state==FeedState.FAILED or (max_events and n>=max_events):break
        finally:
            if owns_heartbeat:
                heartbeat.cancel()
                try:await heartbeat
                except asyncio.CancelledError:pass
        return self.engine.summary()
