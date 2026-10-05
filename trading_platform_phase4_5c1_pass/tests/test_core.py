from decimal import Decimal
from datetime import timedelta
import asyncio
import pytest
from pydantic import ValidationError
from conftest import T,bars_frame,Schedule
from trading_bot.core.events.models import Bar,Order,OrderType,Side,Status,Signal,Fill
from trading_bot.core.portfolio.engine import Portfolio
from trading_bot.core.risk.engine import RiskEngine,floor_step
from trading_bot.core.execution.engine import ExecutionEngine,SimulationBroker
from trading_bot.core.exchange.mock import MockExchange
from trading_bot.config.settings import Settings,RiskConfig
from trading_bot.backtest.engine import BacktestEngine
from trading_bot.data.market_data import MarketDataEngine


def test_no_same_bar_fills(settings):
    r=BacktestEngine(settings).run(bars_frame([100,200,200]),Schedule([.5,None,None]))
    assert r.fills.iloc[0].timestamp==T+timedelta(days=1)
    assert r.fills.iloc[0].price==200
    assert r.equity.iloc[1].cash==1000
    assert r.equity.iloc[-1].equity==1000


def test_latency(settings):
    settings.execution.delay_bars=2
    r=BacktestEngine(settings).run(bars_frame([100,110,120,130]),Schedule([.5,None,None,None]))
    assert r.fills.iloc[0].timestamp==T+timedelta(days=2)
    assert r.fills.iloc[0].price==120


def test_fee_and_cash_accounting():
    p=Portfolio(1000)
    p.apply(Fill('1',T,'BTC','s',Side.BUY,2,100,2,0),{'BTC':100})
    p.apply(Fill('2',T+timedelta(days=1),'BTC','s',Side.SELL,1,120,1.2,0),{'BTC':120})
    assert p.cash==Decimal('916.8')
    assert p.positions['BTC'].cost==101
    assert not p.trades
    p.apply(Fill('3',T+timedelta(days=2),'BTC','s',Side.SELL,1,90,.9,0),{'BTC':90})
    assert p.cash==Decimal('1005.9')
    assert p.trades[0]['pnl']==Decimal('5.9')
    assert p.trades[0]['holding_seconds']==172800
    with pytest.raises(ValueError): p.apply(Fill('4',T,'BTC','s',Side.SELL,1,100,0,0),{'BTC':100})
    with pytest.raises(ValueError): p.apply(Fill('4',T,'BTC','s',Side.BUY,100,100,0,0),{'BTC':100})


def test_partial_fill_and_expiry(settings):
    settings.execution.expiry_bars=2
    r=BacktestEngine(settings).run(bars_frame([100]*5,volume=1),Schedule([1,None,None,None,None]))
    assert list(r.fills.quantity)==[1,1]
    assert r.orders.iloc[0].status==Status.CANCELLED
    assert r.orders.iloc[0].filled==2
    assert r.orders.iloc[0].reason=='expired'


def test_order_state_and_duplicate(settings):
    o=Order('BTC',Side.BUY,1,'s',T,1)
    execution=ExecutionEngine(settings)
    assert execution.submit(o)
    assert not execution.submit(o)
    o.transition(Status.PARTIALLY_FILLED)
    o.transition(Status.FILLED)
    with pytest.raises(ValueError): o.transition(Status.SUBMITTED)
    with pytest.raises(ValueError): Order('BTC',Side.BUY,0,'s',T,1)


def test_limit_marketability_and_tick(settings):
    p=Portfolio(1000); risk=RiskEngine(settings.risk,1000); execution=ExecutionEngine(settings)
    o=Order('BTC',Side.BUY,1,'s',T,1,OrderType.LIMIT,99)
    execution.submit(o)
    broker=SimulationBroker(settings)
    broker.process(execution,1,{'BTC':Bar(T,'BTC',100,101,98,100,100)}, {'BTC':100},p,risk)
    assert o.status==Status.SUBMITTED  # intrabar touch deliberately not filled
    broker.process(execution,2,{'BTC':Bar(T,'BTC',98,101,97,100,100)}, {'BTC':100},p,risk)
    assert o.status==Status.FILLED
    assert p.fills[0]['price']==98


def test_risk_and_exit_after_kill(settings):
    settings.risk.daily_loss=.03
    risk=RiskEngine(settings.risk,1000)
    risk.observe(T,1000,[])
    risk.observe(T+timedelta(hours=1),960,[])
    assert risk.killed
    assert not risk.check(Side.BUY).allowed
    assert risk.check(Side.SELL).allowed


def test_overnight_loss_is_counted(settings):
    settings.risk.daily_loss=.03
    risk=RiskEngine(settings.risk,1000)
    risk.observe(T+timedelta(hours=23),1000,[])
    risk.observe(T+timedelta(days=1),950,[])
    assert risk.kill_reason=='daily_loss'

@pytest.mark.parametrize('field,expected',[('weekly_loss','weekly_loss'),('max_drawdown','max_drawdown')])
def test_loss_limits(settings,field,expected):
    setattr(settings.risk,field,.05)
    risk=RiskEngine(settings.risk,1000)
    risk.observe(T,940,[])
    assert risk.kill_reason==expected


def test_sizing(settings):
    risk=RiskEngine(settings.risk,1000)
    risk.config.fixed_fraction=.02
    assert risk.target_weight('BTC',.8,100)==.02
    risk.config.sizing='atr'
    risk.config.atr_period=2
    assert risk.target_weight('BTC',.8,100)==0
    for i in range(2): risk.observe_bars({'BTC':Bar(T,'BTC',100,105,95,100,10)})
    assert risk.target_weight('BTC',.8,100)==pytest.approx(.05)
    assert floor_step(.123456,.001)==Decimal('0.123')


