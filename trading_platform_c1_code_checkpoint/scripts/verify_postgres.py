"""Run against a disposable local Docker PostgreSQL instance only."""
import os
from datetime import datetime,timezone
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.engine import make_url
from trading_bot.persistence.ledger import migrate,PaperLedger
from trading_bot.persistence.models import OrderRow,FillRow,PositionRow,AccountRow
from trading_bot.config.settings import Settings
from trading_bot.core.events.models import Order,Fill,Side
url=os.environ.get('PAPER_TEST_DATABASE_URL')
if not url or not url.startswith('postgresql+psycopg://') or make_url(url).host not in ('localhost','127.0.0.1') or make_url(url).database!='paper_test':
    raise SystemExit('set PAPER_TEST_DATABASE_URL to a disposable PostgreSQL database')
migrate(url)
l=PaperLedger(url,account=f'pg-test-{uuid4()}')
s=Settings.load('config/paper_upbit.toml')
run=l.start_run(s)
o=Order('BTC/KRW',Side.BUY,.001,'postgres_probe',datetime.now(timezone.utc),1)
l.intent(run,o);l.intent(run,o)
f=Fill(o.id,datetime.now(timezone.utc),'BTC/KRW','postgres_probe',Side.BUY,.001,100_000_000,50,0)
assert l.apply_fill(run,'pg-fill-'+o.id,f,{'BTC/KRW':100_000_000})
assert not l.apply_fill(run,'pg-fill-'+o.id,f,{'BTC/KRW':100_000_000})
with l.Session() as db:
    assert db.get(PositionRow,(l.account,'BTC/KRW')).quantity==Decimal('0.001')
    assert db.get(OrderRow,o.id).status=='FILLED'
    assert db.get(FillRow,'pg-fill-'+o.id) is not None
print('PostgreSQL migration, order idempotency, fill accounting: PASS')
rollback_order=Order('BTC/KRW',Side.BUY,Decimal('0.00000001'),'postgres_probe',datetime.now(timezone.utc),2)
l.intent(run,rollback_order)
rollback_fill=Fill(rollback_order.id,datetime.now(timezone.utc),'BTC/KRW','postgres_probe',Side.BUY,
                   Decimal('0.00000001'),Decimal('100000000'),Decimal('0.000000000000000000000001'),Decimal(0))
with l.Session() as db:before=db.get(AccountRow,l.account).cash
try:
    l.apply_fill(run,'rollback-'+rollback_order.id,rollback_fill,{'BTC/KRW':100000000},fault='after_fill')
    raise AssertionError('injected rollback failed')
except RuntimeError as exc:
    assert 'injected' in str(exc)
with l.Session() as db:
    assert db.get(AccountRow,l.account).cash==before
    assert db.get(FillRow,'rollback-'+rollback_order.id) is None
assert l.apply_fill(run,'rollback-'+rollback_order.id,rollback_fill,{'BTC/KRW':100000000})
with l.Session() as db:
    assert db.get(AccountRow,l.account).cash==before-Decimal('1.000000000000000000000001')
print('PostgreSQL Decimal rollback and exact fee: PASS')
from trading_bot.persistence.lease import WriterLease,LeaseLost
from trading_bot.persistence.models import TraderLease,AccountRow,MarketCursorRow,RiskStateRow
lease=WriterLease(l,'ema_cross',ttl=5)
assert lease.acquire()==1
second=WriterLease(l,'ema_cross',ttl=5)
try:second.acquire();raise AssertionError('duplicate writer accepted')
except LeaseLost:pass
lease.renew()
with l.Session.begin() as db:lease.assert_owned(db)
with l.Session() as db:
    assert db.get(TraderLease,l.account).fencing_token==1
    assert db.get(AccountRow,l.account).cash<db.get(AccountRow,l.account).initial_cash
lease.release()
assert second.acquire()==2
with l.Session.begin() as db:
    try:lease.assert_owned(db);raise AssertionError('old writer was not fenced')
    except LeaseLost:pass
second.release()
print('PostgreSQL lease fencing and account persisted: PASS')

l.close()
