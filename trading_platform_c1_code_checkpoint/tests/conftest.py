from datetime import datetime,timezone,timedelta
import pandas as pd
import pytest
from trading_bot.config.settings import Settings
from trading_bot.core.events.models import Bar,Signal
from trading_bot.strategies.base_strategy import Strategy

T=datetime(2024,1,1,tzinfo=timezone.utc)

@pytest.fixture
def settings():
    return Settings.model_validate({'initial_cash':1000,'execution':{'fee_rate':0,'slippage_bps':0,'max_volume_participation':1},
       'risk':{'max_gross_weight':1,'max_symbol_weight':1,'fixed_fraction':1,'daily_loss':1,'weekly_loss':1,
               'max_drawdown':1,'max_price_jump':100,'max_consecutive_losses':100,'rebalance_tolerance':0},
       'rules':{'min_notional':0,'price_tick':.01,'quantity_step':.001}})

def bars_frame(prices,volume=1000):
    return pd.DataFrame([{'timestamp':T+timedelta(days=i),'symbol':'BTC/USDT','open':p,'high':p,'low':p,'close':p,'volume':volume} for i,p in enumerate(prices)])

class Schedule(Strategy):
    def __init__(self,targets): self.targets=iter(targets)
    def on_data(self,bars):
        target=next(self.targets,None)
        return [Signal(s,target,'test') for s in bars]
