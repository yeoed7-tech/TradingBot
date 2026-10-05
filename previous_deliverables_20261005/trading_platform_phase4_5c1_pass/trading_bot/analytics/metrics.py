import math
import numpy as np
import pandas as pd

YEAR_SECONDS=365.25*86400

def performance(equity,trades=None,bar_seconds=86400,value_column='equity'):
    values=equity[value_column].astype(float)
    if len(values)<2 or (values<=0).any(): raise ValueError('positive equity with >=2 samples required')
    returns=values.pct_change().dropna()
    total=values.iloc[-1]/values.iloc[0]-1
    seconds=(values.index[-1]-values.index[0]).total_seconds()
    years=seconds/YEAR_SECONDS
    annual=YEAR_SECONDS/bar_seconds
    std=float(returns.std(ddof=1)) if len(returns)>1 else 0.
    downside=float(np.sqrt(np.mean(np.minimum(returns,0)**2)))
    dd=values/values.cummax()-1
    mdd=float(dd.min())
    cagr=float(np.expm1(np.log1p(total)/years)) if years>0 else None
    pnl=trades['pnl'] if trades is not None and not trades.empty else pd.Series(dtype=float)
    wins=pnl[pnl>0]
    losses=pnl[pnl<0]
    avg_win=float(wins.mean()) if len(wins) else None
    avg_loss=float(losses.mean()) if len(losses) else None
    result={
        'total_return':float(total),'cagr':cagr,
        'sharpe':float(returns.mean()/std*math.sqrt(annual)) if std>1e-15 else None,
        'sortino':float(returns.mean()/downside*math.sqrt(annual)) if downside>1e-15 else None,
        'max_drawdown':mdd,'calmar':cagr/abs(mdd) if mdd<0 else None,
        'win_rate':float((pnl>0).mean()) if len(pnl) else None,
        'profit_factor':float(wins.sum()/abs(losses.sum())) if len(losses) else None,
        'average_win':avg_win,'average_loss':avg_loss,
        'payoff_ratio':avg_win/abs(avg_loss) if avg_win is not None and avg_loss is not None else None,
        'number_of_trades':len(pnl),
        'average_holding_hours':float(trades.holding_seconds.mean()/3600) if len(pnl) else None,
        'exposure':float((equity.gross.iloc[1:]>0).mean()) if 'gross' in equity and value_column=='equity' else None,
        'volatility':std*math.sqrt(annual),
    }
    return {k:None if isinstance(v,float) and not math.isfinite(v) else v for k,v in result.items()}

def monthly_returns(equity):
    month_end=equity.equity.resample('ME').last()
    result=month_end.pct_change()
    if len(result): result.iloc[0]=month_end.iloc[0]/equity.equity.iloc[0]-1
    return result
