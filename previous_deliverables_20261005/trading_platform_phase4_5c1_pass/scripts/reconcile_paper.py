"""Manual paper-only reconciliation after a latched mismatch. No exchange calls."""
import argparse
import json
from sqlalchemy import select
from trading_bot.config.settings import Settings
from trading_bot.persistence.ledger import PaperLedger,ReconciliationRequired
from trading_bot.persistence.runtime import ReconciliationEngine,SimulationStateProvider,PaperOutboxStatusProvider
from trading_bot.persistence.models import StrategyRun
from trading_bot.paper_trading.engine import PaperTradingEngine
from trading_bot.strategies import create_strategy

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/paper_upbit.toml')
    p.add_argument('--resolve',action='store_true',help='acknowledge reviewed DB/broker comparison; paper only')
    a=p.parse_args();settings=Settings.load(a.config)
    l=PaperLedger(settings.persistence.database_url,settings.persistence.account)
    with l.Session() as db:
        run=db.scalar(select(StrategyRun).where(StrategyRun.mode=='PAPER').order_by(StrategyRun.start_time.desc()))
        if run is None:raise SystemExit('no paper run')
        print(json.dumps({'run_id':run.id,'status':run.status,'config_hash':run.config_hash,
             'account':l.status()},default=str,indent=2))
        run_id=run.id
    if not a.resolve:return
    if l.unresolved_intents():raise ReconciliationRequired('unresolved order intent; inspect status first')
    strategy=create_strategy(settings.strategy.name,settings.strategy.params)
    if run.strategy_version!=f"{type(strategy).__module__}:{type(strategy).__qualname__}":
        raise ReconciliationRequired("strategy implementation differs from persisted run")
    engine=PaperTradingEngine(settings,strategy)
    l.restore(engine,run_id)
    ReconciliationEngine(l,SimulationStateProvider(engine)).check()
    with l.Session.begin() as db:
        row=db.get(StrategyRun,run_id)
        if row.status!='RECONCILIATION_REQUIRED':raise ReconciliationRequired('run is not latched')
        row.status='PAUSED'
    l.event('RECONNECT','reviewed paper DB state and reconciled simulation snapshot',run_id=run_id)
    print('Paper DB/broker snapshot matches; latch cleared. Restart paper to backfill before decisions.')
    l.close()

if __name__=='__main__':main()
