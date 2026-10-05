from decimal import Decimal
import asyncio
import json
import multiprocessing as mp
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select,func
from trading_bot.config.settings import Settings
from trading_bot.core.events.models import Bar,Fill,Side,Order,Status
from trading_bot.core.events.market import FeedEvent,FeedState,Quote
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.data.feeds import RealtimeExchangeFeed
from trading_bot.persistence.ledger import PaperLedger,migrate,config_digest,redact,ReconciliationRequired
from trading_bot.persistence.runtime import DurablePaperTrading
from trading_bot.persistence.models import (Base,AccountRow,CandleRow,PositionRow,OrderRow,FillRow,
    RiskStateRow,MarketCursorRow,StrategyRun,SnapshotRow)
from trading_bot.api.app import create_app
from trading_bot.strategies.base_strategy import Strategy
from trading_bot.core.events.models import Signal

class Cycle(Strategy):
    def __init__(self):self.n=0
    def on_data(self,bars,portfolio=None):
        self.n+=1
        return [Signal(k,None if self.n<2 else (.1 if self.n==2 else 0),'test_cycle') for k in bars]

def config():
    s=Settings.load('config/paper_upbit.toml')
    v=s.model_dump();v['paper_trading']['warmup_bars']=2
    # Legacy crash fixtures reopen immediately; Phase 4.5 tests exercise actual lease expiry.
    v['persistence']['single_writer']=False
    return Settings.model_validate(v)

def setup(tmp_path):
    url=f'sqlite:///{tmp_path}/paper.sqlite3';migrate(url)
    l=PaperLedger(url)
    d=DurablePaperTrading(config(),Cycle,l)
    return url,l,d

def ticks(d):
    now=datetime.now(timezone.utc).replace(second=0,microsecond=0)+timedelta(seconds=2)
    b1=Bar(now-timedelta(minutes=2,seconds=2),'BTC/KRW',100_000_000,100_010_000,99_990_000,100_000_000,2)
    b2=Bar(now-timedelta(minutes=1,seconds=2),'BTC/KRW',100_000_000,100_020_000,99_990_000,100_010_000,2)
    q=lambda t:Quote('BTC/KRW',t,100_008_000,100_010_000,2,2)
    d.engine.clock=lambda:now
    return [FeedEvent(now,FeedState.NORMAL,(b1,b2),q(now)),
            FeedEvent(now+timedelta(seconds=2),FeedState.NORMAL,(),q(now+timedelta(seconds=2)))]

def test_models_migration_and_downgrade(tmp_path):
    url,l,d=setup(tmp_path)
    tables=set(inspect(l.engine).get_table_names())
    assert {'ohlcv','signals','orders','fills','positions','portfolio_snapshots',
            'strategy_runs','system_events','risk_state','market_cursors','accounts'}.issubset(tables)
    from alembic import command
    from alembic.config import Config
    cfg=Config('alembic.ini');cfg.attributes['database_url']=url
    command.downgrade(cfg,'base')
    assert 'orders' not in inspect(l.engine).get_table_names()
    command.upgrade(cfg,'head')
    assert 'orders' in inspect(l.engine).get_table_names()
    l.close()

def test_canonical_hash_and_redaction():
    a=config_digest({'name':'ema','fast':20},{'max':.1})
    assert a==config_digest({'fast':20,'name':'ema'},{'max':.1})
    assert a!=config_digest({'name':'ema','fast':21},{'max':.1})
    assert redact({'api_secret':'hidden','Authorization':'Bearer ABC','nested':{'access_key':'long'},
                   'message':'Authorization: Bearer ABC'})=={
                    'api_secret':'[REDACTED]','Authorization':'[REDACTED]',
                    'nested':{'access_key':'[REDACTED]'},'message':'Authorization: [REDACTED] ABC'} or 'ABC' not in str(redact({'message':'Authorization: Bearer ABC'}))

