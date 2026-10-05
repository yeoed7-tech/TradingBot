from pathlib import Path
import tomllib
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class MarketRules(StrictModel):
    min_quantity: float = Field(default=0, ge=0)
    price_tiers: list[tuple[float,float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_tiers(self):
        if any(a<0 or b<=0 for a,b in self.price_tiers) or len({a for a,b in self.price_tiers})!=len(self.price_tiers):
            raise ValueError("invalid price tiers")
        return self

    def tick_for(self,price):
        return next((tick for lower,tick in sorted(self.price_tiers,reverse=True) if price>=lower),self.price_tick)

    min_notional: float = Field(default=10, ge=0)
    price_tick: float = Field(default=0.01, gt=0)
    quantity_step: float = Field(default=0.000001, gt=0)

class ExecutionConfig(StrictModel):
    fee_rate: float = Field(default=0.001, ge=0, lt=0.1)
    slippage_bps: float = Field(default=5, ge=0, lt=10000)
    delay_bars: int = Field(default=1, ge=1)
    max_volume_participation: float = Field(default=0.01, gt=0, le=1)
    expiry_bars: int = Field(default=4, ge=1)

class RiskConfig(StrictModel):
    max_gross_weight: float = Field(default=0.8, gt=0, le=1)
    max_symbol_weight: float = Field(default=0.5, gt=0, le=1)
    daily_loss: float = Field(default=0.03, gt=0, le=1)
    weekly_loss: float = Field(default=0.08, gt=0, le=1)
    max_drawdown: float = Field(default=0.2, gt=0, le=1)
    max_consecutive_losses: int = Field(default=5, ge=1)
    max_price_jump: float = Field(default=0.5, gt=0)
    max_slippage_bps: float = Field(default=50, ge=0)
    sizing: Literal['fixed_fractional','atr'] = 'fixed_fractional'
    fixed_fraction: float = Field(default=0.02, gt=0, le=1)
    risk_per_trade: float = Field(default=0.01, gt=0, le=1)
    atr_multiple: float = Field(default=2, gt=0)
    atr_period: int = Field(default=14, ge=2)
    rebalance_tolerance: float = Field(default=0.005, ge=0, lt=1)

class StrategyConfig(StrictModel):
    name: str = 'ema_cross'
    params: dict = Field(default_factory=dict)

class ReconnectConfig(StrictModel):
    max_attempts: int = Field(default=3,ge=1,le=10)
    base_backoff: float = Field(default=0.5,gt=0)
    max_backoff: float = Field(default=8,gt=0)
    max_consecutive_failures: int = Field(default=5,ge=1)

class PaperConfig(StrictModel):
    exchange: Literal['upbit'] = 'upbit'
    symbol: str = 'BTC/KRW'
    timeframe: Literal['1m','3m','5m','10m','15m','30m','1h','4h','1d'] = '1m'
    starting_cash: float = Field(default=1000000,gt=0)
    fee_rate: float = Field(default=0.0005,ge=0,lt=0.1)
    slippage_bps: float = Field(default=5,ge=0,lt=10000)
    poll_interval: float = Field(default=3,ge=0.1)
    quote_source: Literal["rest","websocket"] = "websocket"
    network_trust_env: bool = True
    ca_bundle_path: str | None = None
    request_timeout: float = Field(default=15,gt=0,le=60)
    stale_data_timeout: float = Field(default=90,gt=0)
    quote_max_age: float = Field(default=10,gt=0)
    clock_skew_tolerance: float = Field(default=2,ge=0)
    warmup_bars: int = Field(default=120,ge=2,le=10000)
    page_size: int = Field(default=200,ge=1,le=200)
    max_pages: int = Field(default=100,ge=1)
    max_gap_bars: int = Field(default=1440,ge=1)
    max_book_participation: float = Field(default=0.1,gt=0,le=1)
    # Current public KRW policy snapshot; update deliberately, not from private endpoints.
    rules_source: str = 'Upbit KRW public policy checked 2026-09-28'
    market_rules: MarketRules = Field(default_factory=lambda: MarketRules(
        min_notional=5000,quantity_step=0.00000001,price_tick=0.00000001,
        price_tiers=[(1000000,1000),(500000,500),(100000,100),(50000,50),
          (10000,10),(5000,5),(100,1),(10,.1),(1,.01),(.1,.001),
          (.01,.0001),(.001,.00001),(.0001,.000001),(.00001,.0000001),(0,.00000001)]))
    reconnect: ReconnectConfig = Field(default_factory=ReconnectConfig)

class PersistenceConfig(StrictModel):
    enabled: bool = False
    database_url: str = "sqlite:///data/database/paper.sqlite3"
    account: str = "paper"
    lease_ttl: float = Field(default=30,gt=1)
    single_writer: bool = True
    recent_cache_limit: int = Field(default=1000,ge=100,le=100000)

class Settings(StrictModel):
    initial_cash: float = Field(default=100000, gt=0)
    bar_seconds: int = Field(default=86400, ge=1)
    live_trading: Literal[False] = False
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    paper_trading: PaperConfig = Field(default_factory=PaperConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    rules: MarketRules = Field(default_factory=MarketRules)
    symbol_rules: dict[str, MarketRules] = Field(default_factory=dict)

    def rules_for(self, symbol):
        return self.symbol_rules.get(symbol, self.rules)

    @model_validator(mode='after')
    def validate_execution(self):
        if self.execution.slippage_bps > self.risk.max_slippage_bps:
            raise ValueError('configured slippage exceeds kill-switch threshold')
        return self

    @classmethod
    def load(cls, path):
        with Path(path).open('rb') as f:
            return cls.model_validate(tomllib.load(f))
