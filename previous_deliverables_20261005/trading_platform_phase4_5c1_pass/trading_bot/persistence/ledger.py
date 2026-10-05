"""Paper ledger: committed checkpoints are the sole restart source of truth.

No method here can submit an exchange order. In a future live adapter, UNKNOWN
outbox rows require a status lookup by client_order_id before any transition.
"""
import hashlib
import json
from collections import deque, Counter
from datetime import datetime, timezone, date
from uuid import uuid4
from decimal import Decimal
from trading_bot.core.portfolio.precision import dec, ledger
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError
from alembic import command
from alembic.config import Config
from trading_bot.persistence.models import (Base,AccountRow,PositionRow,OrderRow,FillRow,SnapshotRow,
    RiskStateRow,MarketCursorRow,SignalRow,CandleRow,StrategyRun,SystemEventRow,TraderLease,HeartbeatRow)
from trading_bot.core.portfolio.engine import Portfolio, Position
from trading_bot.core.events.models import Fill, Side, Order, Status, OrderType, Bar
from trading_bot.core.events.market import Quote,FeedState

UTC=lambda: datetime.now(timezone.utc).isoformat()
def iso(t): return t.isoformat() if t is not None else None
def dt(t): return datetime.fromisoformat(t) if t is not None else None

def redact(value):
    sensitive=('secret','api_key','access_key','authorization','jwt','token','password','credential')
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(n in k.lower() for n in sensitive) else redact(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact(v) for v in value]
    if isinstance(value,str):
        import re
        value=re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._-]+',r'\1[REDACTED]',value)
        value=re.sub(r'(?i)((?:secret|api_key|access_key|authorization|jwt|password|token)\s*[:=]\s*)\S+',r'\1[REDACTED]',value)
    return value

