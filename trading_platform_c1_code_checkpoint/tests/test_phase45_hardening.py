import asyncio
import json
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import select,inspect
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from trading_bot.config.settings import Settings
from trading_bot.data.upbit_ws import UpbitPublicQuoteStream,parse_orderbook
from trading_bot.data.feeds import RealtimeExchangeFeed
from trading_bot.core.events.models import Bar,Order,Side
from trading_bot.core.events.market import FeedState,InvalidMarketData
from trading_bot.persistence.ledger import PaperLedger,migrate
from trading_bot.persistence.lease import WriterLease,LeaseLost
from trading_bot.persistence.models import TraderLease,HeartbeatRow,AccountRow
from trading_bot.strategies.ema_cross import EMACross
from trading_bot.strategies.rsi_strategy import RSIMeanReversion
from trading_bot.strategies.breakout_strategy import VolatilityBreakout
from trading_bot.api.app import create_app

UTC=timezone.utc

def db(tmp_path):
    url='sqlite:///'+str(tmp_path/'paper.sqlite3');migrate(url)
    return url,PaperLedger(url)

def config():
    s=Settings.load('config/paper_upbit.toml');s.paper_trading.warmup_bars=2
    return s

def book(timestamp=1750000000000):
    return json.dumps({'type':'orderbook','code':'KRW-BTC','timestamp':timestamp,
        'orderbook_units':[{'bid_price':999,'ask_price':1000,'bid_size':2,'ask_size':3}]})

def test_lease_duplicate_stale_takeover_and_fencing(tmp_path):
    url,l=db(tmp_path)
    moment=[datetime(2026,9,28,tzinfo=UTC)]
    clock=lambda:moment[0]
    a=WriterLease(l,'ema_cross',ttl=4,clock=clock);assert a.acquire()==1
    b=WriterLease(l,'ema_cross',ttl=4,clock=clock)
    with pytest.raises(LeaseLost):b.acquire()
    with l.Session.begin() as s:a.assert_owned(s)
    moment[0]+=timedelta(seconds=5)
    assert b.acquire()==2
    with l.Session.begin() as s:
        with pytest.raises(LeaseLost):a.assert_owned(s)
    with pytest.raises(LeaseLost):a.renew()
    with l.Session.begin() as s:b.assert_owned(s)
    b.renew()
    with l.Session() as s:assert s.get(TraderLease,'paper').fencing_token==2
    b.release();l.close()

def test_lease_blocks_ledger_write_and_second_process(tmp_path):
    import multiprocessing as mp
    url,l=db(tmp_path)
    a=WriterLease(l,'ema_cross',ttl=3);a.acquire();l.lease=a
    def attempt(q):
        other=PaperLedger(url)
        try:WriterLease(other,'ema_cross',ttl=3).acquire();q.put('UNSAFE')
        except LeaseLost:q.put('BLOCKED')
    q=mp.get_context('fork').Queue();p=mp.get_context('fork').Process(target=attempt,args=(q,));p.start();p.join(5)
    assert p.exitcode==0 and q.get()=='BLOCKED'
    # A replaced token cannot write an order intent, regardless of stale process memory.
    with l.Session.begin() as s:
        row=s.get(TraderLease,'paper');row.fencing_token+=1
    with pytest.raises(LeaseLost):l.intent('fake',Order('BTC/KRW',Side.BUY,.001,'x',datetime.now(UTC),1))
    l.close()

def test_public_warmup_keeps_writer_lease_alive(tmp_path):
    """A slow public REST warmup must not expire a freshly acquired lease."""
    from trading_bot.paper_trading.runner import run_public_paper
    cfg=config()
    cfg.persistence.database_url='sqlite:///'+str(tmp_path/'warmup.sqlite3')
    cfg.persistence.lease_ttl=1.2
    class SlowPublic:
        def __init__(self,settings):pass
        async def market_metadata(self,symbol):
            await asyncio.sleep(1.8)
            raise RuntimeError('injected public REST delay')
        async def close(self):pass
        def audit(self):return {'transport':{'public_http_attempts':1}}
    result=asyncio.run(run_public_paper(cfg,EMACross(),tmp_path/'out',3,adapter_factory=SlowPublic))
    assert result['error']=='RuntimeError: injected public REST delay'
    assert result.get('shutdown_error')!='LeaseLost'
    assert result['real_order_http_requests']==0
    ledger=PaperLedger(cfg.persistence.database_url)
    with ledger.Session() as s:
        assert s.get(HeartbeatRow,('paper','process')) is not None
    ledger.close()

