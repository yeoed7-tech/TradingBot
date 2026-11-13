from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import json

import exchange_calendars
import pytest
from sqlalchemy import update

from trading_bot.core.events.models import Side
from trading_bot.persistence.lease import LeaseLost
from trading_bot.strategies.laoer_tqqq import Cycle, LaoerStrategy, Parameters
from trading_bot.us_equity.checkpoint import CheckpointStore, events, serialize
from trading_bot.us_equity.history import NY, Session, load_prices
from trading_bot.us_equity.research import fx_result
from trading_bot.us_equity.simulation import ResearchAccount, SYMBOL


def bar(i, o="100", h="102", l="90", c="95", **kw):
    day=date(2024,1,2)+timedelta(days=i)
    return Session(day,datetime(day.year,day.month,day.day,9,30,tzinfo=NY),
        datetime(day.year,day.month,day.day,16,tzinfo=NY),*map(D,(o,h,l,c)),**kw)


def test_tranches_average_fee_exit_reset():
    a=ResearchAccount(1000,Parameters(slices=4,fee=D(".01"),slip=0))
    a.step(bar(0))
    assert a.portfolio.quantity(SYMBOL)==2
    assert a.cycle.spent==D(202)
    a.step(bar(1))
    assert a.cycle.filled_days=={"2024-01-02","2024-01-03"}
    assert a.portfolio.quantity(SYMBOL)==4
    assert a.portfolio.positions[SYMBOL].cost==D("393.90")
    a.step(bar(2,"110","120","109","115"))
    assert a.cycle is None and a.portfolio.quantity(SYMBOL)==0
    assert len(a.cycles)==1 and a.portfolio.realized_total>0
    a.step(bar(3))
    assert a.cycle.started_at=="2024-01-05"


def test_budget_exhaustion_and_no_reentry():
    a=ResearchAccount(1000,Parameters(slices=2,fee=0,slip=0))
    for i in range(4):
        a.step(bar(i))
    assert len(a.cycle.filled_days)==2 and a.cycle.exhausted_at
    assert a.portfolio.fill_count==3
    assert a.portfolio.cash>=0
    assert a.rows[-1]["equity"]==a.rows[-1]["cash"]+a.rows[-1]["market_value"]


def test_plan_reserves_cash_and_max_order():
    strategy=LaoerStrategy(Parameters(slices=1,reserve=800,max_order=150))
    c=Cycle("id","2024-01-02",D(1000))
    p=strategy.plan(day="2024-01-02",index=0,opening_mark=D(100),cycle=c,
                    quantity=D(0),average=D(0),cash=D(1000))
    assert len(p)==1 and p[0].quantity==1


def test_partial_fill_idempotency_counts_one_tranche():
    a=ResearchAccount(1000,Parameters(slices=2,fee=0,slip=0))
    b=bar(0)
    a.cycle=Cycle("manual",str(b.day),D(1000))
    i=a.strategy.plan(day=str(b.day),index=0,opening_mark=b.open,cycle=a.cycle,
                       quantity=D(0),average=D(0),cash=D(1000))[0]
    a.intents[i.id]=i
    f=a.broker.fill(i,b,a.config,capacity=2)
    assert a.apply_fill(f,{SYMBOL:b.open},str(b.day),i)
    assert not a.apply_fill(f,{SYMBOL:b.open},str(b.day),i)
    other=replace(f,fill_id=f.fill_id+":2",quantity=D(3))
    assert a.apply_fill(other,{SYMBOL:b.open},str(b.day),i)
    assert a.portfolio.quantity(SYMBOL)==5 and len(a.cycle.filled_days)==1
    with pytest.raises(ValueError,match="conflicting"):
        a.apply_fill(replace(f,quantity=D(1)),{SYMBOL:b.open},str(b.day),i)
    assert a.risk.killed


