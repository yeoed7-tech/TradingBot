from decimal import Decimal
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
import json
import pytest
from conftest import Schedule,bars_frame
from test_phase3_feed import T,Clock,candle,PublicFake
from trading_bot.config.settings import Settings
from trading_bot.core.events.models import Signal,OrderType,Status
from trading_bot.core.events.market import FeedEvent,FeedState,Quote
from trading_bot.paper_trading.engine import PaperTradingEngine
from trading_bot.data.feeds import ReplayFeed,RealtimeExchangeFeed,HistoricalFeed
from trading_bot.backtest.engine import BacktestEngine

@pytest.fixture
def cfg(settings):
    values=settings.model_dump()
    values['paper_trading']={'symbol':'BTC/KRW','starting_cash':1000,'fee_rate':.001,'slippage_bps':10,
         'warmup_bars':2,'max_book_participation':1,'market_rules':{'min_notional':0,'quantity_step':.001,'price_tick':.01}}
    values['risk']['max_slippage_bps']=1000
    return Settings.model_validate(values)

def event(clock,bars=(),price=100,decision=True,recovered=False,quantity=100):
    return FeedEvent(clock(),FeedState.NORMAL,tuple(bars),Quote('BTC/KRW',clock(),price-.1,price+.1,quantity,quantity),
                     recovered=recovered,decision_allowed=decision)

def test_buy_sell_hold_fees_spread_slippage_and_pnl(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1)); engine=PaperTradingEngine(cfg,Schedule([.5,None,0]),clock=clock)
    engine.consume(event(clock,[candle(T)]))
    assert len(engine.execution.orders)==1 and not engine.portfolio.fills
    clock.advance(1);engine.consume(event(clock))
    buy=engine.portfolio.fills[0]
    assert buy['quantity']==5 and buy['price']==Decimal('100.21')
    assert buy['fee']==Decimal('.50105')
    clock.advance(59);engine.consume(event(clock,[candle(T+timedelta(minutes=1))]))
    assert len(engine.execution.orders)==1 # HOLD does not create new order
    clock.advance(60);engine.consume(event(clock,[candle(T+timedelta(minutes=2),110)],110))
    clock.advance(1);engine.consume(event(clock,price=110))
    sell=engine.portfolio.fills[-1]
    assert sell['price']==Decimal('109.79')
    s=engine.portfolio.snapshot({'BTC/KRW':110})
    assert s['positions']=={} and s['unrealized_pnl']==0
    assert s['cash']==Decimal('1046.85')
    assert s['realized_pnl']==Decimal('46.85')
    assert s['fees']==Decimal('1.05')


def test_positions_and_average_entry_are_existing_ledger(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    s=e.snapshots[-1]
    assert s['positions']['BTC/KRW']['quantity']==5
    assert s['positions']['BTC/KRW']['average_entry_price']==Decimal('100.31021')
    assert s['equity']==s['cash']+Decimal('500')
    assert s['realized_pnl']+s['unrealized_pnl']==s['equity']-Decimal('1000')


def test_duplicate_event_has_no_double_accounting(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    a=event(clock,[candle(T)]);e.consume(a);e.consume(a)
    assert len(e.execution.orders)==1 and e.processed_bars==1
    clock.advance(1);b=event(clock);e.consume(b);cash=e.portfolio.cash;e.consume(b)
    assert len(e.portfolio.fills)==1 and e.portfolio.cash==cash


def test_new_bar_on_duplicate_book_updates_indicators_without_orders(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([None,.5]),clock=clock)
    a=event(clock,[candle(T)]);e.consume(a)
    clock.advance(58)
    b=event(clock);e.consume(b)
    clock.advance(2)
    duplicate=FeedEvent(clock(),FeedState.NORMAL,(candle(T+timedelta(minutes=1)),),b.quote)
    e.consume(duplicate)
    assert e.processed_bars==2 and not e.execution.orders


def test_stale_pause_cancels_pending_and_recovers(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5,.5]),clock=clock)
    a=event(clock,[candle(T)]);e.consume(a)
    clock.advance(20);e.consume(a)
    assert e.state==FeedState.STALE_DATA and e.execution.orders[0].status==Status.CANCELLED
    assert not e.portfolio.fills
    clock.advance(40);e.consume(event(clock,[candle(T+timedelta(minutes=1))],recovered=True))
    assert len(e.execution.orders)==2
    clock.advance(1);e.consume(event(clock))
    assert len(e.portfolio.fills)==1

