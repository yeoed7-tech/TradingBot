"""Exact Decimal storage and bounded-runtime counters.

Revision ID: 0003_exact_accounting
Revises: 0002_decimal_accounting
"""
from alembic import op
import sqlalchemy as sa
revision='0003_exact_accounting'
down_revision='0002_decimal_accounting'
branch_labels=None
depends_on=None

COLUMNS={
 'accounts':'cash initial_cash realized_pnl fees',
 'positions':'quantity cost average_entry_price realized_pnl sold_quantity',
 'orders':'quantity price filled',
 'fills':'quantity price fee slippage realized_pnl',
 'portfolio_snapshots':'cash market_value equity realized_pnl unrealized_pnl fees',
 'risk_state':'day_start week_start peak last_equity',
}
OLD=sa.Numeric(38,12,asdecimal=True)
NEW=sa.Numeric(65,24,asdecimal=True)

def upgrade():
    sqlite=op.get_bind().dialect.name=='sqlite'
    for table,fields in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for field in fields.split():
                old=sa.Float() if table=='risk_state' else OLD
                target=sa.String(100) if sqlite else NEW
                batch.alter_column(field,existing_type=old,type_=target,
                    existing_nullable=(table=='orders' and field=='price'),
                    **({} if sqlite else {'postgresql_using':f'{field}::numeric(65,24)'}))
    with op.batch_alter_table('accounts') as batch:
        batch.add_column(sa.Column('fill_count',sa.Integer(),nullable=False,server_default='0'))
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('fills_seen',sa.Integer(),nullable=False,server_default='0'))
    # Backfill counters for existing paper files without materializing all fills in Python.
    op.execute(sa.text("UPDATE accounts SET fill_count=(SELECT count(*) FROM fills)"))
    op.execute(sa.text("UPDATE orders SET fills_seen=(SELECT count(*) FROM fills WHERE fills.internal_order_id=orders.internal_order_id)"))

def downgrade():
    with op.batch_alter_table('orders') as batch:batch.drop_column('fills_seen')
    with op.batch_alter_table('accounts') as batch:batch.drop_column('fill_count')
    sqlite=op.get_bind().dialect.name=='sqlite'
    for table,fields in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for field in fields.split():
                target=sa.Float() if table=='risk_state' else OLD
                batch.alter_column(field,existing_type=sa.String(100) if sqlite else NEW,
                    type_=target,existing_nullable=(table=='orders' and field=='price'),
                    **({} if sqlite else {'postgresql_using':f'{field}::numeric(38,12)'}))
