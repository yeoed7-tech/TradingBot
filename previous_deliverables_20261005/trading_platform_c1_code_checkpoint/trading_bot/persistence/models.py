"""Portable SQLAlchemy 2.x schema. UTC datetimes are stored as ISO UTC strings."""
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, UniqueConstraint, Index, JSON, Text, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from decimal import Decimal
from trading_bot.persistence.decimal_type import ExactDecimal

class Base(DeclarativeBase): pass

class StrategyRun(Base):
    __tablename__='strategy_runs'
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    strategy_name: Mapped[str]=mapped_column(String(200))
    strategy_version: Mapped[str]=mapped_column(String(80))
    config: Mapped[dict]=mapped_column(JSON)
    config_hash: Mapped[str]=mapped_column(String(64),index=True)
    start_time: Mapped[str]=mapped_column(String(40))
    end_time: Mapped[str|None]=mapped_column(String(40))
    mode: Mapped[str]=mapped_column(String(20))
    status: Mapped[str]=mapped_column(String(40))

class CandleRow(Base):
    __tablename__='ohlcv'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    exchange: Mapped[str]=mapped_column(String(40))
    symbol: Mapped[str]=mapped_column(String(60))
    timeframe: Mapped[str]=mapped_column(String(20))
    timestamp: Mapped[str]=mapped_column(String(40))
    open: Mapped[float]=mapped_column(Float)
    high: Mapped[float]=mapped_column(Float)
    low: Mapped[float]=mapped_column(Float)
    close: Mapped[float]=mapped_column(Float)
    volume: Mapped[float]=mapped_column(Float)
    __table_args__=(UniqueConstraint('exchange','symbol','timeframe','timestamp'),)

class SignalRow(Base):
    __tablename__='signals'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    timestamp: Mapped[str]=mapped_column(String(40))
    strategy: Mapped[str]=mapped_column(String(200))
    strategy_run_id: Mapped[str]=mapped_column(ForeignKey('strategy_runs.id'))
    symbol: Mapped[str]=mapped_column(String(60))
    signal: Mapped[str]=mapped_column(String(8))
    target_position: Mapped[float|None]=mapped_column(Float)
    metadata_json: Mapped[dict]=mapped_column('metadata',JSON)
    mode: Mapped[str]=mapped_column(String(20))

class OrderRow(Base):
    __tablename__='orders'
    internal_order_id: Mapped[str]=mapped_column(String(36),primary_key=True)
    client_order_id: Mapped[str]=mapped_column(String(100),unique=True,nullable=False)
    exchange_order_id: Mapped[str|None]=mapped_column(String(100))
    strategy_run_id: Mapped[str]=mapped_column(ForeignKey('strategy_runs.id'))
    strategy: Mapped[str]=mapped_column(String(200))
    symbol: Mapped[str]=mapped_column(String(60))
    side: Mapped[str]=mapped_column(String(8))
    order_type: Mapped[str]=mapped_column(String(20))
    quantity: Mapped[Decimal]=mapped_column(ExactDecimal())
    price: Mapped[Decimal|None]=mapped_column(ExactDecimal())
    status: Mapped[str]=mapped_column(String(30))
    filled: Mapped[Decimal]=mapped_column(ExactDecimal(),default=Decimal(0))
    fills_seen: Mapped[int]=mapped_column(Integer,default=0)
    eligible_bar: Mapped[int]=mapped_column(Integer)
    reason: Mapped[str]=mapped_column(String(200),default='')
    created_at: Mapped[str]=mapped_column(String(40))
    updated_at: Mapped[str]=mapped_column(String(40))

class FillRow(Base):
    __tablename__='fills'
    exchange_fill_id: Mapped[str]=mapped_column(String(120),primary_key=True)
    internal_order_id: Mapped[str]=mapped_column(ForeignKey('orders.internal_order_id'))
    strategy_run_id: Mapped[str]=mapped_column(ForeignKey('strategy_runs.id'))
    timestamp: Mapped[str]=mapped_column(String(40))
    symbol: Mapped[str]=mapped_column(String(60))
    side: Mapped[str]=mapped_column(String(8))
    quantity: Mapped[Decimal]=mapped_column(ExactDecimal())
    price: Mapped[Decimal]=mapped_column(ExactDecimal())
    fee: Mapped[Decimal]=mapped_column(ExactDecimal())
    slippage: Mapped[Decimal]=mapped_column(ExactDecimal())
    realized_pnl: Mapped[Decimal]=mapped_column(ExactDecimal())

class PositionRow(Base):
    __tablename__='positions'
    account: Mapped[str]=mapped_column(String(100),primary_key=True)
    symbol: Mapped[str]=mapped_column(String(60),primary_key=True)
    quantity: Mapped[Decimal]=mapped_column(ExactDecimal())
    cost: Mapped[Decimal]=mapped_column(ExactDecimal())
    average_entry_price: Mapped[Decimal]=mapped_column(ExactDecimal())
    realized_pnl: Mapped[Decimal]=mapped_column(ExactDecimal())
    opened_at: Mapped[str|None]=mapped_column(String(40))
    sold_quantity: Mapped[Decimal]=mapped_column(ExactDecimal())
    updated_at: Mapped[str]=mapped_column(String(40))