def test_execution_rechecks_cash_and_risk(settings):
    settings.execution.fee_rate=.01
    settings.risk.max_symbol_weight=.5
    r=BacktestEngine(settings).run(bars_frame([100,200,200]),Schedule([1,None,None]))
    assert (r.equity.cash>=0).all()
    assert (r.equity.gross/r.equity.equity<=.5+1e-12).all()


def test_zero_volume_no_fill(settings):
    r=BacktestEngine(settings).run(bars_frame([100]*4,volume=0),Schedule([1,None,None,None]))
    assert r.fills.empty
    assert r.equity.iloc[-1].equity==1000


def test_minimum_notional(settings):
    settings.rules.min_notional=600
    r=BacktestEngine(settings).run(bars_frame([100]*4),Schedule([.5,None,None,None]))
    assert r.orders.empty


def test_cancel_on_reverse(settings):
    settings.execution.delay_bars=3
    r=BacktestEngine(settings).run(bars_frame([100]*5),Schedule([.5,0,None,None,None]))
    assert r.fills.empty
    assert r.orders.iloc[0].reason=='target_changed'

@pytest.mark.parametrize('corruption',['nan','duplicate','missing','bad_ohlc','zero_price'])
def test_data_rejects_corruption(corruption):
    frame=bars_frame([100]*4)
    if corruption=='nan': frame.loc[1,'close']=float('nan')
    if corruption=='duplicate': frame.loc[1,'timestamp']=frame.loc[0,'timestamp']
    if corruption=='missing': frame=frame.drop(index=1)
    if corruption=='bad_ohlc': frame.loc[1,'high']=99
    if corruption=='zero_price': frame.loc[1,'close']=0
    with pytest.raises(ValueError): MarketDataEngine(frame,86400)


def test_bad_settings_and_live_blocked():
    with pytest.raises(ValidationError): Settings(live_trading=True)
    with pytest.raises(ValidationError): Settings(execution={'delay_bars':0})
    with pytest.raises(ValidationError): Settings(risk={'max_gross_weight':2})
    with pytest.raises(ValidationError): Settings(unknown=2)
    with pytest.raises(ValidationError): Settings(initial_cash=float('nan'))
    from trading_bot.main import main
    with pytest.raises(SystemExit) as error: main(['live'])
    assert error.value.code==2


def test_mock_contract():
    async def scenario():
        exchange=MockExchange({'BTC':[Bar(T,'BTC',100,101,99,100,10)]})
        assert (await exchange.ticker('BTC'))['last']==100
        assert len(await exchange.ohlcv('BTC',0,10))==1
        assert (await exchange.order_book('BTC'))['bids']
        assert (await exchange.balances())['cash']==100000
        assert await exchange.positions()==[]
        assert (await exchange.fees('BTC'))['taker']==.001
        order=Order('BTC',Side.BUY,1,'s',T,1)
        first=await exchange.create_order(order)
        assert await exchange.create_order(order)==first
        assert (await exchange.order_status(order.id))['status']=='SUBMITTED'
        assert await exchange.fills(order.id)==[]
        assert (await exchange.cancel_order(order.id))['status']=='CANCELLED'
    asyncio.run(scenario())


def test_multi_asset_aggregate_cap(settings):
    import pandas as pd
    a=bars_frame([100]*4); b=a.copy(); b['symbol']='ETH/USDT'
    frame=pd.concat([a,b])
    settings.risk.max_gross_weight=.6
    r=BacktestEngine(settings).run(frame,Schedule([.5,None,None,None]))
    assert len(r.fills)==2
    assert (r.equity.gross/r.equity.equity<=.6+1e-12).all()


def test_future_changes_do_not_change_prefix(settings):
    from trading_bot.strategies import EMACross
    from trading_bot.data.market_data import synthetic_data
    import pandas as pd
    frame=synthetic_data(80,symbols=('BTC/USDT',))
    changed=frame.copy()
    for col in ['open','high','low','close']: changed.loc[40:,col]*=5
    left=BacktestEngine(settings).run(frame,EMACross(3,10))
    right=BacktestEngine(settings).run(changed,EMACross(3,10))
    pd.testing.assert_frame_equal(left.equity.iloc[:41],right.equity.iloc[:41])


def test_stop_pending_buy_on_gap(settings):
    settings.risk.max_price_jump=.2
    r=BacktestEngine(settings).run(bars_frame([100,200,200]),Schedule([1,None,None]))
    assert r.killed
    assert r.fills.empty


def test_loss_streak_and_slippage(settings):
    settings.risk.max_consecutive_losses=2
    risk=RiskEngine(settings.risk,1000)
    risk.observe(T,1000,[{'pnl':-1},{'pnl':-2}])
    assert risk.kill_reason=='consecutive_losses'
    risk=RiskEngine(settings.risk,1000)
    assert not risk.check(Side.BUY,1000).allowed
    assert risk.kill_reason=='excess_slippage'


def test_decimal_quantity_accumulation_can_exit_fully(settings):
    p=Portfolio(1000)
    for q in [.1,.7]: p.apply(Fill('1',T,'BTC','s',Side.BUY,q,100,0,0),{'BTC':100})
    assert p.quantity('BTC')==Decimal('0.8')
    q=floor_step(p.quantity('BTC'),.001)
    p.apply(Fill('2',T,'BTC','s',Side.SELL,q,100,0,0),{'BTC':100})
    assert p.quantity('BTC')==0
    assert len(p.trades)==1
