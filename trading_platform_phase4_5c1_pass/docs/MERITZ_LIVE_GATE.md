# Meritz gates — no live order implementation

| Stage | Status |
|---|---|
| Strategy specification | DONE: bounded V1 research adaptation |
| Historical backtest | DONE: 4,210 actual market sessions |
| Retrospective holdout / annual fixed-rule evaluation | DONE, strategy screen failed: REJECT |
| SimulationBroker | Offline fixtures and deterministic historical restart tested; forward-running paper acceptance NOT RUN |
| Meritz test/simulation | UNVERIFIED; example testbed is not a trade sandbox |
| Authenticated read-only account integration | NOT RUN; adapter and explicit local probe implemented |
| Live infrastructure validation | NOT IMPLEMENTED |
| Small-capital live | PROHIBITED pending later evidence and user approval |

No buy, sell, cancel, amend, or FX conversion was sent. MERITZ_LIVE_TRADING=false is documented, and this build has no write transport even if the flag is changed. A flag is not permission.

A later release would require live enable flag, approved strategy/config hash, exact approved account and symbol, per-run explicit startup confirmation, confirmed tick/unit/currency and regular-session order eligibility. All are necessary, none alone sufficient. Private authentication and signed local secrets must not be stored in Git. Before a live request: durable intent and reservation in a fenced DB transaction; bind account, cycle, session, tranche and deterministic intent ID; record status SENT/UNKNOWN and observation timestamp. A timeout transitions to UNKNOWN, pauses new buys, reads today/history and execution detail, checks quantity and order identity, and never blindly repeats the POST. If no unambiguous unique match is available, remain halted and escalate. Preserve each distinct fill exactly once using broker date/order number/execution number. An order acceptance is not a fill.

Later gate also requires approved forward data and OOS, a fixed spec, modeled fees and terminal marks, recovery under kill conditions, a validated API simulator if offered, authenticated read-only matching, then demonstrated reconciliation and restart under broker error scenarios. User approval must occur after these results. This branch does not advance past the failed strategy screen.