def config_digest(strategy,risk):
    raw=json.dumps({'strategy':strategy,'risk':risk},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()

def db_engine(url):
    kw={'future':True,'pool_pre_ping':True}
    if url.startswith('sqlite:'):
        kw['connect_args']={'timeout':30}
    return create_engine(url,**kw)

def migrate(url):
    cfg=Config('alembic.ini')
    cfg.attributes['database_url']=url
    command.upgrade(cfg,'head')

class ReconciliationRequired(RuntimeError): pass

class PaperLedger:
    def __init__(self,url,account='paper'):
        self.engine=db_engine(url)
        self.Session=sessionmaker(self.engine,expire_on_commit=False)
        self.account=account
        self.lease=None

    def close(self): self.engine.dispose()

    def start_run(self,settings,strategy_version='1',resume=True):
        name=settings.strategy.name
        config=redact(settings.model_dump(mode='json'))
        digest=config_digest(config['strategy'],config['risk'])
        with self.Session.begin() as s:
            account=s.get(AccountRow,self.account)
            if account is None:
                s.add(AccountRow(account=self.account,cash=ledger(settings.paper_trading.starting_cash),
                    initial_cash=ledger(settings.paper_trading.starting_cash),realized_pnl=ledger(0),fees=ledger(0),fill_count=0))
            previous=s.scalar(select(StrategyRun).where(StrategyRun.mode=='PAPER',
                StrategyRun.status.in_(['RUNNING','PAUSED','RECONCILIATION_REQUIRED'])).order_by(StrategyRun.start_time.desc()))
            if resume and previous:
                if previous.status=='RECONCILIATION_REQUIRED':
                    raise ReconciliationRequired('reconciliation is latched; inspect and resolve before restart')
                if previous.config_hash!=digest or any(previous.config.get(k)!=config.get(k) for k in ('strategy','risk','execution')) or any(previous.config.get('paper_trading',{}).get(k)!=config['paper_trading'].get(k) for k in ('symbol','timeframe','fee_rate','slippage_bps','starting_cash','market_rules')) or previous.strategy_name!=name or previous.strategy_version!=strategy_version:
                    raise ReconciliationRequired('persistent paper account has different strategy/risk config')
                previous.status='RUNNING'
                previous.end_time=None
                run_id=previous.id
            else:
                if account is not None and not resume:
                    raise ReconciliationRequired('cannot reset a funded paper account without explicit archive')
                run_id=str(uuid4())
                s.add(StrategyRun(id=run_id,strategy_name=name,strategy_version=strategy_version,
                     config=config,config_hash=digest,start_time=UTC(),end_time=None,mode='PAPER',status='RUNNING'))
            s.add(SystemEventRow(timestamp=UTC(),level='INFO',component='runner',event='STARTUP',
                message='paper session started',context={},strategy_run_id=run_id))
        return run_id

    def event(self,kind,message='',level='INFO',component='paper',context=None,run_id=None):
        with self.Session.begin() as s:
            s.add(SystemEventRow(timestamp=UTC(),level=level,component=component,event=kind,
              message=redact(message),context=redact(context or {}),strategy_run_id=run_id))

    def intent(self,run_id,order,client_order_id=None,session=None):
        """Unique intent, persisted before simulation; duplicate client IDs return same row.

        UNKNOWN outcomes must be inspected through a status provider, never resent.
        """
        client_order_id=client_order_id or order.id
        def write(s):
            if self.lease is not None:self.lease.assert_owned(s)
            existing=s.scalar(select(OrderRow).where(OrderRow.client_order_id==client_order_id))
            if existing:
                if existing.internal_order_id!=order.id or existing.symbol!=order.symbol or existing.side!=order.side or existing.quantity!=order.quantity:
                    raise ValueError('client_order_id collision with different intent')
                return existing
            row=OrderRow(internal_order_id=order.id,client_order_id=client_order_id,exchange_order_id=None,
                strategy_run_id=run_id,strategy=order.strategy,symbol=order.symbol,side=order.side.value,
                order_type=order.order_type.value,quantity=order.quantity,price=order.limit_price,
                status='CREATED',filled=dec(0),fills_seen=0,eligible_bar=order.eligible_bar,reason='',
                created_at=iso(order.created_at),updated_at=UTC())
            s.add(row);s.flush()
            return row
        if session is not None:return write(session)
        with self.Session.begin() as s:return write(s)

    def unresolved_intents(self):
        with self.Session() as s:
            return [r.client_order_id for r in s.scalars(select(OrderRow).where(OrderRow.status.in_(['CREATED','UNKNOWN'])))]

    def reconcile_outbox(self,status_provider):
        """Status provider accepts identifier, returns status or None; never sends."""
        unresolved=self.unresolved_intents()
        for identifier in unresolved:
            remote=status_provider.status(identifier)
            if remote is None: raise ReconciliationRequired(f'unknown order status: {identifier}')
            with self.Session.begin() as s:
                row=s.scalar(select(OrderRow).where(OrderRow.client_order_id==identifier))
                row.status=remote;row.updated_at=UTC()

    def _restore_portfolio(self,s):
        a=s.get(AccountRow,self.account)
        p=Portfolio(a.initial_cash);p.cash=a.cash
        p.realized_total=a.realized_pnl;p.fees_total=a.fees;p.fill_count=a.fill_count
        for r in s.scalars(select(PositionRow).where(PositionRow.account==self.account)):
            p.positions[r.symbol]=Position(r.quantity,r.cost,dt(r.opened_at),r.realized_pnl,r.sold_quantity)
        return p

    def _write_portfolio(self,s,p,prices,run_id,timestamp,drawdown):
        a=s.get(AccountRow,self.account)
        a.cash=p.cash
        a.realized_pnl=p.realized_total
        a.fees=p.fees_total
        a.fill_count=p.fill_count
        for symbol,pos in p.positions.items():
            r=s.get(PositionRow,(self.account,symbol))
            if r is None:r=PositionRow(account=self.account,symbol=symbol,quantity=0,cost=0,
                     average_entry_price=0,realized_pnl=0,sold_quantity=0,updated_at=UTC());s.add(r)
            r.quantity=pos.quantity;r.cost=pos.cost
            r.average_entry_price=ledger(pos.cost/pos.quantity) if pos.quantity else dec(0)
            r.realized_pnl=pos.realized;r.opened_at=iso(pos.opened_at)
            r.sold_quantity=pos.sold_quantity;r.updated_at=UTC()
        snap=p.snapshot(prices)
        s.add(SnapshotRow(account=self.account,strategy_run_id=run_id,timestamp=iso(timestamp),
            cash=p.cash,market_value=ledger(snap['equity']-p.cash),equity=snap['equity'],
            realized_pnl=snap['realized_pnl'],unrealized_pnl=snap['unrealized_pnl'],
            fees=snap['fees'],drawdown=float(drawdown)))

    def apply_fill(self,run_id,fill_id,fill,prices,*,fault=None):
        """Exactly-once portfolio accounting; all writes share ONE transaction."""
        with self.Session.begin() as s:
            if self.lease is not None:self.lease.assert_owned(s)
            if s.get(FillRow,fill_id) is not None:return False
            order=s.get(OrderRow,fill.order_id)
            if order is None:raise ValueError('fill requires a recorded order intent')
            p=self._restore_portfolio(s)
            if fault=='before_fill':raise RuntimeError('injected before fill')
            realized=p.apply(fill,prices)
            s.add(FillRow(exchange_fill_id=fill_id,internal_order_id=fill.order_id,strategy_run_id=run_id,
                timestamp=iso(fill.timestamp),symbol=fill.symbol,side=fill.side.value,quantity=fill.quantity,
                price=fill.price,fee=fill.fee,slippage=fill.slippage,realized_pnl=realized))
            s.flush()
            if fault=='after_fill':raise RuntimeError('injected after fill')
            order.filled+=fill.quantity;order.fills_seen+=1
            order.status='FILLED' if order.filled>=order.quantity else 'PARTIALLY_FILLED'
            self._write_portfolio(s,p,prices,run_id,fill.timestamp,0)
            s.flush()
            if fault=='after_portfolio':raise RuntimeError('injected after portfolio')
        return True

    def checkpoint(self,run_id,engine,event,*,fault=None):
        """One market decision: orders, fills, account, risk and cursor commit together.

        The engine is in memory until commit. On any exception discard that engine,
        reopen from the previous committed cursor, and halt new decisions.
        """
        p=engine.portfolio;risk=engine.risk;cfg=engine.settings.paper_trading
        prices={cfg.symbol:engine.last_quote.mid} if engine.last_quote and engine.state==FeedState.NORMAL else {}
        with self.Session.begin() as s:
            if self.lease is not None:self.lease.assert_owned(s)
            existing=s.get(MarketCursorRow,(cfg.exchange,cfg.symbol,cfg.timeframe))
            previous=dt(existing.timestamp) if existing else None
            fresh=[b for b in event.bars if previous is None or b.timestamp>previous]
            for b in fresh:
                if s.scalar(select(CandleRow.id).where(CandleRow.exchange==cfg.exchange,
                    CandleRow.symbol==b.symbol,CandleRow.timeframe==cfg.timeframe,CandleRow.timestamp==iso(b.timestamp))):continue
                s.add(CandleRow(exchange=cfg.exchange,symbol=b.symbol,timeframe=cfg.timeframe,
                     timestamp=iso(b.timestamp),open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume))
            new_journal=[e for e in engine.session.journal.events if e.get('event')=='signal']
            # Cursor index counts completed bars; only signals for new market bars are recorded.
            for e in new_journal[-len(fresh):] if fresh else []:
                weight=e.get('target_weight')
                s.add(SignalRow(timestamp=iso(e.get('timestamp')),strategy=e.get('strategy',''),
                  strategy_run_id=run_id,symbol=e.get('symbol',cfg.symbol),
                  signal='HOLD' if weight is None else ('SELL' if weight==0 else 'BUY'),
                  target_position=weight,metadata_json=redact({'reason':e.get('reason','')}),mode='PAPER'))
            if fault=='before_order':raise RuntimeError('injected before order')
            for o in engine.execution.orders:
                row=s.get(OrderRow,o.id)
                if row is None:row=self.intent(run_id,o,session=s)
                row.status=o.status.value;row.filled=o.filled;row.fills_seen=o.fills_seen;row.reason=o.reason;row.updated_at=UTC()
            s.flush()
            if fault=='after_order':raise RuntimeError('injected after order')
            if fault=='kill_after_order':
                import os;os._exit(71)
            account=s.get(AccountRow,self.account)
            pending=p.fill_count-account.fill_count
            if pending<0 or pending>len(p.fills):
                raise ReconciliationRequired('fill cache does not cover pending accounting')
            for f in list(p.fills)[-pending:] if pending else ():
                fill_id=f.get('fill_id')
                if not fill_id:raise ReconciliationRequired('paper fill missing stable identifier')
                if s.get(FillRow,fill_id) is not None:continue
                s.add(FillRow(exchange_fill_id=fill_id,internal_order_id=f['order_id'],strategy_run_id=run_id,
                    timestamp=iso(f['timestamp']),symbol=f['symbol'],side=f['side'].value,
                    quantity=f['quantity'],price=f['price'],fee=f['fee'],slippage=f['slippage'],
                    realized_pnl=f['pnl']))
            s.flush()
            if fault=='after_fill':raise RuntimeError('injected after fill')
            if fault=='kill_after_fill':
                import os;os._exit(72)
            if prices:
                self._write_portfolio(s,p,prices,run_id,engine.clock(),p.equity(prices)/risk.peak-1)
            s.flush()
            if fault=='after_portfolio':raise RuntimeError('injected after portfolio')
            if fault=='kill_after_portfolio':
                import os;os._exit(73)
            state={'trade_offset':p.trade_offset,'trades':[{**t,'pnl':str(t['pnl']),'quantity':str(t['quantity']),
                'opened_at':iso(t['opened_at']),'closed_at':iso(t['closed_at'])} for t in p.trades],
                'tr':{k:list(v) for k,v in risk.tr.items()},'previous_close':risk.previous_close}
            day=iso(risk.day);week=json.dumps(risk.week) if risk.week is not None else None
            rr=s.get(RiskStateRow,self.account)
            newly_killed=risk.killed and (rr is None or not rr.killed)
            if rr is None:rr=RiskStateRow(account=self.account);s.add(rr)
            rr.killed=risk.killed;rr.kill_reason=risk.kill_reason
            rr.day=day;rr.week=week;rr.day_start=risk.day_start;rr.week_start=risk.week_start
            rr.peak=risk.peak;rr.last_equity=risk.last_equity
            rr.current_drawdown=float(risk.last_equity/risk.peak-1)
            rr.daily_loss_state=float(risk.last_equity/risk.day_start-1)
            rr.weekly_loss_state=float(risk.last_equity/risk.week_start-1)
            rr.consecutive_losses=risk.consecutive_losses;rr.trades_seen=risk.trades_seen;rr.state_json=state
            if engine.last_bar is not None:
                cursor=s.get(MarketCursorRow,(cfg.exchange,cfg.symbol,cfg.timeframe))
                if cursor is None:
                    cursor=MarketCursorRow(exchange=cfg.exchange,symbol=cfg.symbol,timeframe=cfg.timeframe)
                    s.add(cursor)
                cursor.timestamp=iso(engine.last_bar.timestamp)
                cursor.last_quote_timestamp=iso(engine.last_quote_timestamp)
                cursor.engine_index=engine.index;cursor.state=engine.state.value
                q=engine.last_quote
                cursor.strategy_state={'snapshot_version':1,'indicator':engine.session.strategy.snapshot_state(),
                    'last_quote':None if q is None else {'symbol':q.symbol,'timestamp':iso(q.timestamp),
                    'bid':q.bid,'ask':q.ask,'bid_quantity':q.bid_quantity,'ask_quantity':q.ask_quantity}}
            if newly_killed:
                s.add(SystemEventRow(timestamp=UTC(),level='CRITICAL',component='risk',event='KILL_SWITCH',
                    message=redact(risk.kill_reason),context={},strategy_run_id=run_id))

    def restore(self,engine,run_id):
        cfg=engine.settings.paper_trading
        with self.Session() as s:
            cursor=s.get(MarketCursorRow,(cfg.exchange,cfg.symbol,cfg.timeframe))
            account=s.get(AccountRow,self.account)
            engine.portfolio.cash=account.cash
            engine.portfolio.initial_cash=account.initial_cash
            engine.portfolio.realized_total=account.realized_pnl
            engine.portfolio.fees_total=account.fees
            engine.portfolio.fill_count=account.fill_count
            engine.minimum_drawdown=s.scalar(select(func.min(SnapshotRow.drawdown))
                .where(SnapshotRow.account==self.account)) or 0
            for row in s.scalars(select(PositionRow).where(PositionRow.account==self.account)):
                engine.portfolio.positions[row.symbol]=Position(row.quantity,row.cost,dt(row.opened_at),
                    row.realized_pnl,row.sold_quantity)
            limit=engine.settings.persistence.recent_cache_limit
            fills=list(s.scalars(select(FillRow).where(FillRow.strategy_run_id==run_id)
                .order_by(FillRow.timestamp.desc(),FillRow.exchange_fill_id.desc()).limit(limit)))
            for row in reversed(fills):
                engine.portfolio.fills.append({'order_id':row.internal_order_id,'timestamp':dt(row.timestamp),
                    'symbol':row.symbol,'side':Side(row.side),'quantity':row.quantity,'price':row.price,
                    'fee':row.fee,'slippage':row.slippage,'pnl':row.realized_pnl,'fill_id':row.exchange_fill_id})
            orders=list(s.scalars(select(OrderRow).where(OrderRow.strategy_run_id==run_id)
                .order_by(OrderRow.created_at.desc()).limit(limit)))
            active=list(s.scalars(select(OrderRow).where(OrderRow.strategy_run_id==run_id,
                OrderRow.status.in_(['CREATED','SUBMITTED','PARTIALLY_FILLED']))))
            seen={o.internal_order_id for o in orders}
            for o in active:
                if o.internal_order_id not in seen:orders.append(o)
            orders.sort(key=lambda o:(o.created_at,o.internal_order_id))
            engine.execution.order_count=s.scalar(select(func.count(OrderRow.internal_order_id))
                .where(OrderRow.strategy_run_id==run_id)) or 0
            for row in orders:
                o=Order(row.symbol,Side(row.side),row.quantity,row.strategy,dt(row.created_at),
                    row.eligible_bar,OrderType(row.order_type),row.price,id=row.internal_order_id,
                    status=Status(row.status),filled=row.filled,fills_seen=row.fills_seen,reason=row.reason)
                engine.execution.orders.append(o);engine.execution.ids.add(o.id)
            risk=s.get(RiskStateRow,self.account)
            if risk:
                r=engine.risk
                r.killed=risk.killed;r.kill_reason=risk.kill_reason;r.peak=risk.peak
                r.last_equity=risk.last_equity;r.day=date.fromisoformat(risk.day) if risk.day else None
                saved_week=json.loads(risk.week) if risk.week else None
                r.week=tuple(saved_week) if saved_week is not None else None
                r.day_start=risk.day_start;r.week_start=risk.week_start
                r.consecutive_losses=risk.consecutive_losses;r.trades_seen=risk.trades_seen
                state=risk.state_json
                r.tr={k:deque(v,maxlen=r.config.atr_period) for k,v in state['tr'].items()}
                r.previous_close=state['previous_close']
                engine.portfolio.trade_offset=state.get('trade_offset',0)
                for t in state['trades']:
                    engine.portfolio.trades.append({**t,'pnl':dec(t['pnl']),'quantity':dec(t['quantity']),
                        'opened_at':dt(t['opened_at']),'closed_at':dt(t['closed_at'])})
            if cursor:
                saved=cursor.strategy_state or {}
                indicator=saved.get('indicator')
                if saved.get('snapshot_version')==1 and indicator is not None:
                    engine.session.strategy.restore_state(indicator)
                    latest=s.scalar(select(CandleRow).where(CandleRow.exchange==cfg.exchange,
                        CandleRow.symbol==cfg.symbol,CandleRow.timeframe==cfg.timeframe,
                        CandleRow.timestamp==cursor.timestamp))
                    if latest is None:raise ReconciliationRequired('snapshot candle absent')
                    engine.last_bar=Bar(dt(latest.timestamp),latest.symbol,latest.open,
                        latest.high,latest.low,latest.close,latest.volume)
                    count=cursor.engine_index+1
                else:
                    bars=s.scalars(select(CandleRow).where(CandleRow.exchange==cfg.exchange,
                      CandleRow.symbol==cfg.symbol,CandleRow.timeframe==cfg.timeframe).order_by(CandleRow.timestamp)).all()
                    for b in bars:
                        bar=Bar(dt(b.timestamp),b.symbol,b.open,b.high,b.low,b.close,b.volume)
                        engine.session.strategy.on_data({bar.symbol:bar}, portfolio=engine.portfolio)
                        engine.last_bar=bar
                    count=len(bars)
                engine.index=cursor.engine_index;engine.processed_bars=count
                engine.volumes={engine.last_bar.symbol:engine.last_bar.volume}
                engine.last_quote_timestamp=dt(cursor.last_quote_timestamp)
                q=cursor.strategy_state.get('last_quote')
                if q:engine.last_quote=Quote(q['symbol'],dt(q['timestamp']),q['bid'],q['ask'],
                                              q['bid_quantity'],q['ask_quantity'])
                engine.state=FeedState.DISCONNECTED # fail closed until new quote and gap backfill
                return int(dt(cursor.timestamp).timestamp()*1000)
        return None

    def status(self):
        with self.Session() as s:
            account=s.get(AccountRow,self.account)
            snap=s.scalar(select(SnapshotRow).where(SnapshotRow.account==self.account).order_by(SnapshotRow.id.desc()))
            risk=s.get(RiskStateRow,self.account)
            mdd=s.scalar(select(func.min(SnapshotRow.drawdown)).where(SnapshotRow.account==self.account))
            run=s.scalar(select(StrategyRun).where(StrategyRun.mode=='PAPER').order_by(StrategyRun.start_time.desc()))
            age=(datetime.now(timezone.utc)-dt(snap.timestamp)).total_seconds() if snap else None
            max_age=(run.config.get('paper_trading',{}).get('stale_data_timeout',90) if run else 90)
            paused=run and run.status!='RUNNING'
            lease=s.get(TraderLease,self.account)
            live=lease is not None and bool(lease.owner_id) and lease.expires_at>UTC()
            heartbeats={h.component:h.timestamp for h in s.scalars(select(HeartbeatRow).where(HeartbeatRow.account==self.account))}
            def recent(component,age_limit):
                t=heartbeats.get(component)
                return bool(t and (datetime.now(timezone.utc)-dt(t)).total_seconds()<=age_limit)
            enforce=bool(run and run.config.get('persistence',{}).get('single_writer',False))
            feed='HALTED' if (risk and risk.killed) or (run and run.status=='RECONCILIATION_REQUIRED') else ('DEGRADED' if age is None or age>max_age or paused else 'HEALTHY')
            if enforce and not recent('market_feed',max_age):feed='DEGRADED'
            return {'application':'HEALTHY' if run and (not enforce or (live and recent('process',max_age))) else 'DEGRADED','database':'HEALTHY' if not enforce or recent('database',max_age) else 'DEGRADED',
                    'market_feed':feed,
                    'broker':'HEALTHY' if run and not paused and (not enforce or live) else 'DEGRADED',
                    'strategy':'HEALTHY' if run and not paused and (not enforce or recent('strategy',max_age)) else 'DEGRADED',
                    'risk_engine':'HALTED' if risk and risk.killed else 'HEALTHY',
                    'heartbeats':heartbeats,'lease_active':live,
                    'run_id':run.id if run else None,'strategy_name':run.strategy_name if run else None,
                    'strategy_status':run.status if run else None,
                    'cash':account.cash if account else None,'equity':snap.equity if snap else None,
                    'drawdown':snap.drawdown if snap else None,
                    'max_drawdown':mdd if mdd is not None else None,
                    'total_pnl':snap.equity-account.initial_cash if snap and account else None,
                    'realized_pnl':account.realized_pnl if account else None,
                    'fees':account.fees if account else None,'kill_switch':risk.killed if risk else False}
