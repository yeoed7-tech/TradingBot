"""One-command public-only one-hour Paper acceptance on a persistent local/VM host."""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

D=Decimal
UNIT=D('0.000000000000000000000001')
def now():return datetime.now(timezone.utc).isoformat()
def emit(path,obj):Path(path).write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8')
def size(path):return Path(path).stat().st_size if Path(path).exists() else 0
def tree_size(path):return sum(x.stat().st_size for x in Path(path).rglob('*') if x.is_file()) if Path(path).exists() else 0
def source_hash():
    h=hashlib.sha256()
    for p in sorted(Path('trading_bot').rglob('*.py')):h.update(str(p).encode());h.update(p.read_bytes())
    return h.hexdigest()
def child_metrics(path):
    try:
        rows=Path(path).read_text().splitlines()
        return json.loads(rows[-1]) if rows else {}
    except (OSError,ValueError):return {}
def snapshot(path):
    if not Path(path).exists():return {}
    try:
        con=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True,timeout=2)
        con.row_factory=sqlite3.Row
        result={}
        for table in ('ohlcv','signals','orders','fills','portfolio_snapshots','system_events'):
            result[table]=con.execute('SELECT count(*) FROM '+table).fetchone()[0]
        a=con.execute('SELECT cash,fees,realized_pnl,fill_count FROM accounts LIMIT 1').fetchone()
        if a:result.update(cash=a[0],fees=a[1],realized_pnl=a[2],fill_count=a[3])
        positions=con.execute('SELECT symbol,quantity,cost FROM positions').fetchall()
        result['positions']={p[0]:{'quantity':p[1],'cost':p[2]} for p in positions}
        snap=con.execute('SELECT equity,unrealized_pnl FROM portfolio_snapshots ORDER BY id DESC LIMIT 1').fetchone()
        if snap:result.update(equity=snap[0],unrealized_pnl=snap[1])
        lease=con.execute('SELECT owner_id,fencing_token FROM trader_leases LIMIT 1').fetchone()
        if lease:result.update(owner_id=lease[0],fencing_token=lease[1])
        hb=con.execute("SELECT timestamp FROM heartbeats WHERE component='process' LIMIT 1").fetchone()
        result['process_heartbeat']=hb[0] if hb else None
        result['risk_halt']=bool(con.execute('SELECT killed FROM risk_state LIMIT 1').fetchone()[0]) if con.execute('SELECT count(*) FROM risk_state').fetchone()[0] else None
        result['rejected_orders']=con.execute("SELECT count(*) FROM orders WHERE status='REJECTED'").fetchone()[0]
        result['error_events']=con.execute("SELECT count(*) FROM system_events WHERE level IN ('ERROR','CRITICAL')").fetchone()[0]
        con.close();return result
    except (sqlite3.Error,OSError) as exc:return {'observation_error':type(exc).__name__+': '+str(exc)[:160]}