def test_order_intent_idempotency_and_unknown_is_not_resent(tmp_path):
    url,l,d=setup(tmp_path)
    o=Order('BTC/KRW',Side.BUY,.001,'test',datetime.now(timezone.utc),1)
    l.intent(d.run_id,o,client_order_id='identifier-1')
    l.intent(d.run_id,o,client_order_id='identifier-1')
    collision=Order('BTC/KRW',Side.BUY,.001,'test',datetime.now(timezone.utc),1)
    with pytest.raises(ValueError):l.intent(d.run_id,collision,client_order_id='identifier-1')
    with l.Session() as s: assert s.scalar(select(func.count(OrderRow.internal_order_id)))==1
    class Provider:
        calls=[]
        def status(self,i):self.calls.append(i);return None
    provider=Provider()
    with pytest.raises(ReconciliationRequired):l.reconcile_outbox(provider)
    assert provider.calls==['identifier-1']
    # Paper status inspection cancels an intent that was never simulated.
    reopened=DurablePaperTrading(config(),Cycle,l)
    assert not reopened.blocked
    assert l.unresolved_intents()==[]
    l.close()

@pytest.mark.parametrize('fault',['before_fill','after_fill','after_portfolio'])
def test_fill_transaction_rollback_duplicate_and_restart(tmp_path,fault):
    url,l,d=setup(tmp_path)
    o=Order('BTC/KRW',Side.BUY,.001,'test',datetime.now(timezone.utc),1)
    l.intent(d.run_id,o)
    fill=Fill(o.id,datetime.now(timezone.utc),'BTC/KRW','test',Side.BUY,.001,100_000_000,50,5)
    initial=l.status()['cash']
    with pytest.raises(RuntimeError):l.apply_fill(d.run_id,'fill-1',fill,{'BTC/KRW':100_000_000},fault=fault)
    with l.Session() as s:
        assert s.get(FillRow,'fill-1') is None
        assert s.get(AccountRow,'paper').cash==initial
        assert s.get(PositionRow,('paper','BTC/KRW')) is None
    assert l.apply_fill(d.run_id,'fill-1',fill,{'BTC/KRW':100_000_000})
    assert not l.apply_fill(d.run_id,'fill-1',fill,{'BTC/KRW':100_000_000})
    with l.Session() as s:
        assert s.get(PositionRow,('paper','BTC/KRW')).quantity==Decimal('0.001')
        assert s.get(AccountRow,'paper').cash==initial-100_050
        assert s.scalar(select(func.count(FillRow.exchange_fill_id)))==1
    l.close()
    l=PaperLedger(url)
    with l.Session() as s:assert s.get(AccountRow,'paper').cash==initial-100_050
    l.close()

@pytest.mark.parametrize('fault',['before_order','after_order','after_fill','after_portfolio'])
def test_crash_boundary_rollback_then_replay(tmp_path,fault):
    url,l,d=setup(tmp_path)
    first,second=ticks(d)
    with pytest.raises(RuntimeError):d.consume(first,fault=fault)
    with l.Session() as s:
        assert s.scalar(select(func.count(OrderRow.internal_order_id)))==1 # committed outbox
        assert s.scalar(select(func.count(CandleRow.id)))==0
        assert s.get(MarketCursorRow,('upbit','BTC/KRW','1m')) is None
    l.close()
    l=PaperLedger(url)
    recovered=DurablePaperTrading(config(),Cycle,l)
    recovered.engine.clock=d.engine.clock
    assert recovered.cursor_ms is None
    recovered.consume(first)
    recovered.consume(second)
    with l.Session() as s:
        assert s.scalar(select(func.count(CandleRow.id)))==2
        assert s.scalar(select(func.count(OrderRow.internal_order_id)))==2 # cancelled intent + replayed order
        assert s.scalar(select(func.count(FillRow.exchange_fill_id)))>=1
    l.close()

def test_restart_position_risk_kill_cursor_and_replay(tmp_path):
    url,l,d=setup(tmp_path)
    first,second=ticks(d)
    d.consume(first);d.consume(second)
    d.consume(second)
    with l.Session() as s:
        before=(s.get(AccountRow,'paper').cash,
            s.get(PositionRow,('paper','BTC/KRW')).quantity,
            s.scalar(select(func.count(FillRow.exchange_fill_id))))
        assert s.scalar(select(func.count(CandleRow.id)))==2
    d.engine.risk.kill('manual_test')
    l.checkpoint(d.run_id,d.engine,second)
    l.close()
    l=PaperLedger(url)
    restored=DurablePaperTrading(config(),Cycle,l)
    assert restored.cursor_ms==int(d.engine.last_bar.timestamp.timestamp()*1000)
    assert restored.engine.risk.killed and restored.engine.risk.kill_reason=='manual_test'
    assert restored.engine.portfolio.cash==before[0]
    assert restored.engine.portfolio.quantity('BTC/KRW')==before[1]
    with l.Session() as s:assert s.scalar(select(func.count(FillRow.exchange_fill_id)))==before[2]
    l.close()

