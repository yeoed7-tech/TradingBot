# TQQQ Laoer V1 backtest — REJECT

**The frozen 35% holdout drawdown limit failed.** The strategy beat cash on net CAGR and had positive results in 10 of 12 annual evaluation windows, but the 2022–2026 holdout drawdown was −41.35%. No promotion to forward paper or broker order testing.

## Reproduction and data

- Research code: `34215ffd19965563f9869f12f53522df8b8a91db`. Config SHA-256: `e3c760f914106629491fc9a5cdb3cd7e79df19f2bfca1ae7a2e632d3f2b95647`.
- 4,210 NASDAQ sessions, 2010-02-11 through 2026-11-05. Downloaded Yahoo daily chart OHLC, split and distribution events for TQQQ and QQQ, and [FRED DEXKOUS](https://fred.stlouisfed.org/series/DEXKOUS). Yahoo chart is an undocumented research data endpoint. Inputs are identified by hash in the summary; downloaded third-party raw files are not committed. Provider metadata, history and FX vintages may change on later download.
- Calendar is XNAS with early closes and DST. All TQQQ sessions were checked against the calendar; each comparison date has QQQ data. Yahoo split-only OHLC was restored to contemporaneous share scale using future split ratios as unit conversions, not predictive inputs. Adj Close was not used. See [independent data format notes](https://github.com/holochart/holochart/blob/main/examples/demos/tqqq-soxl/data/SOURCES.md) and [TQQQ split list](https://chartexchange.com/symbol/nasdaq-tqqq/historical/splits/). No pre-inception synthetic data.
- Cash starts at USD 10,000; no FX trade. A distribution is an ex-date receivable included in equity but not deployable cash; no tax or payment-date reinvestment modeled. The benchmarks use the same convention and entry cost. Terminal positions are marked, not fictitiously sold.
- Fees and adverse slippage are 5 bp per side, configurable. Fixed sale limits require a buffered trigger; this is an execution proxy. Gross rerun can produce different fills, not simply net plus fees. USD to KRW translation uses the latest date-matched FRED observation up to each endpoint (max seven-day lookback); FX costs default to 0 and can be set separately with `--fx-cost`. This is ex post valuation, not an FX trading rule.
- Post-open intents use only opening mark and prior portfolio. Historical high and close can affect fills but not the order decision. Daily data cannot show closing-auction liquidity, execution precedence, or the feasible broker cutoff. Whole shares and a $0.01 simulation tick are independent of live eligibility.

```bash
python -m pip install -r requirements.txt
python -m trading_bot.us_equity.research --data /tmp/tqqq-data --fetch-before 2026-11-06 --out reports/tqqq_laoer
```

## Results (USD unless specified)

| Window | Sessions | Net CAGR | Total return | MDD | TQQQ B&H CAGR / MDD | QQQ B&H CAGR / MDD |
|---|---:|---:|---:|---:|---:|---:|
| full | 4,210 | 21.52% | 2505.89% | -55.32% | 39.23% / -81.62% | 17.86% / -33.91% |
| development | 2,237 | 19.54% | 388.25% | -38.99% | 42.05% / -58.07% | 16.19% / -21.77% |
| validation | 757 | 28.85% | 113.68% | -19.13% | 112.41% / -69.88% | 38.61% / -28.33% |
| holdout | 1,216 | 14.85% | 95.42% | -41.35% | 4.51% / -80.30% | 10.91% / -34.73% |

Cash has 0% modeled return and drawdown (no interest). Buy & Hold is fully allocated while the strategy deploys gradually; it is not a risk-matched comparison.

| Window | No-cost rerun CAGR | USD fees | KRW return at zero FX cost | Completed cycles | Exhausted cycles | Max underwater (days) | End unfinished cycle PnL |
|---|---:|---:|---:|---:|---:|---:|---:|
| full | 21.48% | 3,135.60 | 2949.33% | 92 | 28 | 1,073 | -43,280.67 |
| development | 19.53% | 659.92 | 369.94% | 51 | 21 | 220 | -21,308.79 |
| validation | 29.03% | 122.61 | 126.94% | 34 | 4 | 55 | +213.48 |
| holdout | 18.05% | 131.82 | 121.92% | 19 | 8 | 436 | -2,772.76 |

Exhaustion means the tranche cap or inability to buy the minimum share under the remaining budget rule; it does not mean 100% cash depletion. The full run reached 50% / 75% / 100% of allocated cycle spend in 32 / 4 / 0 cycles. Max additional price drawdown after exhaustion was −81.18%, longest exhausted state 1,074 calendar days, and longest cycle 1,133 days. Full-run average and maximum market-value utilization were 37.53% and 84.48%. These metrics show why counting only completed profit cycles is misleading.

## Holdout, annual evaluation and sensitivity

Development 2010–2018, validation 2019–2021, retrospective holdout 2022–2026. Parameters were fixed before the first run. Annual walk-forward is an independent fixed-rule evaluation, not training, parameter reselection, or one continuous equity curve. The preceding three years are contextual metadata; no indicators are warmed and no state or PnL carries over. 2026 is a partial year. 2022 returned −35.24% in its independent window. There is no prospective OOS result.

| Evaluation year | Net return | MDD |
|---|---:|---:|
| 2015 | 22.98% | -17.66% |
| 2016 | 26.28% | -13.01% |
| 2017 | 25.22% | -3.87% |
| 2018 | -14.23% | -26.90% |
| 2019 | 24.65% | -10.42% |
| 2020 | 27.05% | -22.47% |
| 2021 | 22.11% | -6.15% |
| 2022 | -35.24% | -41.35% |
| 2023 | 32.35% | -18.57% |
| 2024 | 29.09% | -8.47% |
| 2025 | 15.65% | -24.62% |
| 2026 | 5.60% | -20.07% |

Development-only one-factor sensitivity is available in summary.json, including tranche count, profit target, interval, budget, LOC buffer and costs. For example, 2/3-day intervals reduced development CAGR to 12.14%/8.34% and MDD to −33.02%/−22.52%. Those results cannot establish an OOS improvement. Stress windows cover the 2020 crash, 2022–2024 long recovery, 2023–2024 bull, quiet 2017 and mixed 2015. Windows restart with fresh USD; the short crash window does not measure an already fully deployed account. Explicit volatility-regime statistical validation is not claimed.

Sharpe, Sortino, Calmar, profit factor, turnover, exact realized/unrealized amounts and recovery metrics are in [summary.json](../../reports/tqqq_laoer/summary.json); no observed losing realized cycles means profit factor is undefined rather than proof of no losses. Daily marks, fills and per-cycle budget states are in the same directory. Reported buy execution drag and a no-cost rerun are separate; no synthetic sell slippage dollars are inferred from high/low data.

## Verification

- Baseline Upbit suite before changes: 126 passed. Final complete suite: 147 passed, 1 existing Starlette deprecation warning (Linux). No test exclusions.
- 80 historical sessions replayed with a new SQLite store and a restart after session 40; exact terminal checkpoint matched uninterrupted execution. See restart_simulation.json. Forward-running paper acceptance remains NOT RUN.
- Real Meritz official master download: PASS. Port 9443 connectivity: ENVIRONMENT_LIMITATION (curl timeout). Authenticated REST/WS: NOT RUN. REST/WS contracts tested with mock transports. Actual order, amendment, cancellation and FX conversion calls: 0.
