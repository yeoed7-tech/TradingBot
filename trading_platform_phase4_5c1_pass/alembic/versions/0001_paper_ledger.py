"""Static initial paper ledger schema.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():

    op.create_table('accounts',
    sa.Column('account', sa.String(length=100), nullable=False),
    sa.Column('cash', sa.Float(), nullable=False),
    sa.Column('initial_cash', sa.Float(), nullable=False),
    sa.Column('realized_pnl', sa.Float(), nullable=False),
    sa.Column('fees', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('account')
    )
    op.create_table('market_cursors',
    sa.Column('exchange', sa.String(length=40), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('timeframe', sa.String(length=20), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('last_quote_timestamp', sa.String(length=40), nullable=True),
    sa.Column('engine_index', sa.Integer(), nullable=False),
    sa.Column('strategy_state', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('exchange', 'symbol', 'timeframe')
    )
    op.create_table('ohlcv',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exchange', sa.String(length=40), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('timeframe', sa.String(length=20), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('open', sa.Float(), nullable=False),
    sa.Column('high', sa.Float(), nullable=False),
    sa.Column('low', sa.Float(), nullable=False),
    sa.Column('close', sa.Float(), nullable=False),
    sa.Column('volume', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('exchange', 'symbol', 'timeframe', 'timestamp')
    )
    op.create_table('positions',
    sa.Column('account', sa.String(length=100), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=False),
    sa.Column('average_entry_price', sa.Float(), nullable=False),
    sa.Column('realized_pnl', sa.Float(), nullable=False),
    sa.Column('opened_at', sa.String(length=40), nullable=True),
    sa.Column('sold_quantity', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('account', 'symbol')
    )
    op.create_table('risk_state',
    sa.Column('account', sa.String(length=100), nullable=False),
    sa.Column('killed', sa.Boolean(), nullable=False),
    sa.Column('kill_reason', sa.Text(), nullable=False),
    sa.Column('day', sa.String(length=20), nullable=True),
    sa.Column('week', sa.String(length=20), nullable=True),
    sa.Column('day_start', sa.Float(), nullable=False),
    sa.Column('week_start', sa.Float(), nullable=False),
    sa.Column('peak', sa.Float(), nullable=False),
    sa.Column('last_equity', sa.Float(), nullable=False),
    sa.Column('current_drawdown', sa.Float(), nullable=False),
    sa.Column('daily_loss_state', sa.Float(), nullable=False),
    sa.Column('weekly_loss_state', sa.Float(), nullable=False),
    sa.Column('consecutive_losses', sa.Integer(), nullable=False),
    sa.Column('trades_seen', sa.Integer(), nullable=False),
    sa.Column('state_json', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('account')
    )
    op.create_table('strategy_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('strategy_name', sa.String(length=200), nullable=False),
    sa.Column('strategy_version', sa.String(length=80), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('config_hash', sa.String(length=64), nullable=False),
    sa.Column('start_time', sa.String(length=40), nullable=False),
    sa.Column('end_time', sa.String(length=40), nullable=True),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_strategy_runs_config_hash'), 'strategy_runs', ['config_hash'], unique=False)
    op.create_table('orders',
    sa.Column('internal_order_id', sa.String(length=36), nullable=False),
    sa.Column('client_order_id', sa.String(length=100), nullable=False),
    sa.Column('exchange_order_id', sa.String(length=100), nullable=True),
    sa.Column('strategy_run_id', sa.String(length=36), nullable=False),
    sa.Column('strategy', sa.String(length=200), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('order_type', sa.String(length=20), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('price', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('filled', sa.Float(), nullable=False),
    sa.Column('eligible_bar', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('updated_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['strategy_runs.id'], ),
    sa.PrimaryKeyConstraint('internal_order_id'),
    sa.UniqueConstraint('client_order_id')
    )
    op.create_index('ix_orders_run_status', 'orders', ['strategy_run_id', 'status'], unique=False)
    op.create_table('portfolio_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account', sa.String(length=100), nullable=False),
    sa.Column('strategy_run_id', sa.String(length=36), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('cash', sa.Float(), nullable=False),
    sa.Column('market_value', sa.Float(), nullable=False),
    sa.Column('equity', sa.Float(), nullable=False),
    sa.Column('realized_pnl', sa.Float(), nullable=False),
    sa.Column('unrealized_pnl', sa.Float(), nullable=False),
    sa.Column('fees', sa.Float(), nullable=False),
    sa.Column('drawdown', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['strategy_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('signals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('strategy', sa.String(length=200), nullable=False),
    sa.Column('strategy_run_id', sa.String(length=36), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('signal', sa.String(length=8), nullable=False),
    sa.Column('target_position', sa.Float(), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['strategy_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('system_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('component', sa.String(length=80), nullable=False),
    sa.Column('event', sa.String(length=80), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('context', sa.JSON(), nullable=False),
    sa.Column('strategy_run_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['strategy_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('fills',
    sa.Column('exchange_fill_id', sa.String(length=120), nullable=False),
    sa.Column('internal_order_id', sa.String(length=36), nullable=False),
    sa.Column('strategy_run_id', sa.String(length=36), nullable=False),
    sa.Column('timestamp', sa.String(length=40), nullable=False),
    sa.Column('symbol', sa.String(length=60), nullable=False),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('fee', sa.Float(), nullable=False),
    sa.Column('slippage', sa.Float(), nullable=False),
    sa.Column('realized_pnl', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['internal_order_id'], ['orders.internal_order_id'], ),
    sa.ForeignKeyConstraint(['strategy_run_id'], ['strategy_runs.id'], ),
    sa.PrimaryKeyConstraint('exchange_fill_id')
    )
    op.create_index('ix_fills_run_timestamp', 'fills', ['strategy_run_id', 'timestamp'], unique=False)


def downgrade():

    op.drop_index('ix_fills_run_timestamp', table_name='fills')
    op.drop_table('fills')
    op.drop_table('system_events')
    op.drop_table('signals')
    op.drop_table('portfolio_snapshots')
    op.drop_index('ix_orders_run_status', table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_strategy_runs_config_hash'), table_name='strategy_runs')
    op.drop_table('strategy_runs')
    op.drop_table('risk_state')
    op.drop_table('positions')
    op.drop_table('ohlcv')
    op.drop_table('market_cursors')
    op.drop_table('accounts')

