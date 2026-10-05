"""Synthetic strategy dispatch throughput only; does not claim multi-asset trading."""
import json
import time
from datetime import datetime,timezone,timedelta
from trading_bot.core.events.models import Bar
from trading_bot.strategies.ema_cross import EMACross

def run(iterations=1000):
    results=[];now=datetime.now(timezone.utc)
    for n in (1,10,50):
        strategy=EMACross()
        start=time.perf_counter()
        for i in range(iterations):
            bars={f'ASSET{j}/KRW':Bar(now+timedelta(minutes=i),f'ASSET{j}/KRW',100,101,99,100+i/100,1)
                  for j in range(n)}
            strategy.on_data(bars)
        elapsed=time.perf_counter()-start
        results.append({'symbols':n,'events':n*iterations,'seconds':elapsed,
                        'events_per_second':n*iterations/elapsed})
    return results
if __name__=='__main__':print(json.dumps(run(),indent=2))