class AccountRow(Base):
    __tablename__='accounts'
    account: Mapped[str]=mapped_column(String(100),primary_key=True)
    cash: Mapped[Decimal]=mapped_column(ExactDecimal())
    initial_cash: Mapped[Decimal]=mapped_column(ExactDecimal())
    realized_pnl: Mapped[Decimal]=mapped_column(ExactDecimal(),default=0)
    fees: Mapped[Decimal]=mapped_column(ExactDecimal(),default=Decimal(0))
    fill_count: Mapped[int]=mapped_column(Integer,default=0)

class SnapshotRow(Base):
    __tablename__='portfolio_snapshots'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    account: Mapped[str]=mapped_column(String(100))
    strategy_run_id: Mapped[str]=mapped_column(ForeignKey('strategy_runs.id'))
    timestamp: Mapped[str]=mapped_column(String(40))
    cash: Mapped[Decimal]=mapped_column(ExactDecimal())
    market_value: Mapped[Decimal]=mapped_column(ExactDecimal())
    equity: Mapped[Decimal]=mapped_column(ExactDecimal())
    realized_pnl: Mapped[Decimal]=mapped_column(ExactDecimal())
    unrealized_pnl: Mapped[Decimal]=mapped_column(ExactDecimal())
    fees: Mapped[Decimal]=mapped_column(ExactDecimal())
    drawdown: Mapped[float]=mapped_column(Float)

class RiskStateRow(Base):
    __tablename__='risk_state'
    account: Mapped[str]=mapped_column(String(100),primary_key=True)
    killed: Mapped[bool]=mapped_column(Boolean)
    kill_reason: Mapped[str]=mapped_column(Text)
    day: Mapped[str|None]=mapped_column(String(20))
    week: Mapped[str|None]=mapped_column(String(20))
    day_start: Mapped[Decimal]=mapped_column(ExactDecimal())
    week_start: Mapped[Decimal]=mapped_column(ExactDecimal())
    peak: Mapped[Decimal]=mapped_column(ExactDecimal())
    last_equity: Mapped[Decimal]=mapped_column(ExactDecimal())
    current_drawdown: Mapped[float]=mapped_column(Float)
    daily_loss_state: Mapped[float]=mapped_column(Float)
    weekly_loss_state: Mapped[float]=mapped_column(Float)
    consecutive_losses: Mapped[int]=mapped_column(Integer)
    trades_seen: Mapped[int]=mapped_column(Integer)
    state_json: Mapped[dict]=mapped_column(JSON)

class MarketCursorRow(Base):
    __tablename__='market_cursors'
    exchange: Mapped[str]=mapped_column(String(40),primary_key=True)
    symbol: Mapped[str]=mapped_column(String(60),primary_key=True)
    timeframe: Mapped[str]=mapped_column(String(20),primary_key=True)
    timestamp: Mapped[str]=mapped_column(String(40))
    last_quote_timestamp: Mapped[str|None]=mapped_column(String(40))
    engine_index: Mapped[int]=mapped_column(Integer)
    strategy_state: Mapped[dict]=mapped_column(JSON)
    state: Mapped[str]=mapped_column(String(40))

class SystemEventRow(Base):
    __tablename__='system_events'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    timestamp: Mapped[str]=mapped_column(String(40))
    level: Mapped[str]=mapped_column(String(20))
    component: Mapped[str]=mapped_column(String(80))
    event: Mapped[str]=mapped_column(String(80))
    message: Mapped[str]=mapped_column(Text)
    context: Mapped[dict]=mapped_column(JSON)
    strategy_run_id: Mapped[str|None]=mapped_column(ForeignKey('strategy_runs.id'))

class TraderLease(Base):
    __tablename__='trader_leases'
    account: Mapped[str]=mapped_column(String(100),primary_key=True)
    strategy: Mapped[str]=mapped_column(String(200),nullable=False)
    owner_id: Mapped[str]=mapped_column(String(36),nullable=False)
    fencing_token: Mapped[int]=mapped_column(Integer,nullable=False)
    expires_at: Mapped[str]=mapped_column(String(40),nullable=False)
    heartbeat_at: Mapped[str]=mapped_column(String(40),nullable=False)

class HeartbeatRow(Base):
    __tablename__='heartbeats'
    account: Mapped[str]=mapped_column(String(100),primary_key=True)
    component: Mapped[str]=mapped_column(String(40),primary_key=True)
    timestamp: Mapped[str]=mapped_column(String(40),nullable=False)
    owner_id: Mapped[str]=mapped_column(String(36),nullable=False)

Index('ix_orders_run_status',OrderRow.strategy_run_id,OrderRow.status)
Index('ix_fills_run_timestamp',FillRow.strategy_run_id,FillRow.timestamp)
