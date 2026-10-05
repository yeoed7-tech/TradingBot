"""Opt-in public-market end-to-end probe. No keys or live order capability.

Run: python -m scripts.public_integration --duration 150 --out reports/public_integration
The diagnostic target is a plumbing test, not an investment strategy.
"""
import argparse
import asyncio
import json
from trading_bot.config.settings import Settings
from trading_bot.strategies.base_strategy import Strategy
from trading_bot.core.events.models import Signal
from trading_bot.paper_trading.runner import run_public_paper

class DiagnosticCycle(Strategy):
    def __init__(self,warmup): self.count=0;self.warmup=warmup
    def on_data(self,bars):
        self.count+=1
        target=None if self.count<self.warmup else (.1 if self.count==self.warmup else 0.)
        return [Signal(s,target,'public_integration_probe','diagnostic only') for s in bars]

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/paper_upbit.toml');p.add_argument('--duration',type=float,default=150);p.add_argument('--out',default='reports/public_integration')
    a=p.parse_args()
    settings=Settings.load(a.config)
    result=asyncio.run(run_public_paper(settings,DiagnosticCycle(settings.paper_trading.warmup_bars),a.out,a.duration))
    print(json.dumps(result,default=str,indent=2))
    if not result['integration_success']: raise SystemExit(1)

if __name__=='__main__': main()