def test_decimal_migration_existing_data_upgrade_downgrade(tmp_path):
    url='sqlite:///'+str(tmp_path/'legacy.sqlite3')
    cfg=Config('alembic.ini');cfg.attributes['database_url']=url
    command.upgrade(cfg,'0001')
    from sqlalchemy import create_engine,text
    e=create_engine(url)
    with e.begin() as c:c.execute(text("INSERT INTO accounts(account,cash,initial_cash,realized_pnl,fees) VALUES ('paper',12.345,12.345,0,0)"))
    command.upgrade(cfg,'0002_decimal_accounting')
    assert 'trader_leases' in inspect(e).get_table_names()
    with e.connect() as c:assert c.execute(text("SELECT cash FROM accounts WHERE account='paper'")).scalar()==pytest.approx(12.345)
    command.downgrade(cfg,'0001')
    assert 'trader_leases' not in inspect(e).get_table_names()
    with e.connect() as c:assert c.execute(text("SELECT cash FROM accounts WHERE account='paper'")).scalar()==pytest.approx(12.345)
    command.upgrade(cfg,'head');e.dispose()

def test_strategy_snapshot_full_replay_equivalence():
    now=datetime(2026,9,28,tzinfo=UTC)
    for cls in (EMACross,RSIMeanReversion,VolatilityBreakout):
        full=cls();partial=cls()
        bars=[Bar(now+timedelta(days=i),'BTC/KRW',100+i,102+i,98+i,100+(-1)**i*i,2) for i in range(40)]
        for b in bars[:20]:full.on_data({'BTC/KRW':b});partial.on_data({'BTC/KRW':b})
        state=json.loads(json.dumps(partial.snapshot_state()))
        resumed=cls();resumed.restore_state(state)
        for b in bars[20:]:
            assert full.on_data({'BTC/KRW':b})==resumed.on_data({'BTC/KRW':b})

def test_websocket_orderbook_validation_duplicates_silence_and_disconnect():
    assert parse_orderbook(book(),'BTC/KRW').ask==1000
    with pytest.raises(InvalidMarketData):parse_orderbook('{','BTC/KRW')
    with pytest.raises(InvalidMarketData):parse_orderbook(book().replace('"ask_price": 1000','"ask_price": 0'),'BTC/KRW')
    class WS:
        sent=[];items=[book(),book(),book(1750000001000)]
        async def send(self,msg):self.sent.append(msg)
        async def recv(self):
            await asyncio.sleep(.01)
            if not self.items:await asyncio.sleep(1)
            return self.items.pop(0)
        async def close(self):pass
    async def connect(*a,**kw):return WS()
    async def check():
        stream=UpbitPublicQuoteStream('BTC/KRW',connector=connect,timeout=.05)
        first=await stream.next_quote();assert first.ask==1000
        second=await stream.next_quote();assert second.timestamp>first.timestamp
        assert stream.duplicates==1
        with pytest.raises(TimeoutError):await stream.next_quote()
        assert stream.connection is None
    asyncio.run(check())

def test_monitor_optional_auth_and_heartbeat(tmp_path,monkeypatch):
    url,l=db(tmp_path)
    lease=WriterLease(l,'ema_cross');lease.acquire();lease.renew();lease.heartbeat('market_feed');lease.heartbeat('strategy')
    monkeypatch.setenv('PAPER_MONITOR_TOKEN','testing-only')
    client=TestClient(create_app(url))
    assert client.get('/health').status_code==401
    assert client.get('/health',headers={'x-monitor-token':'testing-only'}).status_code==200
    lease.release();l.close()

def test_ws_disconnect_gap_backfill_before_resuming_decisions():
    now=datetime(2026,9,28,12,2,20,tzinfo=UTC)
    a=Bar(now.replace(minute=0,second=0),'BTC/KRW',100,101,99,100,2)
    b=Bar(now.replace(minute=1,second=0),'BTC/KRW',100,101,99,100,2)
    class Public:
        calls=[]
        async def candles(self,symbol,timeframe,since,end):
            self.calls.append(since)
            return [x for x in (a,b) if since<=int(x.timestamp.timestamp()*1000)<end]
    from trading_bot.core.events.market import Quote
    class Stream:
        calls=0;closed=0
        async def next_quote(self):
            self.calls+=1
            if self.calls==2:raise ConnectionError('injected ws disconnect')
            return Quote('BTC/KRW',now+timedelta(seconds=self.calls),99,100,2,2)
        async def close(self):self.closed+=1
    paper_config=config().paper_trading
    feed=RealtimeExchangeFeed(Public(),paper_config,clock=lambda:now+timedelta(seconds=3),quote_stream=Stream())
    async def run():
        first=await feed.poll();assert first.state==FeedState.NORMAL and len(first.bars)==2
        failed=await feed.poll();assert failed.state==FeedState.DISCONNECTED and not failed.decision_allowed
        recovered=await feed.poll();assert recovered.state==FeedState.NORMAL and recovered.recovered
        assert feed.last_ms==int(b.timestamp.timestamp()*1000)
        assert len(recovered.bars)==0
        assert feed.quote_stream.closed==1
    asyncio.run(run())

