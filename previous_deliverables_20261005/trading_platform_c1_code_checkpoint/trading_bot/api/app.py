"""Read-only API and small dashboard. Own DB connection, no trading engine."""
from html import escape
from fastapi import FastAPI, HTTPException, Request
import os
import hmac
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from datetime import datetime,timezone
from trading_bot.persistence.ledger import PaperLedger,redact
from trading_bot.persistence.models import (PositionRow,OrderRow,FillRow,StrategyRun,
                                               RiskStateRow,SystemEventRow,SnapshotRow)

def create_app(database_url,account='paper'):
    app=FastAPI(title='Paper Trading Monitor',docs_url=None,redoc_url=None)
    ledger=PaperLedger(database_url,account)
    @app.middleware('http')
    async def optional_local_auth(request:Request,call_next):
        configured=os.environ.get('PAPER_MONITOR_TOKEN')
        if configured and not hmac.compare_digest(request.headers.get('x-monitor-token',''),configured):
            return JSONResponse({'detail':'unauthorized'},status_code=401)
        return await call_next(request)
    @app.get('/health')
    def health():
        try:
            s=ledger.status();parts=[s[k] for k in ('application','database','market_feed','broker','strategy','risk_engine')]
            s['status']='HALTED' if 'HALTED' in parts else ('DEGRADED' if 'DEGRADED' in parts else 'HEALTHY')
            return redact({k:s[k] for k in ('status','application','database','market_feed','broker','strategy','risk_engine','heartbeats','lease_active')})
        except Exception:raise HTTPException(503,detail='database unavailable')
    @app.get('/status')
    def status():return redact(ledger.status())
    @app.get('/portfolio')
    def portfolio():
        with ledger.Session() as s:
            rows=s.scalars(select(SnapshotRow).where(SnapshotRow.account==account).order_by(SnapshotRow.id.desc())).all()
            if not rows:return {'status':'NO_SNAPSHOT'}
            x=rows[0]
            today=datetime.now(timezone.utc).date().isoformat()
            day_rows=[r for r in rows if r.timestamp.startswith(today)]
            day_start=day_rows[-1].equity if day_rows else x.equity
            return {'timestamp':x.timestamp,'cash':x.cash,'market_value':x.market_value,
                'equity':x.equity,'realized_pnl':x.realized_pnl,'unrealized_pnl':x.unrealized_pnl,
                'fees':x.fees,'drawdown':x.drawdown,'today_pnl':x.equity-day_start}
    @app.get('/positions')
    def positions():
        with ledger.Session() as s:
            return [{'symbol':r.symbol,'quantity':r.quantity,'average_entry_price':r.average_entry_price,
                'realized_pnl':r.realized_pnl} for r in s.scalars(select(PositionRow).where(PositionRow.account==account))]
    @app.get('/orders')
    def orders():
        with ledger.Session() as s:
            return [{'id':r.internal_order_id,'client_order_id':r.client_order_id,'symbol':r.symbol,
                'side':r.side,'status':r.status,'quantity':r.quantity,'filled':r.filled}
                for r in s.scalars(select(OrderRow).order_by(OrderRow.created_at.desc()).limit(30))]
    @app.get('/fills')
    def fills():
        with ledger.Session() as s:
            return [{'id':r.exchange_fill_id,'symbol':r.symbol,'side':r.side,'quantity':r.quantity,
                'price':r.price,'fee':r.fee,'realized_pnl':r.realized_pnl}
                for r in s.scalars(select(FillRow).order_by(FillRow.timestamp.desc()).limit(30))]
    @app.get('/strategies')
    def strategies():
        with ledger.Session() as s:
            return [{'id':r.id,'name':r.strategy_name,'version':r.strategy_version,'config_hash':r.config_hash,
                'mode':r.mode,'status':r.status} for r in s.scalars(select(StrategyRun).order_by(StrategyRun.start_time.desc()).limit(30))]
    @app.get('/risk')
    def risk():
        with ledger.Session() as s:
            r=s.get(RiskStateRow,account)
            return {'status':'UNKNOWN'} if r is None else {'killed':r.killed,'kill_reason':redact(r.kill_reason),
                'day_start':r.day_start,'week_start':r.week_start,'peak':r.peak,
                'drawdown':r.current_drawdown,'daily_loss':r.daily_loss_state,'weekly_loss':r.weekly_loss_state}
    @app.get('/events')
    def events():
        with ledger.Session() as s:
            return [{'timestamp':r.timestamp,'level':r.level,'component':r.component,'event':r.event,
                'message':redact(r.message),'context':redact(r.context)}
                for r in s.scalars(select(SystemEventRow).order_by(SystemEventRow.id.desc()).limit(30))]
    @app.get('/',response_class=HTMLResponse)
    def dashboard():
        info=status();p=portfolio();riskinfo=risk();o=orders();f=fills();e=events()
        rows={'System Status':info.get('strategy_status'),'Exchange Connection':health()['market_feed'],
            'Current Strategy':info.get('strategy_name'),'Portfolio Equity':p.get('equity'),
            'Cash':p.get('cash'), 'Positions':positions(),"Today's PnL":p.get('today_pnl'),
            'Total PnL':info.get('total_pnl'),'Maximum Drawdown':info.get('max_drawdown'),
            'Risk State':riskinfo,'Kill Switch':info.get('kill_switch'),
            'Recent Orders':o,'Recent Fills':f,'Recent Errors':[x for x in e if x['level'] in ('ERROR','CRITICAL')]}
        return '<!doctype html><meta charset="utf-8"><title>Paper Monitor</title><style>body{font:16px system-ui;margin:2rem;max-width:1000px}td{padding:.6rem;border-bottom:1px solid #ddd;vertical-align:top}td:first-child{font-weight:bold;width:220px}pre{white-space:pre-wrap;word-break:break-word}</style><h1>Paper Trading</h1><table>'+''.join('<tr><td>'+escape(k)+'</td><td><pre>'+escape(str(redact(v)))+'</pre></td></tr>' for k,v in rows.items())+'</table>'
    return app
