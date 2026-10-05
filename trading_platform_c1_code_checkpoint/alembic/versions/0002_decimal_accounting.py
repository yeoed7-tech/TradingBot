"""Decimal accounting columns and single-writer lease.

Revision ID: 0002_decimal_accounting
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
revision='0002_decimal_accounting'
down_revision='0001'
branch_labels=None
depends_on=None

COLUMNS={
 'accounts':'cash initial_cash realized_pnl fees',
 'positions':'quantity cost average_entry_price realized_pnl sold_quantity',
 'orders':'quantity price filled',
 'fills':'quantity price fee slippage realized_pnl',
 'portfolio_snapshots':'cash market_value equity realized_pnl unrealized_pnl fees',
}
NUM=sa.Numeric(38, 12, asdecimal=True)

def change(source,target):
    for table,columns in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns.split():
                batch.alter_column(column,existing_type=source,type_=target,
                    existing_nullable=table=='orders' and column=='price',
                    postgresql_using=f'{column}::numeric(38,12)' if isinstance(target,sa.Numeric) else None)

def upgrade():
    change(sa.Float(),NUM)
    op.create_table('trader_leases',
        sa.Column('account',sa.String(100),primary_key=True),
        sa.Column('strategy',sa.String(200),nullable=False),
        sa.Column('owner_id',sa.String(36),nullable=False),
        sa.Column('fencing_token',sa.Integer(),nullable=False),
        sa.Column('expires_at',sa.String(40),nullable=False),
        sa.Column('heartbeat_at',sa.String(40),nullable=False))
    op.create_table('heartbeats',
        sa.Column('account',sa.String(100),primary_key=True),
        sa.Column('component',sa.String(40),primary_key=True),
        sa.Column('timestamp',sa.String(40),nullable=False),
        sa.Column('owner_id',sa.String(36),nullable=False))

def downgrade():
    op.drop_table('heartbeats');op.drop_table('trader_leases')
    change(NUM,sa.Float())
