from datetime import timedelta
import json
import pandas as pd
import pytest
from conftest import T,bars_frame,Schedule
from trading_bot.strategies import EMACross,RSIMeanReversion,VolatilityBreakout,create_strategy
from trading_bot.strategies.ensemble import StrategyPortfolio
from trading_bot.core.events.models import Bar
from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.validation import chronological_split,grid_search,walk_forward
from trading_bot.analytics.metrics import performance
from trading_bot.analytics.report import write_report
from trading_bot.data.market_data import synthetic_data


def feed(strategy,prices):
    return [strategy.on_data({'BTC':Bar(T+timedelta(days=i),'BTC',p,p,p,p,100)})[0].target_weight for i,p in enumerate(prices)]

def test_ema_warmup_and_reversal():
    s=feed(EMACross(2,4),[1,2,3,4,5,4,2,1])
    assert s[:3]==[None]*3
    assert s[3]==.4
    assert s[-1]==0

def test_rsi_extremes_and_flat():
    assert feed(RSIMeanReversion(3),[4,3,2,1])[-1]==.4
    assert feed(RSIMeanReversion(3),[1,2,3,4])[-1]==0
    assert feed(RSIMeanReversion(3),[1,1,1,1])[-1]==0

def test_breakout_uses_previous_range():
    s=VolatilityBreakout(.5)
    assert s.on_data({'BTC':Bar(T,'BTC',100,110,90,100,1)})[0].target_weight is None
    assert s.on_data({'BTC':Bar(T+timedelta(days=1),'BTC',100,115,99,111,1)})[0].target_weight==.4


def test_plugins_and_ensemble():
    assert isinstance(create_strategy('trading_bot.strategies.ema_cross:EMACross',{'fast':2,'slow':4}),EMACross)
    with pytest.raises(ValueError): create_strategy('absent')
    s=StrategyPortfolio([(.4,Schedule([1,None])),(.6,Schedule([0,1]))])
    assert feed(s,[100,101])==[.4,1.]


def test_metric_hand_calculation():
    e=pd.DataFrame({'equity':[100,110,99],'gross':[0,100,99],'benchmark':[100,100,100]},index=pd.date_range(T,periods=3,freq='D'))
    trades=pd.DataFrame({'pnl':[10.,-5.,0.],'holding_seconds':[3600,7200,10800]})
    m=performance(e,trades)
    assert m['total_return']==pytest.approx(-.01)
    assert m['max_drawdown']==pytest.approx(-.1)
    assert m['sharpe']==pytest.approx(0,abs=1e-12)
    assert m['profit_factor']==2
    assert m['payoff_ratio']==2
    assert m['average_holding_hours']==2
    assert m['win_rate']==pytest.approx(1/3)
    assert m['exposure']==1


def test_undefined_metrics_are_null():
    e=pd.DataFrame({'equity':[100.,100.,100.],'gross':[0.,0.,0.]},index=pd.date_range(T,periods=3))
    m=performance(e)
    assert m['sharpe'] is m['sortino'] is m['profit_factor'] is m['calmar'] is None
    assert m['number_of_trades']==0
    json.dumps(m,allow_nan=False)


def test_report_output(settings,tmp_path):
    r=BacktestEngine(settings).run(bars_frame([100,100,110,110]),Schedule([.5,0,None,None]))
    m=write_report(r,tmp_path,'SYNTHETIC test')
    assert m['number_of_trades']==1
    assert (tmp_path/'charts.png').stat().st_size>1000
    assert (tmp_path/'index.html').exists()
    assert json.loads((tmp_path/'metrics.json').read_text())['source']=='SYNTHETIC test'


def test_chronological_split():
    frame=synthetic_data(50,symbols=('BTC/USDT',))
    parts=chronological_split(frame,'2022-01-21','2022-02-10')
    assert [len(p) for p in parts.values()]==[20,20,10]
    assert parts['train'].timestamp.max()<parts['test'].timestamp.min()
    assert parts['test'].timestamp.max()<parts['validation'].timestamp.min()


def test_grid_and_walkforward(settings):
    frame=synthetic_data(70,symbols=('BTC/USDT',))
    grid={'fast':[2,3],'slow':[6,8]}
    search=grid_search(frame.iloc[:30],settings,'ema_cross',grid)
    assert len(search['candidates'])==4
    assert 'neighbor_std_sharpe' in search['candidates'][0]
    result=walk_forward(frame,settings,'ema_cross',grid,30,20)
    assert len(result['folds'])==2
    assert result['folds'][0]['test_end_inclusive']<result['folds'][1]['test_start']
    changed=frame.copy()
    for col in ['open','high','low','close']: changed.loc[30:,col]*=2
    altered=walk_forward(changed,settings,'ema_cross',grid,30,20)
    assert altered['folds'][0]['selected_params']==result['folds'][0]['selected_params']


def test_warmup_does_not_trade(settings):
    frame=bars_frame([100]*10)
    r=BacktestEngine(settings).run(frame,Schedule([.5]*10),trade_start=T+timedelta(days=5))
    assert r.equity.index[0]==T+timedelta(days=5)
    assert r.fills.iloc[0].timestamp>=T+timedelta(days=6)