def test_ws_missing_candle_fails_closed_until_rest_backfill():
    now=datetime(2026,9,28,12,2,20,tzinfo=UTC)
    a=Bar(now.replace(minute=0,second=0),'BTC/KRW',100,101,99,100,2)
    b=Bar(now.replace(minute=1,second=0),'BTC/KRW',100,101,99,100,2)
    from trading_bot.core.events.market import Quote
    class Public:
        calls=0
        async def candles(self,*args):
            self.calls+=1
            return [a] if self.calls==1 else [a,b]
    class Stream:
        async def next_quote(self):return Quote('BTC/KRW',now,99,100,2,2)
        async def close(self):pass
    feed=RealtimeExchangeFeed(Public(),config().paper_trading,clock=lambda:now,quote_stream=Stream())
    async def run():
        gap=await feed.poll();assert gap.state==FeedState.GAP and feed.last_ms is None
        good=await feed.poll();assert good.state==FeedState.NORMAL and good.recovered and len(good.bars)==2
    asyncio.run(run())

def test_crashed_process_lease_expires_and_new_owner_recovers(tmp_path):
    import multiprocessing as mp
    url,l=db(tmp_path)
    def crash(q):
        from trading_bot.persistence.ledger import PaperLedger
        from trading_bot.persistence.lease import WriterLease
        import os
        child=PaperLedger(url);owner=WriterLease(child,'ema_cross',ttl=1)
        q.put(owner.acquire());os._exit(72)
    q=mp.get_context('fork').Queue();p=mp.get_context('fork').Process(target=crash,args=(q,))
    p.start();p.join(5);assert p.exitcode==72
    lease=WriterLease(l,'ema_cross',ttl=2)
    with pytest.raises(LeaseLost):lease.acquire()
    import time
    time.sleep(1.1)
    assert lease.acquire()==2
    lease.release();l.close()

def test_restore_snapshot_queries_one_candle_instead_of_full_replay(tmp_path):
    from sqlalchemy import event as sqlalchemy_event
    from trading_bot.persistence.runtime import DurablePaperTrading
    from trading_bot.core.events.market import FeedEvent,Quote
    url,l=db(tmp_path);settings=config()
    d=DurablePaperTrading(settings,lambda:EMACross(fast=2,slow=3),l)
    now=datetime.now(UTC).replace(second=2,microsecond=0)
    bars=tuple(Bar(now.replace(second=0)-timedelta(minutes=i+1),'BTC/KRW',100,101,99,100,2)
               for i in (1,0))
    q=Quote('BTC/KRW',now,99,100,2,2)
    d.engine.clock=lambda:now
    d.consume(FeedEvent(now,FeedState.NORMAL,bars,q))
    d.lease.release();l.lease=None
    queries=[]
    def inspect_query(conn,cursor,statement,parameters,context,executemany):
        if 'FROM ohlcv' in statement:queries.append(statement)
    sqlalchemy_event.listen(l.engine,'before_cursor_execute',inspect_query)
    restarted=DurablePaperTrading(settings,lambda:EMACross(fast=2,slow=3),l)
    sqlalchemy_event.remove(l.engine,'before_cursor_execute',inspect_query)
    assert restarted.cursor_ms==int(bars[-1].timestamp.timestamp()*1000)
    assert len(queries)==1 and 'ohlcv.timestamp =' in queries[0]
    assert restarted.engine.session.strategy.snapshot_state()==d.engine.session.strategy.snapshot_state()
    restarted.lease.release();l.close()

def test_retention_preserves_error_and_latest_snapshot(tmp_path):
    from trading_bot.persistence.retention import prune
    from trading_bot.persistence.models import SystemEventRow,SnapshotRow
    from sqlalchemy import func
    url,l=db(tmp_path)
    run=l.start_run(config())
    old=(datetime.now(UTC)-timedelta(days=100)).isoformat()
    recent=datetime.now(UTC).isoformat()
    with l.Session.begin() as s:
        for level in ('INFO','ERROR'):
            s.add(SystemEventRow(timestamp=old,level=level,component='test',event='TEST',
                message='test',context={},strategy_run_id=run))
        for when in (old,recent):
            s.add(SnapshotRow(account='paper',strategy_run_id=run,timestamp=when,cash=1,
                market_value=0,equity=1,realized_pnl=0,unrealized_pnl=0,fees=0,drawdown=0))
    result=prune(l,events_days=30,snapshots_days=90)
    assert result['events_pruned']==1 and result['snapshots_pruned']==1
    assert result['orders_pruned']==result['fills_pruned']==0
    with l.Session() as s:
        assert s.scalar(select(func.count(SnapshotRow.id)))==1
        assert s.scalar(select(SystemEventRow).where(SystemEventRow.level=='ERROR')) is not None
    l.close()

def test_accounting_quantization_policy_and_float_compatibility():
    from trading_bot.core.portfolio.precision import money,quantity
    from trading_bot.core.portfolio.engine import Portfolio
    from trading_bot.core.events.models import Fill
    assert money('0.000000005')==Decimal('0.00000000')
    assert money('0.000000015')==Decimal('0.00000002')
    assert quantity('0.000000019')==Decimal('0.00000002')
    p=Portfolio(1_000_000)
    p.apply(Fill('id',datetime.now(UTC),'BTC/KRW','test',Side.BUY,.001,100_000_000,50,0),
            {'BTC/KRW':100_000_000})
    assert money(p.cash)==p.cash
    assert p.snapshot({'BTC/KRW':100_000_000})['fees']==50