@pytest.mark.parametrize('state',[FeedState.DISCONNECTED,FeedState.GAP,FeedState.FAILED,FeedState.INVALID_DATA])
def test_failure_blocks_execution(cfg,state):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(T)]))
    e.consume(FeedEvent(clock(),state,reason='injected fault'))
    assert not e.portfolio.fills
    assert e.execution.orders[0].status==Status.CANCELLED
    if state in {FeedState.FAILED,FeedState.INVALID_DATA}: assert e.risk.killed


def test_risk_rejection_drawdown_and_kill(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5,.5]),clock=clock)
    e.risk.kill('manual')
    e.consume(event(clock,[candle(T)]))
    assert not e.execution.orders
    e=PaperTradingEngine(cfg,Schedule([.5,None]),clock=clock)
    e.settings.risk.max_drawdown=.02
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    clock.advance(1);e.consume(event(clock,price=90))
    assert e.risk.killed and e.risk.kill_reason=='max_drawdown'


def test_daily_loss_and_position_cap(cfg):
    cfg.risk.max_symbol_weight=.1
    cfg.risk.daily_loss=.001
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([1]),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    assert e.portfolio.gross({'BTC/KRW':100})/e.portfolio.equity({'BTC/KRW':100})<=.1
    clock.advance(1);e.consume(event(clock,price=95))
    assert e.risk.killed and e.risk.kill_reason=='daily_loss'


def test_limit_order_and_partial_liquidity(cfg):
    class Limit:
        def on_data(self,bars,portfolio=None): return [Signal(s,.5,'limit',order_type=OrderType.LIMIT,limit_price=99) for s in bars]
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Limit(),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    assert not e.portfolio.fills
    clock.advance(1);e.consume(event(clock,price=98,quantity=1))
    assert len(e.portfolio.fills)==1 and e.portfolio.fills[0]['price']<=99
    assert e.execution.orders[0].status==Status.PARTIALLY_FILLED


def test_minimum_and_precision(cfg):
    cfg.paper_trading.market_rules.min_notional=600
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(T)]));assert not e.execution.orders
    cfg.paper_trading.market_rules.min_notional=0
    cfg.paper_trading.market_rules.min_quantity=6
    e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(T)]));assert not e.execution.orders


def test_missing_bar_and_future_bar_rejected(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(120)
    e.consume(event(clock,[candle(T+timedelta(minutes=2))]))
    assert e.state==FeedState.GAP and not e.portfolio.fills
    e=PaperTradingEngine(cfg,Schedule([.5]),clock=clock)
    e.consume(event(clock,[candle(clock()+timedelta(minutes=1))]))
    assert e.state==FeedState.INVALID_DATA


def test_replay_safety_and_save(cfg,tmp_path):
    async def run():
        clock=Clock(T+timedelta(minutes=1,seconds=1))
        first=event(clock,[candle(T)]);clock.advance(1);second=event(clock)
        e=PaperTradingEngine(cfg,Schedule([.5]),clock=lambda:second.observed_at)
        summary=await e.run(ReplayFeed([first,first,second,second]))
        assert summary['simulated_fills']==1
        assert summary['execution_backend']=='SimulationBroker'
        assert not any(hasattr(e,n) for n in ['adapter','exchange','create_order','cancel_order'])
        e.save(tmp_path)
        assert json.loads((tmp_path/'summary.json').read_text())['simulated_fills']==1
    asyncio.run(run())


def test_realtime_feed_to_paper_and_network_spies(cfg):
    async def run():
        clock=Clock();public=PublicFake(clock)
        public.create_order=AsyncMock(side_effect=AssertionError('forbidden'))
        public.cancel_order=AsyncMock(side_effect=AssertionError('forbidden'))
        feed=RealtimeExchangeFeed(public,cfg.paper_trading,clock=clock)
        engine=PaperTradingEngine(cfg,Schedule([None,.5,None,0]),clock=clock)
        engine.consume(await feed.poll());clock.advance(1);engine.consume(await feed.poll())
        assert engine.portfolio.fills
        clock.advance(120);public.offline=True;engine.consume(await feed.poll())
        public.offline=False;engine.consume(await feed.poll())
        clock.advance(1);engine.consume(await feed.poll())
        assert engine.processed_bars==4
        assert public.create_order.await_count==public.cancel_order.await_count==0
    asyncio.run(run())


def test_historical_backtest_regression_feed_api(settings):
    import pandas as pd
    frame=bars_frame([100,100,110,110])
    a=BacktestEngine(settings).run(frame,Schedule([.5,0]))
    b=BacktestEngine(settings).run_feed(HistoricalFeed(frame,86400),Schedule([.5,0]))
    pd.testing.assert_frame_equal(a.equity,b.equity)
    assert a.trades.pnl.tolist()==b.trades.pnl.tolist()


def test_recovery_backfill_does_not_retroactively_fill(cfg):
    clock=Clock(T+timedelta(minutes=1,seconds=1))
    e=PaperTradingEngine(cfg,Schedule([.5,.5,.5]),clock=clock)
    e.consume(event(clock,[candle(T)]))
    e.consume(FeedEvent(clock(),FeedState.DISCONNECTED,reason='network'))
    clock.advance(120)
    recovered=[candle(T+timedelta(minutes=1),50),candle(T+timedelta(minutes=2),110)]
    e.consume(event(clock,recovered,price=110,recovered=True))
    assert not e.portfolio.fills # historic price 50 cannot be used
    clock.advance(1);e.consume(event(clock,price=110))
    assert e.portfolio.fills[0]['price']>110


def test_delay_and_expiry_count_completed_bars(cfg):
    cfg.execution.delay_bars=2
    cfg.execution.expiry_bars=1
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5,None,None]),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    assert not e.portfolio.fills
    clock.advance(59);e.consume(event(clock,[candle(T+timedelta(minutes=1))],quantity=.1))
    assert e.execution.orders[0].status==Status.PARTIALLY_FILLED
    clock.advance(60);e.consume(event(clock,[candle(T+timedelta(minutes=2))]))
    assert e.execution.orders[0].status==Status.CANCELLED


