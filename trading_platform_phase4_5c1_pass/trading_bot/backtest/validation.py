"""Chronological holdouts, train-only grid search and rolling out-of-sample tests."""
from itertools import product
import numpy as np
import pandas as pd
from trading_bot.backtest.engine import BacktestEngine
from trading_bot.strategies import create_strategy
from trading_bot.analytics.metrics import performance


def chronological_split(frame,train_end,test_end):
    t=pd.to_datetime(frame.timestamp,utc=True)
    a,b=pd.Timestamp(train_end),pd.Timestamp(test_end)
    if a.tzinfo is None: a=a.tz_localize('UTC')
    if b.tzinfo is None: b=b.tz_localize('UTC')
    if a>=b: raise ValueError('train_end must precede test_end')
    parts={'train':frame[t<a].copy(),'test':frame[(t>=a)&(t<b)].copy(),'validation':frame[t>=b].copy()}
    if any(p.timestamp.nunique()<2 for p in parts.values()): raise ValueError('each partition needs at least two bars')
    return parts


def grid_search(frame,settings,name,grid,base_params=None):
    """Train-only search. Ranks by neighborhood mean Sharpe, not max return."""
    if not grid or any(not values for values in grid.values()): raise ValueError('nonempty parameter grid required')
    keys=list(grid)
    rows=[]
    for values in product(*(grid[k] for k in keys)):
        params={**(base_params or {}),**dict(zip(keys,values))}
        result=BacktestEngine(settings).run(frame,create_strategy(name,params))
        metrics=performance(result.equity,result.trades,settings.bar_seconds)
        rows.append({'params':params,**metrics})
    for row in rows:
        neighbors=[]
        for candidate in rows:
            distance=sum(abs(grid[k].index(row['params'][k])-grid[k].index(candidate['params'][k])) for k in keys)
            if distance<=1 and candidate['sharpe'] is not None: neighbors.append(candidate['sharpe'])
        row['neighbor_mean_sharpe']=float(np.mean(neighbors)) if neighbors else None
        row['neighbor_std_sharpe']=float(np.std(neighbors)) if neighbors else None
    valid=[r for r in rows if r['sharpe'] is not None and r['neighbor_mean_sharpe'] is not None]
    if not valid: raise ValueError('no candidate with a defined Sharpe ratio')
    selected=max(valid,key=lambda r:r['neighbor_mean_sharpe'])
    warnings=['Multiple parameter tests introduce selection bias; untouched validation remains required.',
              'Neighborhood stability is a heuristic, not a proof against overfitting.']
    if len(rows)<5: warnings.append('Very small parameter grid: weak stability evidence.')
    if selected['number_of_trades']<30: warnings.append('Selected candidate has fewer than 30 completed trades.')
    if selected['neighbor_std_sharpe'] is not None and selected['neighbor_std_sharpe']>0.5:
        warnings.append('High neighborhood sensitivity: possible overfitting.')
    if any(selected['params'][k] in (v[0],v[-1]) for k,v in grid.items() if len(v)>1):
        warnings.append('Selected candidate touches search boundary.')
    return {'selected_params':selected['params'],'candidates':rows,'warnings':warnings}


def walk_forward(frame,settings,name,grid,train_bars=300,test_bars=100,base_params=None):
    times=sorted(pd.to_datetime(frame.timestamp,utc=True).unique())
    if train_bars<2 or test_bars<2: raise ValueError('windows must contain >=2 bars')
    t=pd.to_datetime(frame.timestamp,utc=True)
    folds=[]
    # Non-overlapping test windows. Each fold starts with fresh cash, explicitly.
    for split in range(train_bars,len(times)-test_bars+1,test_bars):
        training=frame[(t>=times[split-train_bars])&(t<times[split])]
        optimization=grid_search(training,settings,name,grid,base_params)
        warm_and_test=frame[(t>=times[split-train_bars])&(t<=times[split+test_bars-1])]
        strategy=create_strategy(name,optimization['selected_params'])
        result=BacktestEngine(settings).run(warm_and_test,strategy,trade_start=times[split])
        metrics=performance(result.equity,result.trades,settings.bar_seconds)
        folds.append({'train_start':str(times[split-train_bars]),'train_end_exclusive':str(times[split]),
                      'test_start':str(times[split]),'test_end_inclusive':str(times[split+test_bars-1]),
                      'selected_params':optimization['selected_params'],'metrics':metrics,'warnings':optimization['warnings']})
    if not folds: raise ValueError('insufficient data for one walk-forward fold')
    return {'folds':folds,'policy':'Independent folds with indicator warm-up and fresh cash; no stitched portfolio return.'}