def test_no_lookahead_and_sell_first():
    cfg=Parameters(slices=4,fee=0,slip=0)
    a,b=ResearchAccount(1000,cfg),ResearchAccount(1000,cfg)
    a.step(bar(0)); b.step(bar(0))
    a.step(bar(1,"100","120","90","95"))
    b.step(bar(1,"100","105","90","105"))
    assert list(a.intents.values())==list(b.intents.values())
    assert a.portfolio.quantity(SYMBOL)==0 and b.portfolio.quantity(SYMBOL)>0
    assert [f.side for f in a.fills.values()]==[Side.BUY,Side.SELL]


def test_split_preserves_cost_and_dividends_are_receivable():
    a=ResearchAccount(1000,Parameters(slices=1,fee=0,slip=0))
    a.step(bar(0))
    a.step(bar(1,"50","51","47","47.5",split=D(2),dividend=D(".10")))
    assert a.portfolio.quantity(SYMBOL)==20 and a.portfolio.positions[SYMBOL].cost==1000
    assert a.portfolio.cash==0 and a.dividends==2 and a.rows[-1]["equity"]==952


def test_kill_switch_blocks_new_exposure():
    a=ResearchAccount(1000,Parameters(slices=4))
    a.risk.kill("operator")
    a.step(bar(0))
    assert not a.fills


def test_restart_fencing_and_reconciliation(tmp_path):
    url=f"sqlite:///{tmp_path/'sim.db'}"
    cfg=Parameters(slices=4)
    with CheckpointStore(url,1000,cfg) as store:
        store.step(bar(0),capacity=1)
        before=serialize(store.run.snapshot())
        with pytest.raises(LeaseLost):
            CheckpointStore(url,1000,cfg)
    with CheckpointStore(url,1000,cfg) as store:
        assert serialize(store.run.snapshot())==before
        store.step(bar(1))
        with store.Session.begin() as s:
            s.execute(update(events).values(state="{}"))
    with pytest.raises(ValueError,match="reconciliation"):
        CheckpointStore(url,1000,cfg)


def test_session_checkpoint_write_failure_is_recoverable(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path/'sim.db'}"
    cfg=Parameters(slices=4)
    with CheckpointStore(url,1000,cfg) as store:
        store.step(bar(0))
        def fail(_):
            raise RuntimeError("fault")
        with monkeypatch.context() as m:
            m.setattr(store.lease,"assert_owned",fail)
            with pytest.raises(RuntimeError):
                store.step(bar(1))
        assert store.run.failed
    with CheckpointStore(url,1000,cfg) as store:
        assert store.run.last_day==bar(0).day
        assert store.step(bar(1))["date"]==str(bar(1).day)


def test_history_raw_split_and_dst_half_day(tmp_path):
    cal=exchange_calendars.get_calendar("XNAS",start="2024-01-01",end="2025-01-01")
    dates=["2024-11-27","2024-11-29"]
    stamps=[int(cal.session_open(d).timestamp()) for d in dates]
    doc={"chart":{"result":[{"meta":{"symbol":"TQQQ","currency":"USD"},"timestamp":stamps,
        "indicators":{"quote":[{"open":[50,50],"high":[51,51],"low":[49,49],"close":[50,50]}]},
        "events":{"splits":{"s":{"date":stamps[1],"numerator":2,"denominator":1}}}}]}}
    f=tmp_path/"t"; f.write_text(json.dumps(doc))
    x,y=load_prices(f,"TQQQ",cal)
    assert x.open==100 and y.open==50 and y.split==2
    assert y.closes.astimezone(NY).hour==13
    assert cal.session_open("2024-07-01").hour==13 and cal.session_open("2024-11-27").hour==14


def test_fx_cost_separate():
    a,b=date(2020,1,2),date(2020,1,3)
    result=fx_result(.10,a,b,{a:D(1000),b:D(1200)},D(".01"))
    assert result["krw_return_before_fx_cost"]==D(".32")
    assert result["krw_converted_return"]<D(".32")