def test_runner_closes_and_saves_failure(cfg,tmp_path):
    from trading_bot.paper_trading.runner import run_public_paper
    from trading_bot.core.exchange.upbit_public import PublicDataUnavailable
    class Failing:
        closed=False
        def __init__(self,config):pass
        async def market_metadata(self,symbol):raise PublicDataUnavailable('injected network failure')
        async def close(self):Failing.closed=True
        def audit(self):return {'transport':{'public_http_attempts':1,'GET /v1/market/all':1}}
    r=asyncio.run(run_public_paper(cfg,Schedule([.5]),tmp_path,1,adapter_factory=Failing))
    assert Failing.closed and r['status']=='FAILED'
    assert r['real_order_http_requests']==0 and not r['integration_success']
    assert json.loads((tmp_path/'summary.json').read_text())['error']


def test_runner_deadline_without_data_is_failure(cfg,tmp_path):
    from trading_bot.paper_trading.runner import run_public_paper
    class Slow:
        def __init__(self,config):pass
        async def market_metadata(self,symbol):await asyncio.sleep(10)
        async def close(self):pass
        def audit(self):return {'transport':{}}
    r=asyncio.run(run_public_paper(cfg,Schedule([.5]),tmp_path,.001,adapter_factory=Slow))
    assert r['status']=='FAILED' and not r['integration_success']


def test_abnormal_quote_cannot_fill_even_a_risk_reducing_sell(cfg):
    cfg.risk.max_price_jump=.5
    clock=Clock(T+timedelta(minutes=1,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5,0]),clock=clock)
    e.consume(event(clock,[candle(T)]));clock.advance(1);e.consume(event(clock))
    clock.advance(59);e.consume(event(clock,[candle(T+timedelta(minutes=1))]))
    assert len(e.execution.orders)==2
    clock.advance(1);e.consume(event(clock,price=1000))
    assert len(e.portfolio.fills)==1
    assert e.state==FeedState.INVALID_DATA and e.risk.killed
    assert e.execution.orders[-1].status==Status.CANCELLED


def test_abnormal_closed_candle_is_rejected_before_strategy(cfg):
    cfg.risk.max_price_jump=.5
    clock=Clock(T+timedelta(minutes=2,seconds=1));e=PaperTradingEngine(cfg,Schedule([.5,.5]),clock=clock)
    e.consume(event(clock,[candle(T),candle(T+timedelta(minutes=1),1000)]))
    assert e.processed_bars==0 and not e.execution.orders
    assert e.state==FeedState.INVALID_DATA
