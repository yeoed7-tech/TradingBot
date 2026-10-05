"""Conservative retention: never touch orders, fills, accounts, risk or cursors."""
from datetime import datetime,timezone,timedelta
from sqlalchemy import delete,select,func
from trading_bot.persistence.models import SystemEventRow,SnapshotRow

def prune(ledger,*,events_days=30,snapshots_days=90,now=None):
    now=now or datetime.now(timezone.utc)
    events_cutoff=(now-timedelta(days=events_days)).isoformat()
    snapshot_cutoff=(now-timedelta(days=snapshots_days)).isoformat()
    with ledger.Session.begin() as s:
        # Retain all warnings/errors and latest snapshot; only low-severity noise expires.
        last=s.scalar(select(func.max(SnapshotRow.id)).where(SnapshotRow.account==ledger.account))
        events=s.execute(delete(SystemEventRow).where(SystemEventRow.timestamp<events_cutoff,
                         SystemEventRow.level=='INFO')).rowcount
        snapshots=s.execute(delete(SnapshotRow).where(SnapshotRow.account==ledger.account,
            SnapshotRow.timestamp<snapshot_cutoff,SnapshotRow.id!=last)).rowcount
        return {'events_pruned':events,'snapshots_pruned':snapshots,
                'ohlcv_pruned':0,'orders_pruned':0,'fills_pruned':0}
