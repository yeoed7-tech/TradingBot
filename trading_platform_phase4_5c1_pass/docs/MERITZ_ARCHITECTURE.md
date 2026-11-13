# TQQQ/Meritz branch architecture

```
Historical sessions -> pure Laoer strategy -> session Order Intent
  -> common RiskEngine -> EquitySimulationBroker -> common Fill -> Decimal Portfolio
  -> isolated SQL session checkpoint / WriterLease -> deterministic replay

Meritz instrument master -> MarketDataClient -> allowlisted read-only REST
                          -> AccountClient / OrderReader -> observation reconciliation
                          -> RealtimeClient -> fresh regular quote, after REST reconciliation
```

The original Strategy contract explicitly receives only completed bars and targets weights. Laoer requires multiple simultaneous order intents with pre-session state and LOC time-in-force. This branch adds a pure session planner rather than extending the BTC signal type or treating a close-auction order as a normal limit order. The stock simulator reuses Portfolio, Decimal precision, Fill, RiskEngine, metric helpers, DB engine and writer fencing. Existing Upbit engine, broker, strategy, persistence schema, monitoring and recovery paths stay in place. The equity runner does not claim to run the original continuous Upbit engine.

The broker observation branch is separate from the research planner. It has no path that transmits an order. Disconnection, reconciliation mismatch or unknown order freezes observation state; a fresh quote stream is explicitly reopened and checks REST state before yielding. This is not an unattended reconnect scheduler. REST account observations are sequential, not an atomic broker ledger snapshot; this is insufficient for live reconciliation. Realtime order/fill notifications and book consumers are deferred.

The isolated simulation store persists an append-only series of complete sessions, config hash and exact checkpoints. The checkpoint includes immutable cycle ID, start, allocation, spend/cash, average entry, quantity, tranche days, target, realized PnL, fill count/hash, last intent state and risk baselines. Writes are fenced transactionally using the shared lease. Recovery replays committed sessions and compares checkpoints, including fill digest. On commit failure the in-memory process is poisoned and must reopen. No intraday pending order can survive a completed simulated session; partial quantities are recorded, remainders expire. This store is for research and bounded-size replay, not a production archival or multi-currency ledger; replay time and in-memory research histories grow with session count.

For a later production design, keep a separate USD ledger and reconcile external order identities, immutable fills and pending orders before permitting any new intent. Never replace the old Upbit DB with an equity DB.
