from pathlib import Path
import json
import html
import hashlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from .metrics import performance,monthly_returns

STYLE='''body{background:#0d1321;color:#e6edf8;font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 24px}h1{font-size:34px}h2{margin-top:36px}p{color:#b5c5db;line-height:1.6}.tag{color:#7fe0c1}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;text-align:right;border-bottom:1px solid #304057}td:first-child,th:first-child{text-align:left}img{width:100%;background:#fff;border-radius:10px}a{color:#7fe0c1}'''

def write_report(result,destination,source='user-supplied OHLCV'):
    out=Path(destination); out.mkdir(parents=True,exist_ok=True)
    e=result.equity
    metrics=performance(e,result.trades,result.settings.bar_seconds)
    benchmark=performance(e,None,result.settings.bar_seconds,'benchmark')
    warnings=['No expected return or future profitability is implied.',
              'Universe/delisting history is unverified; survivorship bias may be present.',
              'Bar-open fills, prior-bar volume cap; no order-book queue or intrabar limit fills.',
              'Open positions marked to final close; not force-liquidated. Trade stats include completed flat-to-flat episodes only.',
              'Benchmark: frictionless equal-weight buy & hold of input assets; excludes fees and slippage.',
              'ATR sizing is a risk budget, NOT a guaranteed per-trade loss limit; stop orders are not implemented.']
    if result.killed: warnings.append('New BUY orders halted by risk engine: '+result.kill_reason)
    if len(result.trades)<30: warnings.append('Fewer than 30 closed trades: weak statistical evidence.')
    if len(e)<366: warnings.append('Short evaluation window: annualized metrics may be unstable.')
    payload={'label':result.label,'source':source,'metrics':metrics,'benchmark':benchmark,'warnings':warnings,
             'config':result.settings.model_dump(),'metric_conventions':{'risk_free_rate':0,
             'annualization_days':365.25,'sortino':'RMS of negative returns with zero for nonnegative returns',
             'trade_unit':'flat-to-flat position episode including entry/exit fees',
             'exposure':'fraction of end-of-bar observations with any position',
             'undefined_ratios':'null, including no losing trades'}}
    (out/'metrics.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    e.to_csv(out/'equity.csv')
    result.fills.to_csv(out/'fills.csv',index=False)
    result.orders.to_csv(out/'orders.csv',index=False)
    result.trades.to_csv(out/'trades.csv',index=False)
    monthly_returns(e).to_csv(out/'monthly_returns.csv')
    result.journal.save(out/'events.jsonl')
    fig,axes=plt.subplots(3,2,figsize=(15,12),layout='constrained')
    axes[0,0].plot(e.index,(e.equity/e.equity.iloc[0]-1)*100,color='#168b79')
    axes[0,0].set_title('Cumulative strategy return (%)')
    axes[0,1].plot(e.index,e.equity/e.equity.iloc[0],label='Strategy (net)')
    axes[0,1].plot(e.index,e.benchmark/e.benchmark.iloc[0],label='Equal-weight B&H (gross)')
    axes[0,1].legend(); axes[0,1].set_title('Benchmark comparison')
    axes[1,0].fill_between(e.index,(e.equity/e.equity.cummax()-1)*100,0,color='#cd6370')
    axes[1,0].set_title('Drawdown (%)')
    m=monthly_returns(e)*100
    axes[1,1].bar(m.index,m.values,width=20,color=['#168b79' if x>=0 else '#cd6370' for x in m])
    axes[1,1].set_title('Monthly return (%)')
    for col in e.columns:
        if col.startswith('position:'): axes[2,0].plot(e.index,e[col],label=col[9:])
    axes[2,0].set_title('Position quantities'); axes[2,0].legend()
    if not result.fills.empty:
        for (symbol,side),f in result.fills.groupby(['symbol','side']):
            axes[2,1].scatter(pd.to_datetime(f.timestamp),f.price,s=18,marker='^' if side=='BUY' else 'v',label=f'{symbol} {side}')
        axes[2,1].legend(fontsize=8)
    axes[2,1].set_title('Execution timestamps / prices')
    for ax in axes.flat:
        ax.grid(alpha=.2); ax.tick_params(axis='x',rotation=25,labelsize=8)
    fig.savefig(out/'charts.png',dpi=130); plt.close(fig)
    def fmt(v): return 'N/A' if v is None else f'{v:,.5f}' if isinstance(v,float) else str(v)
    table=''.join(f'<tr><td>{html.escape(k)}</td><td>{fmt(v)}</td><td>{fmt(benchmark.get(k))}</td></tr>' for k,v in metrics.items())
    (out/'index.html').write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Research report</title><style>{STYLE}</style>
    <p class="tag">RESEARCH PLATFORM · PHASE 1–2 · OFFLINE</p><h1>{html.escape(result.label)}</h1>
    <p>Source: {html.escape(source)}. {e.index[0]} — {e.index[-1]}. Returns and weights in the table are fractions.</p>
    <img src="charts.png" alt="Six performance charts"><h2>Performance</h2><table><tr><th>Metric</th><th>Strategy</th><th>Gross benchmark</th></tr>{table}</table>
    <h2>Interpretation & limits</h2><ul>{''.join('<li>'+html.escape(w)+'</li>' for w in warnings)}</ul>
    <p><a href="metrics.json">Metrics & config</a> · <a href="equity.csv">Equity</a> · <a href="fills.csv">Fills</a> · <a href="events.jsonl">Event journal</a></p></html>''',encoding='utf-8')
    return metrics

def compare(results,destination,source):
    out=Path(destination); out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name,result in results.items():
        rows.append({'strategy':name,**write_report(result,out/name,source)})
    frame=pd.DataFrame(rows).set_index('strategy')
    frame.to_csv(out/'comparison.csv')
    table=frame[['cagr','max_drawdown','sharpe','sortino','total_return','number_of_trades']].to_html(float_format=lambda x:f'{x:.4f}')
    links=' · '.join(f'<a href="{html.escape(name)}/index.html">{html.escape(name)}</a>' for name in results)
    (out/'index.html').write_text(f'<!doctype html><meta charset="utf-8"><title>Strategy comparison</title><style>{STYLE}</style><p class="tag">RESEARCH PLATFORM · PHASE 1–2</p><h1>Strategy comparison</h1><p>{html.escape(source)} — test fixtures, not investment evidence.</p>{table}<p>{links}</p>',encoding='utf-8')
    return frame