def test_reconciliation_mismatch_blocks(tmp_path):
    url,l,d=setup(tmp_path)
    d.consume(ticks(d)[0]);d.engine.portfolio.cash-=100
    with pytest.raises(ReconciliationRequired):d.consume(ticks(d)[1])
    assert d.blocked and l.status()['strategy_status']=='RECONCILIATION_REQUIRED'
    with pytest.raises(ReconciliationRequired):DurablePaperTrading(config(),Cycle,l)
    # Reconstruct the paper broker from committed DB state, compare, then explicitly clear.
    from trading_bot.paper_trading.engine import PaperTradingEngine
    from trading_bot.persistence.runtime import ReconciliationEngine,SimulationStateProvider
    clean=PaperTradingEngine(config(),Cycle());l.restore(clean,d.run_id)
    assert ReconciliationEngine(l,SimulationStateProvider(clean)).check()
    with l.Session.begin() as s:s.get(StrategyRun,d.run_id).status='PAUSED'
    assert not DurablePaperTrading(config(),Cycle,l).blocked
    l.close()

def test_feed_resumes_gap_before_decision(tmp_path):
    url,l,d=setup(tmp_path)
    first,_=ticks(d);d.consume(first);l.close()
    l=PaperLedger(url);restored=DurablePaperTrading(config(),Cycle,l)
    class Public:
        def __init__(self):self.ranges=[]
        async def candles(self,symbol,timeframe,start,end):
            self.ranges.append((start,end));return []
        async def order_book(self,symbol):raise AssertionError('no book until contiguous backfill')
    public=Public()
    feed=RealtimeExchangeFeed(public,config().paper_trading,clock=lambda:first.observed_at+timedelta(minutes=3))
    feed.last_ms=restored.cursor_ms
    event=asyncio.run(feed.poll())
    assert event.state==FeedState.GAP and not event.decision_allowed
    assert public.ranges[0][0]==restored.cursor_ms+feed.step
    assert feed.last_ms==restored.cursor_ms
    l.close()

def test_api_dashboard_read_only_and_redacted_events(tmp_path):
    url,l,d=setup(tmp_path)
    d.consume(ticks(d)[0])
    l.event('ORDER_ERROR','Authorization: Bearer xyz_secret','ERROR',context={'api_secret':'oops'})
    client=TestClient(create_app(url))
    for path in ['/health','/status','/portfolio','/positions','/orders','/fills','/strategies','/risk','/events','/']:
        res=client.get(path);assert res.status_code==200,path
        assert 'xyz_secret' not in res.text and 'oops' not in res.text
    assert client.get('/health').json()['status']=='HEALTHY'
    assert 'Current Strategy' in client.get('/').text
    assert client.post('/orders').status_code==405
    l.close()

def _crash_child(root,stage):
    import os
    from pathlib import Path
    url,l,d=setup(Path(root))
    event=ticks(d)[0]
    if stage=='after_intent':
        order=Order('BTC/KRW',Side.BUY,.001,'test',datetime.now(timezone.utc),1)
        l.intent(d.run_id,order,client_order_id='persisted-intent')
        os._exit(74)
    if stage=='after_risk_kill':
        d.consume(event)
        d.engine.risk.kill('persistent kill')
        l.checkpoint(d.run_id,d.engine,event)
        os._exit(75)
    d.consume(event,fault=stage)
    os._exit(99)

@pytest.mark.parametrize('stage,exitcode',[
    ('after_intent',74),('kill_after_order',71),('kill_after_fill',72),
    ('kill_after_portfolio',73),('after_risk_kill',75)])
def test_real_process_exit_recovery(tmp_path,stage,exitcode):
    p=mp.Process(target=_crash_child,args=(str(tmp_path),stage))
    p.start();p.join(timeout=10)
    assert p.exitcode==exitcode
    url=f'sqlite:///{tmp_path}/paper.sqlite3'
    l=PaperLedger(url)
    if stage=='after_intent':
        assert l.unresolved_intents()==['persisted-intent']
        assert DurablePaperTrading(config(),Cycle,l).engine.execution.orders[0].status==Status.CANCELLED
    else:
        restored=DurablePaperTrading(config(),Cycle,l)
        if stage=='after_risk_kill':
            assert restored.engine.risk.killed
            assert restored.engine.risk.kill_reason=='persistent kill'
            assert restored.cursor_ms is not None
        else:
            assert restored.cursor_ms is None
            with l.Session() as s:
                assert s.scalar(select(func.count(OrderRow.internal_order_id)))==1 # durable intent
                assert s.scalar(select(func.count(FillRow.exchange_fill_id)))==0
                assert s.get(AccountRow,'paper').cash==1_000_000
            restored.engine.clock=lambda:ticks(restored)[0].observed_at
            restored.consume(ticks(restored)[0])
            assert restored.cursor_ms is None # cursor on object is startup watermark
            with l.Session() as s:assert s.scalar(select(func.count(OrderRow.internal_order_id)))==2
    l.close()

