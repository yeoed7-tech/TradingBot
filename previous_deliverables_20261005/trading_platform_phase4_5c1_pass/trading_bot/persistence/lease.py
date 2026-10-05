"""Single active paper writer: database conditional takeover and transactional fencing."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from trading_bot.persistence.models import TraderLease, HeartbeatRow

def stamp(t):return t.isoformat(timespec='microseconds')
def utcnow():return datetime.now(timezone.utc)

class LeaseLost(RuntimeError): pass

class WriterLease:
    def __init__(self,ledger,strategy,ttl=30,clock=utcnow):
        self.ledger=ledger;self.strategy=strategy;self.ttl=ttl;self.clock=clock
        self.owner_id=str(uuid4());self.token=None;self._last_clock=None

    def _now(self):
        now=self.clock()
        if self._last_clock is not None and now<self._last_clock:
            raise LeaseLost('wall clock moved backwards; writer halted')
        self._last_clock=now
        return now

    def acquire(self):
        now=self._now(); expiry=stamp(now+timedelta(seconds=self.ttl));current=stamp(now)
        with self.ledger.Session.begin() as s:
            existing=s.get(TraderLease,self.ledger.account)
            if existing is None:
                try:
                    with s.begin_nested():
                        s.add(TraderLease(account=self.ledger.account,strategy=self.strategy,
                            owner_id=self.owner_id,fencing_token=1,expires_at=expiry,heartbeat_at=current))
                        s.flush()
                    self.token=1;return self.token
                except IntegrityError:
                    raise LeaseLost('concurrent lease acquisition; retry only after expiry') from None
            if existing.expires_at>current and existing.owner_id:
                raise LeaseLost('another paper trader owns this account')
            prior=existing.fencing_token
            result=s.execute(update(TraderLease).where(TraderLease.account==self.ledger.account,
                TraderLease.fencing_token==prior,TraderLease.expires_at<=current)
                .values(strategy=self.strategy,owner_id=self.owner_id,
                    fencing_token=prior+1,expires_at=expiry,heartbeat_at=current))
            if result.rowcount!=1:raise LeaseLost('lease takeover race')
            self.token=prior+1
        return self.token

    def assert_owned(self,session):
        if self.token is None:raise LeaseLost('writer lease not acquired')
        # This conditional UPDATE is the first write in the accounting transaction.
        # SQLite obtains a writer lock; PostgreSQL locks the row. A stale owner
        # cannot pass after a newer token commits, even if it read earlier.
        now=stamp(self._now())
        result=session.execute(update(TraderLease).where(
            TraderLease.account==self.ledger.account,
            TraderLease.owner_id==self.owner_id,
            TraderLease.fencing_token==self.token,
            TraderLease.expires_at>now).values(heartbeat_at=now))
        if result.rowcount!=1:raise LeaseLost('stale or expired writer fencing token')

    def renew(self):
        now=self._now();current=stamp(now)
        with self.ledger.Session.begin() as s:
            result=s.execute(update(TraderLease).where(TraderLease.account==self.ledger.account,
                TraderLease.owner_id==self.owner_id,TraderLease.fencing_token==self.token,
                TraderLease.expires_at>current)
                .values(heartbeat_at=current,expires_at=stamp(now+timedelta(seconds=self.ttl))))
            if result.rowcount!=1:raise LeaseLost('cannot renew lost lease')
            for component in ('process','database'):
                row=s.get(HeartbeatRow,(self.ledger.account,component))
                if row is None:s.add(HeartbeatRow(account=self.ledger.account,component=component,
                                                  owner_id=self.owner_id,timestamp=current))
                else:row.timestamp=current;row.owner_id=self.owner_id

    def heartbeat(self,component):
        with self.ledger.Session.begin() as s:
            self.assert_owned(s)
            row=s.get(HeartbeatRow,(self.ledger.account,component))
            if row is None:s.add(HeartbeatRow(account=self.ledger.account,component=component,
                                              timestamp=stamp(self._now()),owner_id=self.owner_id))
            else:row.timestamp=stamp(self._now());row.owner_id=self.owner_id

    def release(self):
        if self.token is None:return
        with self.ledger.Session.begin() as s:
            s.execute(update(TraderLease).where(TraderLease.account==self.ledger.account,
                TraderLease.owner_id==self.owner_id,TraderLease.fencing_token==self.token)
                .values(owner_id='',expires_at=stamp(self._now())))
        self.token=None
