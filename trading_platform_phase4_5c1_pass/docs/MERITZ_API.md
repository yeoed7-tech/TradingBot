# Meritz Open API — official contract review

Reviewed 2026-11-13 KST using [portal](https://openapi.imeritz.com), [official JSON contract](https://openapi.imeritz.com/api-spec/download/json) (generated 11:33:23 KST, SHA-256 `1992523cb32052861858f49812eaa533d1151f923204056150c74239179f72c4`), [official sample repository](https://github.com/meritz-securities/open-api), [application guide](https://openapi.imeritz.com/howto-use), [master file](https://openapi.imeritz.com/stock-info), and [testbed](https://openapi.imeritz.com/testbed-lab). Portal contract overrides example code. No authenticated endpoint was exercised in Work.

| API | Official path or TR | Branch status |
|---|---|---|
| Token | POST /oauth2/token | Environment credentials, client_credentials, scope login; monotonic expiry from expires_in, early renewal, one auth refresh for a read |
| Quote / depth | GET /market/v1/overseas/prices, /market/v1/overseas/orderbook | Quote and best bid/ask normalized; auth required |
| Candles | GET /market/v1/overseas/candles/days, /market/v1/overseas/candles/minutes | Raw days via mod_stpr_cls_code=1; minutes returned as provider rows |
| Buy / sell | POST /trading/v1/overseas/orders/buy, /sell | Contract reviewed; LOC code 32 and close condition 7. Write routes blocked |
| Amend / cancel | POST /trading/v1/overseas/orders/modify, /cancel | Blocked |
| Orderable cash | GET /trading/v1/overseas/orders/estimate | Currency amounts, non-integrated query; not executable quantity |
| Orders | GET /trading/v1/overseas/orders/today, /history | Today observation and history paging; incomplete response cannot clear reconciliation |
| Execution detail | GET /trading/v1/overseas/orders/detail | Date and order number; only detail execution IDs used to deduplicate; no synthetic fee or timestamp assumptions |
| Cash / holdings / FX cash | GET /accounts/v1/me/deposit, /accounts/v1/me/overseas/holdings, /accounts/v1/me/overseas/currencies | Read-only Decimal normalized amounts, distinct buckets |
| Realized PnL | GET /accounts/v1/me/overseas/profit-loss | Paged provider rows with explicit country argument |
| Market calendar | GET /reference/v1/overseas/market-hours, /reference/v1/overseas/market-days | Read-only; broker calendar authority for future runtime not verified |
| Realtime regular quote, depth, order events | wss://openapi.imeritz.com:29443/websocket; ohhts_exst_cntg, ohhts_exst_aspr, ohhts_cntg_exst | Regular quote subscription implemented and mocked. Depth/order event consumers not wired; later work |
| Trading sessions | Regular quote, daytime, after, reservation are separate | Research only regular sessions. No assumption that LOC is accepted in every session |

Downloaded official public `mts_exst_code.mst`. Unique match: TQQQ, NASDAQ market classification **OQ**, exchange vendor **0537**, ProShares UltraPro QQQ. SHA-256 `d066f4324f6e570691ee5b853b29e456580d4a881d8839bd1b3383c784a6f1ca`. USD is confirmed in historical instrument metadata; authenticated Meritz currency, order tick, minimum share unit, sell-only status and account eligibility remain unverified. A zero or missing quote rule is unknown, never a live default. Historical simulation assumes whole shares and $0.01 tick, separate from broker rules. Presence in the master is not an entitlement or order acceptance result.

## Connectivity and limits

- REST guide uses HTTPS port 9443 and an authorization token plus a 12-hex-digit device MAC for relevant authenticated reads. Request token expiry governs; portal describes 12 hours for personal tokens. Authentication errors EGW00121/EGW00123 are retried once on GET; timeout, malformed payload, rate-limit rejection or other error halts the instance. Use a fresh transport after diagnosis. No response body or credential is printed.
- Selected responses use application codes including 0000, 5762, 5766 and 5820; HTTP status alone does not authorize use of results. EGW00200 is a rate-limit error in the contract. Per-TR numerical production limits were not confirmed from the public export. Local conservative pacing is 1 request/s per instance, not a claim about the broker limit.
- The official testbed displays request/response examples and sends no requests. A generic mock-domain field is not confirmation of a usable overseas simulation account. Separate Meritz mock routing is unconfirmed and not implemented.
- The official master and schema downloaded over HTTPS. An unauthenticated GET connectivity probe to port 9443 timed out after 8 seconds in Work (curl 28, no HTTP response). Authenticated quote/positions and live WebSocket are **NOT RUN**. Mock transport is not actual connectivity.
- No remote order idempotency key is present in the reviewed overseas submit fields. Do not infer retry safety from a local intent ID. See live gate.

## Cost and explicit local probe

[Portal fee guide](https://openapi.imeritz.com/intro) says API usage has no separate fee and account trading charges apply. Account commissions, event terms, FX spread, regulatory charges and withholding can vary; research fees are scenario inputs, not Meritz quotes. No automatic conversion.

```bash
python -m trading_bot.core.exchange.meritz.probe --master /tmp/mts_exst_code.mst --download-master
# Later, only after approval for account read verification, set credentials in your own environment:
python -m trading_bot.core.exchange.meritz.probe --master /tmp/mts_exst_code.mst --read-account
```

The second command is an explicit authenticated read probe, not account or order authorization. Set `MERITZ_APP_KEY`, `MERITZ_APP_SECRET` and `MERITZ_MAC_ADDRESS` locally; never commit them or send them through chat. Probe does not print balances, positions or credentials. No such read was run in this work.