def test_restart_gap_backfill_then_live_normal(tmp_path):
    url,l,d=setup(tmp_path)
    first,_=ticks(d);d.consume(first);l.close()
    l=PaperLedger(url);restored=DurablePaperTrading(config(),Cycle,l)
    then=first.observed_at+timedelta(minutes=3)
    restored.engine.clock=lambda:then
    class Public:
        def __init__(self):self.n=0
        async def candles(self,symbol,timeframe,start,end):
            self.n+=1
            if self.n==1:return [] # still missing: remain GAP
            return [Bar(datetime.fromtimestamp(t/1000,timezone.utc),symbol,100_010_000,
                        100_020_000,100_000_000,100_010_000,2)
                    for t in range(start,end,60_000)]
        async def order_book(self,symbol):
            return Quote(symbol,then,100_008_000,100_010_000,2,2)
    feed=RealtimeExchangeFeed(Public(),config().paper_trading,clock=lambda:then)
    feed.last_ms=restored.cursor_ms
    assert asyncio.run(feed.poll()).state==FeedState.GAP
    assert feed.last_ms==restored.cursor_ms
    recovery=asyncio.run(feed.poll())
    assert recovery.state==FeedState.NORMAL and recovery.recovered
    restored.consume(recovery)
    assert restored.engine.state==FeedState.NORMAL
    assert feed.last_ms>restored.cursor_ms
    with l.Session() as s:
        assert s.get(MarketCursorRow,('upbit','BTC/KRW','1m')).timestamp==restored.engine.last_bar.timestamp.isoformat()
    l.close()

def test_rotating_log_redacts_and_rotates(tmp_path):
    from trading_bot.monitoring.rotating import configure_log
    path=tmp_path/'events.jsonl'
    log=configure_log(path,max_bytes=180,backup_count=2)
    for _ in range(5):log.error('Authorization: Bearer sensitive_jwt',extra={'event':'ORDER_ERROR',
                                               'context':{'api_secret':'hidden'}})
    for h in log.handlers:h.flush();h.close()
    all_text=''.join(p.read_text() for p in tmp_path.glob('events.jsonl*'))
    assert 'sensitive_jwt' not in all_text and 'hidden' not in all_text
    assert 'ORDER_ERROR' in all_text and len(list(tmp_path.glob('events.jsonl*')))>1

def test_buy_sell_realized_pnl_and_replay_exactly_once(tmp_path):
    url,l,d=setup(tmp_path)
    t=datetime.now(timezone.utc)
    buy=Order('BTC/KRW',Side.BUY,.001,'test',t,1)
    sell=Order('BTC/KRW',Side.SELL,.001,'test',t+timedelta(seconds=1),2)
    l.intent(d.run_id,buy);l.intent(d.run_id,sell)
    b=Fill(buy.id,t,'BTC/KRW','test',Side.BUY,.001,100_000_000,50,5)
    x=Fill(sell.id,t+timedelta(seconds=1),'BTC/KRW','test',Side.SELL,.001,101_000_000,50.5,5)
    assert l.apply_fill(d.run_id,'b',b,{'BTC/KRW':100_000_000})
    assert l.apply_fill(d.run_id,'s',x,{'BTC/KRW':101_000_000})
    assert not l.apply_fill(d.run_id,'s',x,{'BTC/KRW':101_000_000})
    with l.Session() as s:
        a=s.get(AccountRow,'paper');p=s.get(PositionRow,('paper','BTC/KRW'))
        assert a.cash==Decimal('1000899.5')
        assert a.realized_pnl==Decimal('899.5')
        assert a.fees==Decimal('100.5')
        assert p.quantity==0 and p.average_entry_price==0
        assert s.scalar(select(func.count(FillRow.exchange_fill_id)))==2
    l.close()