def regression(log):
    result=subprocess.run([sys.executable,'-m','pytest','-q'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    Path(log).write_text(result.stdout,encoding='utf-8')
    return {'exit_code':result.returncode,'summary':result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''}
def slope(points):
    data=[(float(p['elapsed_seconds']),float(p['rss_bytes'])) for p in points if p['rss_bytes'] not in ('',None)]
    if len(data)<3:return None
    mx=sum(t for t,_ in data)/len(data);my=sum(y for _,y in data)/len(data)
    den=sum((t-mx)**2 for t,_ in data)
    return 3600*sum((t-mx)*(y-my) for t,y in data)/den if den else None

def independent_check(database,report):
    if not Path(database).exists():return {'status':'NOT RUN','reason':'database missing'}
    result=report.get('result',{})
    con=sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro',uri=True);con.row_factory=sqlite3.Row
    mismatches=[]
    def eq(label,a,b):
        if a!=b:mismatches.append({'field':label,'actual':str(a),'expected':str(b)})
    try:
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        a=con.execute('SELECT * FROM accounts LIMIT 1').fetchone()
        if a is None:return {'status':'FAIL','reason':'account missing'}
        with localcontext() as ctx:
            ctx.prec=65
            q=lambda v:D(str(v)).quantize(UNIT,rounding=ROUND_HALF_EVEN)
            cash=D(str(a['initial_cash']));fees=realized=D(0);positions={}
            fills=con.execute('SELECT * FROM fills ORDER BY rowid').fetchall()
            for f in fills:
                symbol=f['symbol'];p=positions.setdefault(symbol,{'quantity':D(0),'cost':D(0)})
                qty=D(str(f['quantity']));price=D(str(f['price']));fee=D(str(f['fee']))
                value=q(qty*price);fees=q(fees+fee)
                if f['side']=='BUY':
                    cash=q(cash-value-fee);p['quantity']+=qty;p['cost']=q(p['cost']+value+fee)
                    eq('fill.realized:'+f['exchange_fill_id'],D(str(f['realized_pnl'])),D(0))
                elif f['side']=='SELL' and qty<=p['quantity']:
                    basis=p['cost'] if qty==p['quantity'] else q(p['cost']*qty/p['quantity'])
                    pnl=q(value-fee-basis);eq('fill.realized:'+f['exchange_fill_id'],D(str(f['realized_pnl'])),pnl)
                    cash=q(cash+value-fee);realized=q(realized+pnl)
                    p['quantity']-=qty;p['cost']=q(p['cost']-basis)
                    if p['quantity']==0:p['cost']=D(0)
                else:mismatches.append({'field':'invalid_sell_or_side','fill_id':f['exchange_fill_id']})
        for name,expected in [('cash',cash),('fees',fees),('realized_pnl',realized)]:
            eq('db.'+name,D(str(a[name])),expected)
            runtime=(result.get('last_snapshot') or {}).get(name)
            if runtime is not None:eq('runtime.'+name,D(str(runtime)),expected)
        eq('fill_count',a['fill_count'],len(fills));eq('runtime.fill_count',result.get('simulated_fills'),len(fills))
        db_positions=con.execute('SELECT symbol,quantity,cost FROM positions').fetchall()
        for row in db_positions:
            p=positions.get(row['symbol'],{'quantity':D(0),'cost':D(0)})
            eq('db.quantity:'+row['symbol'],D(str(row['quantity'])),p['quantity'])
            eq('db.cost:'+row['symbol'],D(str(row['cost'])),p['cost'])
            eq('runtime.cost:'+row['symbol'],D(str(result.get('position_cost_basis',{}).get(row['symbol'],0))),p['cost'])
            eq('runtime.quantity:'+row['symbol'],D(str((result.get('last_snapshot') or {}).get('positions',{}).get(row['symbol'],{}).get('quantity',0))),p['quantity'])
        for symbol,p in positions.items():
            if p['quantity']>0 and not any(r['symbol']==symbol for r in db_positions):mismatches.append({'field':'missing_position','symbol':symbol})
        latest=con.execute('SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1').fetchone()
        if latest:
            eq('snapshot.cash',D(str(latest['cash'])),cash)
            eq('snapshot.equity',D(str(latest['equity'])),D(str(latest['cash']))+D(str(latest['market_value'])))
            eq('snapshot.unrealized',D(str(latest['unrealized_pnl'])),D(str(latest['market_value']))-sum((p['cost'] for p in positions.values()),D(0)))
        risk=con.execute('SELECT * FROM risk_state LIMIT 1').fetchone()
        if risk:
            for name in ('peak','day_start','week_start'):
                eq('risk.'+name,D(str(risk[name])),D(str(result.get('risk_state',{}).get(name))))
            eq('risk.killed',bool(risk['killed']),bool(result.get('risk_state',{}).get('killed')))
        cursor=con.execute('SELECT timestamp FROM market_cursors LIMIT 1').fetchone()
        eq('cursor',cursor[0] if cursor else None,result.get('market_cursor'))
        open_ids=[x[0] for x in con.execute("SELECT internal_order_id FROM orders WHERE status IN ('CREATED','SUBMITTED','PARTIALLY_FILLED')")]
        eq('open_orders',sorted(open_ids),sorted(result.get('open_orders',[])))
        count_orders=con.execute('SELECT count(*) FROM orders').fetchone()[0]
        eq('orders',count_orders,result.get('simulated_orders'))
        duplicates={t:con.execute(f'SELECT count(*)-count(DISTINCT {col}) FROM {t}').fetchone()[0]
            for t,col in (('orders','internal_order_id'),('fills','exchange_fill_id'))}
        duplicates['client_order_ids']=con.execute('SELECT count(*)-count(DISTINCT client_order_id) FROM orders').fetchone()[0]
        duplicates['ohlcv']=con.execute('SELECT count(*) FROM (SELECT 1 FROM ohlcv GROUP BY exchange,symbol,timeframe,timestamp HAVING count(*)>1)').fetchone()[0]
        if any(duplicates.values()):mismatches.append({'field':'duplicates','values':duplicates})
        eq('integrity',integrity,'ok');eq('runtime_reconciliation',result.get('reconciliation_ok'),True)
        return {'status':'PASS' if not mismatches else 'FAIL','mismatches':mismatches,'integrity':integrity,
            'duplicates':duplicates,'computed':{'cash':str(cash),'fees':str(fees),'realized_pnl':str(realized),
            'positions':{s:{k:str(v) for k,v in p.items()} for s,p in positions.items()}},
            'fills':len(fills),'orders':count_orders,'open_orders':open_ids,'cursor':cursor[0] if cursor else None}
    finally:con.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='config/paper_upbit.toml')
    p.add_argument('--database',default='reports/phase45c1/paper_1h.sqlite3')
    p.add_argument('--out',default='reports/phase45c1')
    p.add_argument('--sample-seconds',type=float,default=30)
    p.add_argument('--seconds',type=float,help='diagnostic only; never qualifies as one-hour acceptance')
    args=p.parse_args()
    from trading_bot.config.settings import Settings
    settings=Settings.load(args.config)
    if settings.live_trading or not settings.persistence.enabled or not settings.persistence.single_writer or settings.paper_trading.quote_source!='websocket':
        raise SystemExit('C1 requires fenced durable Public WebSocket Paper configuration')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    database=str(Path(args.database).resolve())
    if Path(database).exists():raise SystemExit('C1 requires a fresh database path')
    baseline=regression(out/'regression_before.txt')
    if baseline['exit_code']!=0:raise SystemExit('regression failed before soak')
    start=now();initial_log=tree_size('logs')
    command=[sys.executable,'-m','scripts.soak_paper','--config',args.config, '--database',database,'--out',str(out),
             '--quote-source','websocket','--sample-seconds',str(args.sample_seconds)]
    command+=['--seconds',str(args.seconds)] if args.seconds is not None else ['--hours','1']
    with (out/'runner.log').open('w') as logfile:
        child=subprocess.Popen(command,stdout=logfile,stderr=subprocess.STDOUT)
        state={'start':start,'pid':child.pid,'source_sha256':source_hash(),
            'config':settings.model_dump(mode='json'),'config_path':str(Path(args.config).resolve()),
            'config_sha256':hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
            'database':database,'command':command,'initial_rss':None,
            'initial_db_size':size(database),'initial_log_size':initial_log,'regression_before':baseline}
        emit(out/'start_state.json',state)
        fields=['at','elapsed_seconds','rss_bytes','cpu_seconds','db_bytes','log_bytes','ohlcv','signals','orders','fills','portfolio_snapshots','system_events','cash','fees','realized_pnl','fill_count','equity','unrealized_pnl','positions','owner_id','fencing_token','process_heartbeat','risk_halt','rejected_orders','error_events','observation_error']
        samples=[];clock=time.monotonic()
        with (out/'runtime_metrics.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();f.flush()
            while child.poll() is None:
                time.sleep(args.sample_seconds)
                observed_self=child_metrics(out/'runtime_self.jsonl')
                if state['initial_rss'] is None and (out/'runtime_self.jsonl').exists():
                    try:state['initial_rss']=json.loads((out/'runtime_self.jsonl').read_text().splitlines()[0])['rss_bytes']
                    except (IndexError,ValueError,OSError):pass
                row={'at':now(),'elapsed_seconds':time.monotonic()-clock,
                    'rss_bytes':observed_self.get('rss_bytes'),'cpu_seconds':observed_self.get('cpu_seconds'),
                    'db_bytes':size(database),'log_bytes':tree_size('logs')}
                observed=snapshot(database)
                if observed.get('owner_id') and 'writer_owner_id' not in state:
                    state.update(writer_owner_id=observed['owner_id'],fencing_token=observed.get('fencing_token'))
                    emit(out/'start_state.json',state)
                row.update({k:json.dumps(v,default=str) if isinstance(v,dict) else v for k,v in observed.items()})
                writer.writerow({k:row.get(k) for k in fields});f.flush();samples.append(row)
        exit_code=child.wait();elapsed=time.monotonic()-clock
    report=json.loads((out/'soak.json').read_text()) if (out/'soak.json').exists() else {}
    result=report.get('result',{});transport=result.get('adapter_audit',{}).get('transport',{})
    network={'public_rest_count':transport.get('public_http_attempts'),
        'public_websocket_messages':result.get('websocket_received'),
        'public_websocket_connections':None if 'websocket_reconnects' not in result else result['websocket_reconnects']+1,
        'private_api_count':result.get('private_http_requests'),
        'order_http_count':result.get('real_order_http_requests'),
        'cancel_http_count':result.get('real_cancel_http_requests'),
        'blocked_attempts':result.get('blocked_requests'),'transport':transport}
    emit(out/'network_audit.json',network)
    reconciliation=independent_check(database,report) if report else {'status':'NOT RUN','reason':'no final runner output'}
    emit(out/'reconciliation.json',reconciliation)
    post=regression(out/'regression_after.txt')
    rss=[int(x['rss_bytes']) for x in samples if x.get('rss_bytes') is not None]
    cache=result.get('cache_sizes',{});limit=settings.persistence.recent_cache_limit
    bounded=bool(cache) and all(v<=limit for v in cache.values())
    tail=[x for x in samples if float(x['elapsed_seconds'])>=max(0,elapsed/2)]
    tail_slope=slope(tail)
    technical=(exit_code==0 and elapsed>=3600 and result.get('status')=='NORMAL' and
        result.get('reconciliation_ok') is True and reconciliation['status']=='PASS' and bounded and
        not result.get('error') and not result.get('shutdown_error') and
        all(network[k]==0 for k in ('private_api_count','order_http_count','cancel_http_count','blocked_attempts')) and
        post['exit_code']==0 and report.get('feed_metrics',{}).get('gap_events',0)==0 and
        report.get('feed_metrics',{}).get('stale_events',0)==0 and not any(x.get('observation_error') for x in samples))
    memory_ok=tail_slope is not None and tail_slope<10_000_000
    verdict=('NOT RUN' if args.seconds is not None else
             'PASS' if technical and memory_ok else
             'ENVIRONMENT_LIMITATION' if elapsed<3600 and exit_code!=0 and not report else 'FAILED')
    summary={'verdict':verdict,'start':start,'end':now(),'elapsed_seconds':elapsed,'child_exit_code':exit_code,
        'regression_before':baseline,'regression_after':post,'start_state':state,
        'rss_start':state['initial_rss'],
        'rss_end':state['initial_rss']+report['rss_delta'] if report.get('rss_delta') is not None and state['initial_rss'] is not None else (rss[-1] if rss else None),
        'rss_max':report.get('rss_max') if report else (max(rss) if rss else None),
        'rss_delta':report.get('rss_delta') if report else ((rss[-1]-state['initial_rss']) if rss and state['initial_rss'] is not None else None),
        'rss_slope_bytes_per_hour':slope(samples),'rss_tail_slope_bytes_per_hour':tail_slope,
        'db_start':state['initial_db_size'],'db_end':size(database),'db_delta':size(database)-state['initial_db_size'],
        'log_start':initial_log,'log_end':tree_size('logs'),
        'row_start':{},'row_end':snapshot(database),'feed_metrics':result.get('feed_metrics'),
        'ws_reconnects':result.get('websocket_reconnects'),'ws_messages':result.get('websocket_received'),
        'cache_sizes':cache,'cache_limit':limit,'bounded':bounded,
        'orders':result.get('simulated_orders'),'fills':result.get('simulated_fills'),
        'network_audit':network,'reconciliation':reconciliation['status'],
        'errors':{k:result.get(k) for k in ('error','shutdown_error') if result.get(k)}}
    emit(out/'soak_summary.json',summary)
    print(json.dumps({'verdict':verdict,'elapsed_seconds':elapsed,'reconciliation':reconciliation['status'],
                      'regression_after':post['summary']}))
    return 0 if verdict=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
