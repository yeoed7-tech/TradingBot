"""Measured public-data paper soak; no private exchange API is constructed."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from sqlalchemy import create_engine,text
from trading_bot.config.settings import Settings
from trading_bot.strategies.base_strategy import create_strategy
from trading_bot import strategies  # register built-ins
from trading_bot.paper_trading.runner import run_public_paper

TABLES=['ohlcv','signals','orders','fills','positions','portfolio_snapshots','system_events']

def bytes_used(path):
    p=Path(path)
    return sum(x.stat().st_size for x in p.rglob('*') if x.is_file()) if p.is_dir() else (p.stat().st_size if p.exists() else 0)

def rss_bytes():
    try:return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    except (FileNotFoundError,IndexError,OSError):return None

def counts(url):
    engine=create_engine(url)
    try:
        with engine.connect() as s:return {t:s.execute(text('SELECT count(*) FROM '+t)).scalar() for t in TABLES}
    except Exception:return {}
    finally:engine.dispose()

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='config/paper_upbit.toml')
    parser.add_argument('--hours',type=float,choices=[1,6,24],default=1)
    parser.add_argument('--seconds',type=float,help='short execution window, recorded as such')
    parser.add_argument('--quote-source',choices=['websocket','rest'])
    parser.add_argument('--database',help='dedicated test SQLite database')
    parser.add_argument('--out',default='reports/soak')
    parser.add_argument('--sample-seconds',type=float,default=30)
    args=parser.parse_args()
    s=Settings.load(args.config)
    if args.database:
        path=Path(args.database);path.parent.mkdir(parents=True,exist_ok=True)
        s.persistence.database_url='sqlite:///'+str(path.resolve())
    if args.quote_source:s.paper_trading.quote_source=args.quote_source
    if not s.persistence.enabled:raise ValueError('soak requires durable paper database')
    output=Path(args.out);output.mkdir(parents=True,exist_ok=True)
    duration=args.seconds if args.seconds is not None else args.hours*3600
    task=asyncio.create_task(run_public_paper(s,create_strategy(s.strategy.name,s.strategy.params),output/'session',duration))
    started_at=datetime.now(timezone.utc).isoformat()
    initial_rss=rss_bytes()
    self_metrics=(output/'runtime_self.jsonl').open('w',encoding='utf-8')
    self_metrics.write(json.dumps({'elapsed_seconds':0,'rss_bytes':initial_rss,
        'cpu_seconds':os.times().user+os.times().system})+'\n');self_metrics.flush()
    samples=[];start=asyncio.get_running_loop().time()
    while not task.done():
        await asyncio.sleep(min(args.sample_seconds,max(0.1,duration-(asyncio.get_running_loop().time()-start)+2)))
        url=s.persistence.database_url
        db_path=url.removeprefix('sqlite:///') if url.startswith('sqlite:///') else ''
        samples.append({'at':datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds':asyncio.get_running_loop().time()-start,'rss_bytes':rss_bytes(),
            'db_bytes':bytes_used(db_path) if db_path else None,
            'log_bytes':bytes_used('logs'),'table_counts':counts(url)})
        self_metrics.write(json.dumps({'elapsed_seconds':samples[-1]['elapsed_seconds'],
            'rss_bytes':samples[-1]['rss_bytes'],
            'cpu_seconds':os.times().user+os.times().system})+'\n');self_metrics.flush()
    self_metrics.close()
    result=await task
    ended_at=datetime.now(timezone.utc).isoformat()
    final_rss=rss_bytes()
    rss=[v for v in [initial_rss,final_rss,*(x['rss_bytes'] for x in samples)] if v is not None]
    final_counts=counts(s.persistence.database_url)
    feed=result.get('feed_metrics',{})
    report={'start':started_at,'end':ended_at,'requested_seconds':duration,
            'duration':asyncio.get_running_loop().time()-start,
            'rss_min':min(rss) if rss else None,'rss_max':max(rss) if rss else None,
            'rss_delta':final_rss-initial_rss if final_rss is not None and initial_rss is not None else None,
            'db_size':bytes_used(s.persistence.database_url.removeprefix('sqlite:///')) if s.persistence.database_url.startswith('sqlite:///') else None,
            'log_size':bytes_used('logs'),'orders':result['simulated_orders'],
            'fills':result['simulated_fills'],'signals':final_counts.get('signals',0),
            'reconnects':result.get('websocket_reconnects',0),
            'stale':feed.get('stale_events',0),'gaps':feed.get('gap_events',0),
            'duplicates':feed.get('duplicate_events',0)+result.get('websocket_duplicate_events',0),
            'rest_requests':feed.get('rest_requests',0),
            'exceptions':int(bool(result.get('error') or result.get('shutdown_error'))),
            'risk_halt':result['risk_killed'],'lease_token':result.get('lease_token'),
            'final_cash':(result.get('last_snapshot') or {}).get('cash'),
            'final_equity':(result.get('last_snapshot') or {}).get('equity'),
            'final_pnl':str(Decimal(str((result.get('last_snapshot') or {}).get('equity')))-
                Decimal(str(s.paper_trading.starting_cash))) if result.get('last_snapshot') else None,
            'final_realized_pnl':(result.get('last_snapshot') or {}).get('realized_pnl'),
            'live_private_http_call_count':result['real_order_http_requests'],
            'quote_source':s.paper_trading.quote_source,'table_counts':final_counts,
            'samples':samples,'result':result}
    (output/'soak.json').write_text(json.dumps(report,default=str,indent=2),encoding='utf-8')
    print(json.dumps({'actual_seconds':report['duration'],'samples':len(samples),
                      'status':result['status'],'ws_reconnects':result.get('websocket_reconnects'),
                      'orders':result['simulated_orders'],'fills':result['simulated_fills'],
                      'real_order_http_requests':result['real_order_http_requests']}))

if __name__=='__main__':asyncio.run(main())
