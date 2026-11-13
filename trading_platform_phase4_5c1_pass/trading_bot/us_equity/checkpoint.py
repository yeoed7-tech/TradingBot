"""Fenced, append-only session checkpoints for isolated US-equity simulation.

A session is atomic: only committed sessions restore. Never open an Upbit ledger
as this store. No remote pending order is recoverable by this simulation store.
"""
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select
from sqlalchemy.orm import sessionmaker

from trading_bot.persistence.lease import WriterLease
from trading_bot.persistence.ledger import db_engine
from trading_bot.persistence.models import HeartbeatRow, TraderLease
from trading_bot.strategies.laoer_tqqq import VERSION
from .history import Session
from .simulation import ResearchAccount

metadata=MetaData()
manifest=Table("tqqq_sim_manifest",metadata,Column("account",String,primary_key=True),
               Column("config_hash",String,nullable=False),Column("initial_cash",String,nullable=False))
events=Table("tqqq_sim_sessions",metadata,Column("account",String,primary_key=True),
             Column("sequence",Integer,primary_key=True),Column("day",String,nullable=False),
             Column("bar",Text,nullable=False),Column("capacity",String),Column("state",Text,nullable=False))


def serialize(obj):
    return json.dumps(obj,default=str,sort_keys=True,separators=(",",":"),allow_nan=False)


def decode_bar(raw):
    x=json.loads(raw)
    x["day"]=date.fromisoformat(x["day"])
    for k in ("opens","closes"):
        x[k]=datetime.fromisoformat(x[k])
    for k in ("open","high","low","close","split","dividend"):
        x[k]=Decimal(x[k])
    return Session(**x)


class CheckpointStore:
    account="tqqq-usd-simulation"

    def __init__(self,url,initial_cash,config,*,ttl=30):
        self.engine=db_engine(url)
        self.Session=sessionmaker(self.engine)
        self.run=None
        try:
            # A dedicated store is required; do not use an existing Upbit DB.
            from sqlalchemy import inspect
            allowed={"tqqq_sim_manifest","tqqq_sim_sessions","trader_leases","heartbeats"}
            if set(inspect(self.engine).get_table_names())-allowed:
                raise ValueError("not a dedicated TQQQ simulation database")
            metadata.create_all(self.engine)
            TraderLease.__table__.create(self.engine,checkfirst=True)
            HeartbeatRow.__table__.create(self.engine,checkfirst=True)
            self.lease=WriterLease(self,VERSION,ttl=ttl)
            self.lease.acquire()
            try:
                self.run=self._restore(initial_cash,config)
                self.lease.renew()
            except Exception:
                self.lease.release()
                raise
        except Exception:
            self.engine.dispose()
            raise

    def _restore(self,initial_cash,config):
        state=ResearchAccount(initial_cash,config)
        with self.Session.begin() as s:
            self.lease.assert_owned(s)
            row=s.execute(select(manifest).where(manifest.c.account==self.account)).one_or_none()
            if row is None:
                s.execute(insert(manifest).values(account=self.account,config_hash=config.digest,
                                                  initial_cash=str(state.portfolio.initial_cash)))
            elif row.config_hash!=config.digest or Decimal(row.initial_cash)!=state.portfolio.initial_cash:
                raise ValueError("checkpoint configuration mismatch")
            stored=s.execute(select(events).where(events.c.account==self.account).order_by(events.c.sequence)).all()
        for row in stored:
            bar=decode_bar(row.bar)
            if row.sequence!=state.index or row.day!=str(bar.day):
                raise ValueError("checkpoint sequence mismatch")
            state.step(bar,Decimal(row.capacity) if row.capacity is not None else None)
            if serialize(state.snapshot())!=row.state:
                raise ValueError("checkpoint reconciliation mismatch")
        return state

    def step(self,bar,capacity=None):
        if self.run.failed:
            raise ValueError("checkpoint failed; reopen and reconcile")
        try:
            self.lease.renew()
            seq=self.run.index
            row=self.run.step(bar,capacity)
            with self.Session.begin() as s:
                self.lease.assert_owned(s)
                s.execute(insert(events).values(account=self.account,sequence=seq,day=str(bar.day),
                    bar=serialize(asdict(bar)),capacity=None if capacity is None else str(capacity),
                    state=serialize(self.run.snapshot())))
            return row
        except Exception:
            self.run.failed=True
            self.run.risk.kill("checkpoint_failed")
            raise

    def close(self):
        try:
            self.lease.release()
        finally:
            self.engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self,*_):
        self.close()
