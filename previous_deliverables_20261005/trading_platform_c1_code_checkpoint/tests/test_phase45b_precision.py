"""Exact accounting, durable replay, bounded operational caches and failure closure."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import select, func
from trading_bot.config.settings import Settings
from trading_bot.core.events.models import Fill, Order, Side, Status
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.core.session import TradingSession
from trading_bot.core.portfolio.precision import ledger, floor_step, tick_price
from trading_bot.persistence.ledger import PaperLedger, migrate
from trading_bot.persistence.models import AccountRow, PositionRow, FillRow, OrderRow, RiskStateRow
from trading_bot.persistence.lease import WriterLease, LeaseLost
from trading_bot.persistence.runtime import DurablePaperTrading, ReconciliationRequired
from trading_bot.strategies.ema_cross import EMACross

T=datetime(2026,9,28,tzinfo=timezone.utc)
D=Decimal

def setup(tmp_path,limit=100):
    s=Settings.load('config/paper_upbit.toml')
    s.persistence.single_writer=False
    s.persistence.recent_cache_limit=limit
    url='sqlite:///'+str(tmp_path/'exact.sqlite3')
    migrate(url)
    l=PaperLedger(url)
    d=DurablePaperTrading(s,lambda:EMACross(2,3),l)
    return s,l,d

def test_exact_partial_fills_full_exit_and_stress():
    p=Portfolio('1000000000',history_limit=100)
    q=D('0.00000001');price=D('99999999.99');fee=D('0.00000001')
    cost=ledger(q*price+fee)
    for i in range(2000):
        b=Fill(str(i),T,'BTC/KRW','test',Side.BUY,q/2,price,fee/2,0)
        p.apply(b,{'BTC/KRW':price})
        p.apply(b,{'BTC/KRW':price})
        assert p.quantity('BTC/KRW')==q
        assert p.positions['BTC/KRW'].cost==cost
        for _ in range(4):
            p.apply(Fill(str(i),T,'BTC/KRW','test',Side.SELL,q/4,price,fee/4,0),{'BTC/KRW':price})
        assert p.quantity('BTC/KRW')==0
        assert p.positions['BTC/KRW'].cost==0
    assert p.cash==D('1000000000')-2000*fee*2
    assert p.fees_total==2000*fee*2
    assert p.realized_total==-2000*fee*2
    assert p.fill_count==12000 and len(p.fills)==100 and len(p.trades)==100
    assert p.trade_offset==1900

def test_market_rounding_separate_from_internal_ledger():
    assert ledger('0.1234567890123456789012345')==D('0.123456789012345678901234')
    assert floor_step('0.000000019','0.00000001')==D('0.00000001')
    assert tick_price('100.01','0.1',True)==D('100.1')
    assert tick_price('100.01','0.1',False)==D('100.0')

def test_migration_0002_to_0003_and_back_preserves_existing_sqlite_values(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    url='sqlite:///'+str(tmp_path/'migration.sqlite3')
    cfg=Config('alembic.ini');cfg.attributes['database_url']=url
    command.upgrade(cfg,'0002_decimal_accounting')
    e=create_engine(url)
    with e.begin() as db:
        db.execute(text("INSERT INTO accounts(account,cash,initial_cash,realized_pnl,fees) "
            "VALUES ('paper',12345.125,12345.125,0,0)"))
    command.upgrade(cfg,'0003_exact_accounting')
    with e.connect() as db:
        assert D(str(db.execute(text("SELECT cash FROM accounts WHERE account='paper'")).scalar()))==D('12345.125')
        assert db.execute(text("SELECT fill_count FROM accounts WHERE account='paper'")).scalar()==0
    command.downgrade(cfg,'0002_decimal_accounting')
    with e.connect() as db:
        assert D(str(db.execute(text("SELECT cash FROM accounts WHERE account='paper'")).scalar()))==D('12345.125')
    command.upgrade(cfg,'head')
    with e.connect() as db:
        assert D(str(db.execute(text("SELECT cash FROM accounts WHERE account='paper'")).scalar()))==D('12345.125')
    e.dispose()

def test_exact_sqlite_fill_restart_reconcile_and_duplicate(tmp_path):
    s,l,d=setup(tmp_path)
    o=Order('BTC/KRW',Side.BUY,D('0.00000001'),'ema_cross',T,1)
    l.intent(d.run_id,o)
    fill=Fill(o.id,T,'BTC/KRW','ema_cross',Side.BUY,D('0.00000001'),D('123456789.12345678'),D('0.000000000000000000000001'),D('0.01'))
    assert l.apply_fill(d.run_id,'precise-fill',fill,{'BTC/KRW':fill.price})
    assert not l.apply_fill(d.run_id,'precise-fill',fill,{'BTC/KRW':fill.price})
    with l.Session() as db:
        a=db.get(AccountRow,'paper');pos=db.get(PositionRow,('paper','BTC/KRW'))
        expected=(a.cash,a.fees,a.fill_count,pos.quantity,pos.cost,pos.average_entry_price)
        assert all(isinstance(v,D) for v in expected if not isinstance(v,int))
        assert db.scalar(select(func.count(FillRow.exchange_fill_id)))==1
    l.close()
    reopened=PaperLedger('sqlite:///'+str(tmp_path/'exact.sqlite3'))
    with reopened.Session() as db:
        a=db.get(AccountRow,'paper');pos=db.get(PositionRow,('paper','BTC/KRW'))
        assert (a.cash,a.fees,a.fill_count,pos.quantity,pos.cost,pos.average_entry_price)==expected
    reopened.close()

def test_operational_history_bounded_research_full_and_100k_events():
    from trading_bot.monitoring.events import EventJournal
    s=Settings.load('config/paper_upbit.toml');s.persistence.recent_cache_limit=100
    operational=TradingSession(s,EMACross(2,3),operational=True)
    research=TradingSession(s,EMACross(2,3))
    for i in range(100_000):
        operational.journal.record('market_data',index=i)
        if i<101:research.journal.record('market_data',index=i)
    assert len(operational.journal.events)==100
    assert operational.journal.events[0]['index']==99_900
    assert len(research.journal.events)==101
    for i in range(1000):
        operational.execution.events.append({'index':i})
        operational.risk.events.append({'index':i})
    assert len(operational.execution.events)==len(operational.risk.events)==100

def test_sqlite_real_write_lock_does_not_advance_state(tmp_path):
    s,l,d=setup(tmp_path)
    from trading_bot.core.events.models import Bar
    from trading_bot.core.events.market import FeedEvent,FeedState,Quote
    l.engine.dispose()
    locker=sqlite3.connect(str(tmp_path/'exact.sqlite3'),timeout=.1)
    locker.execute('BEGIN IMMEDIATE')
    try:
        l.engine.dispose()
        from sqlalchemy import event
        @event.listens_for(l.engine,'connect')
        def short_timeout(conn,rec):conn.execute('PRAGMA busy_timeout=50')
        with pytest.raises(Exception):
            l.intent(d.run_id,Order('BTC/KRW',Side.BUY,D('0.1'),'test',T,1))
        now=T+timedelta(minutes=2,seconds=1)
        d.engine.clock=lambda:now
        e=FeedEvent(now,FeedState.NORMAL,(Bar(T,'BTC/KRW',100000000,100000000,100000000,100000000,2),),
            Quote('BTC/KRW',now,100000000,100001000,2,2))
        with pytest.raises(Exception):d.consume(e)
        assert d.blocked and d.engine.state==FeedState.RECONCILIATION_REQUIRED
        with l.Session() as db:
            assert db.scalar(select(func.count(OrderRow.internal_order_id)))==0
    finally:locker.rollback();locker.close();l.close()

def test_clock_backwards_and_forward_lease_fail_closed(tmp_path):
    s,l,d=setup(tmp_path)
    now=[T]
    lease=WriterLease(l,'ema_cross',ttl=10,clock=lambda:now[0]);lease.acquire()
    now[0]-=timedelta(seconds=1)
    with pytest.raises(LeaseLost,match='backwards'):lease.renew()
    now[0]+=timedelta(seconds=12)
    with pytest.raises(LeaseLost):lease.renew()
    l.close()

def test_db_write_failure_halts_runtime_and_does_not_advance_cursor(tmp_path,monkeypatch):
    from trading_bot.core.events.models import Bar
    from trading_bot.core.events.market import FeedEvent, FeedState, Quote
    s,l,d=setup(tmp_path)
    now=T+timedelta(minutes=2,seconds=1)
    d.engine.clock=lambda:now
    bar=Bar(T,'BTC/KRW',100_000_000,100_000_000,100_000_000,100_000_000,2)
    event=FeedEvent(now,FeedState.NORMAL,(bar,),Quote('BTC/KRW',now,100_000_000,100_001_000,2,2))
    def disk_failure(*args,**kwargs):raise OSError('injected database write failure')
    monkeypatch.setattr(l,'checkpoint',disk_failure)
    with pytest.raises(OSError,match='injected'):d.consume(event)
    assert d.blocked and d.engine.state==FeedState.RECONCILIATION_REQUIRED
    with l.Session() as db:
        from trading_bot.persistence.models import MarketCursorRow
        assert db.scalar(select(func.count(MarketCursorRow.timestamp)))==0
        assert db.get(AccountRow,'paper').cash==D('1000000')
        assert db.scalar(select(func.count(FillRow.exchange_fill_id)))==0
    l.close()

def test_reconciliation_detects_single_ledger_unit_difference(tmp_path):
    s,l,d=setup(tmp_path)
    with l.Session.begin() as db:
        a=db.get(AccountRow,'paper');a.cash+=D('0.000000000000000000000001')
    with pytest.raises(ReconciliationRequired):d.reconciler.check()
    l.close()

def test_risk_monetary_state_restores_exact_decimal(tmp_path):
    from trading_bot.core.events.market import FeedEvent,FeedState
    s,l,d=setup(tmp_path)
    d.engine.risk.peak=D('1000000.000000000000000000000001')
    d.engine.risk.day_start=D('999999.999999999999999999999999')
    d.engine.risk.week_start=D('999999.999999999999999999999998')
    d.engine.risk.last_equity=D('1000000')
    l.checkpoint(d.run_id,d.engine,FeedEvent(T,FeedState.DISCONNECTED))
    l.close()
    restored=PaperLedger('sqlite:///'+str(tmp_path/'exact.sqlite3'))
    reopened=DurablePaperTrading(s,lambda:EMACross(2,3),restored)
    assert reopened.engine.risk.peak==D('1000000.000000000000000000000001')
    assert reopened.engine.risk.day_start==D('999999.999999999999999999999999')
    assert reopened.engine.risk.week_start==D('999999.999999999999999999999998')
    restored.close()

def test_2000_durable_orders_fills_bounded_restore(tmp_path):
    s,l,d=setup(tmp_path,limit=100)
    q=D('0.00000001');price=D('100000000');fee=D('0.000000000000000000000001')
    for i in range(1000):
        for side in (Side.BUY,Side.SELL):
            o=Order('BTC/KRW',side,q,'ema_cross',T+timedelta(seconds=i),1)
            l.intent(d.run_id,o)
            fill=Fill(o.id,T,'BTC/KRW','ema_cross',side,q,price,fee,0)
            assert l.apply_fill(d.run_id,'stable-'+o.id,fill,{'BTC/KRW':price})
            assert not l.apply_fill(d.run_id,'stable-'+o.id,fill,{'BTC/KRW':price})
    with l.Session() as db:
        a=db.get(AccountRow,'paper')
        assert db.scalar(select(func.count(FillRow.exchange_fill_id)))==2000
        assert db.scalar(select(func.count(OrderRow.internal_order_id)))==2000
        assert a.fill_count==2000 and a.cash==D('1000000')-2000*fee
        assert db.get(PositionRow,('paper','BTC/KRW')).cost==0
    l.close()
    restored=PaperLedger('sqlite:///'+str(tmp_path/'exact.sqlite3'))
    reopened=DurablePaperTrading(s,lambda:EMACross(2,3),restored)
    assert reopened.reconciler.check()
    assert reopened.engine.portfolio.cash==D('1000000')-2000*fee
    assert reopened.engine.portfolio.fill_count==2000
    assert len(reopened.engine.portfolio.fills)==len(reopened.engine.execution.orders)==100
    assert reopened.engine.execution.order_count==2000
    restored.close()
