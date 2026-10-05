# Phase 4.5-C1 — 1-Hour Real Public Paper Acceptance

**최종 판정: PASS / 1시간 Operational Gate: DONE.**

2026-09-30의 새 DB에서 단일 프로세스를 연속 실행했다. 이전47분/58분30초 시도와 시간을 합산하지 않았다. 원시 DB·CSV·시작 상태·회귀 로그·최종 네트워크 감사가 보존돼 있다. 다음 단계는 **Phase4.5-C2 — 6-Hour Operational Acceptance**이며 이번 작업에서 시작하지 않았다. Phase5는 NOT IMPLEMENTED다.

## 실행과 설정

```bash
.venv/bin/python -m scripts.phase45c1_accept --config config/paper_upbit.toml --database reports/phase45c1_run_20260930_approved/paper_1h.sqlite3 --out reports/phase45c1_run_20260930_approved
```

- Paper 시작 `2026-09-30T01:25:46.270819+00:00`, 종료 `2026-09-30T02:25:46.546915+00:00` (UTC; KST+9시간).
- Paper 프로그램 실제 시간 **3600.276096초**. 이 값은 public 초기화와 종료 정리를 포함한다. soak runner 실측 **3602.007414초**, 외부 계측 wrapper **3630.248656초**로 서로 구분한다.
- Upbit `KRW-BTC` / 내부 `BTC/KRW`, 1m, EMA20/100, weight0.1. 전략 설정을 변경하지 않았다.
- 가상 시작 현금1,000,000KRW, fee0.0005, slippage5bps, public orderbook WebSocket + completed candle REST, SimulationBroker.
- DB `/workspace/scratch/32862f77f60b/phase45b_work/reports/phase45c1_run_20260930_approved/paper_1h.sqlite3`, PID `63468`, writer owner `81ee5d11-e775-44d3-80c8-0149767f1a72`, fencing token `1`.
- git checkout은 없으며 source SHA256 `fe3e6146da89534a165fe79a0e080d00101233b4637c27f0ae1795aebc48e3ef`. 전체 canonical config와 config SHA는 `start_state.json`에 있다. 인증정보/API Key 없이 수행했다.

## Regression과 실행환경 진단

| 시험 | 실제 결과 | 상태 |
|---|---|---|
| 사전 전체 regression | 126 passed, 1 warning in 28.51s | DONE |
| 사후 전체 regression | 126 passed, 1 warning in 28.58s | DONE |
| 최초 제한 sandbox의 로컬 FastAPI TestClient | 프로젝트 테스트20초 timeout; 무관한 최소앱도15초 timeout | ENVIRONMENT_LIMITATION |
| 같은 프로젝트 테스트를 승인된 실행경로에서 재확인 | 1 passed, 1 warning, 1.80s | DONE |
| 새 승인된 실행경로의 전체 C1 | 정상 종료, child exit0 | DONE |

최초 sandbox wrapper는 soak 시작 전 멈췄고 검증 전용 pytest/wrapper를 종료했다. 테스트를 삭제하거나 skip하지 않았으며 거래소 주문 경로도 변경하지 않았다. 경고1개는 FastAPI/Starlette httpx deprecation이다. 이 작업의 소스 로직 변경은 없었다. 이전 실패 시도의 원인은 당시 환경 reset이며 휴대폰설정/앱종료 원인으로 단정하지 않는다.

## Memory / DB / Log

| 관측 항목 | 실제 값 |
|---|---:|
| RSS 시작 / max / 종료 | 166047744 / 204480512 / 204480512B |
| RSS delta | 38432768B |
| 전체 RSS slope | 5611277.44B/h |
| 후반 절반 RSS slope | 4397062.24B/h |
| 활성 마지막 약8분 RSS slope / delta | 1511312.70B/h / 155648B |
| DB 시작 / 종료 / 증가 | 0 / 409600 / 409600B |
| 공용 logs 폴더 시작 / 종료 / 증가 | 56947 / 59603 / 2656B |
| DB snapshot / 메모리 recent snapshot | 1178 / 1000 |
| 메모리 recent events / 설정 maxlen | 1000 / 1000 |

전체 delta는 초기 연결/라이브러리 적재와 종료 serialization을 포함한다. 작은 증가 자체가0이 된 것은 아니다. 후반 RSS slope는 runner의 사전 기준10,000,000B/h 이내이며 마지막 활성 구간 증가폭도 작았다. DB snapshot은1,178개지만 메모리 recent snapshot/event는각1,000개로 제한됐다. 이번1시간에서 이벤트 수에 따라 무한히 커지는 container나 비정상 지속 증가 증거는 없었다. 며칠간 leak 부재까지 입증한 것으로 확대하지 않는다.

최종 cache: `{"orders": 2, "fills": 10, "events": 1000, "snapshots": 1000, "trades": 1, "execution_events": 2, "risk_events": 0}`. 모든값이 설정상한1,000 이내다. CPU·heartbeat·DB·회계 시계열은 원본 `runtime_metrics.csv`, 자체RSS/CPU는 `runtime_self.jsonl`에 있다. logs최종 크기는 사후 회귀가 쓰는 공용로그도 포함한다. retention을 임의로 실행하거나 주문/Fill을 삭제하지 않았다.

## Feed / Trading / Errors

| 항목 | 실측 |
|---|---:|
| Public REST HTTP attempts/successes | 63 / 63 |
| WS connections / valid messages | 1 / 27512 |
| WS reconnect / duplicate | 0 / 0 |
| 정상 feed events | 1177 |
| stale / gap / feed duplicate | 0 / 0 / 0 |
| OHLCV rows / signals | 180 / 61 |
| Paper orders / fills / closed round trips | 2 / 10 / 1 |
| rejected orders / risk halt | 0 / 0 |
| exceptions / DB errors / reconciliation mismatches | 0 / 0 / 0 |
| writer/fencing violations / error events | 0 / 0 |

`feed.metrics.rest_requests=1177`는 논리 조회 횟수이며 실제HTTP63회와 구별한다. WS disconnect/REST timeout/gap/stale가 자연발생하지 않아 실운전 recovery 시간과 backfill 범위는 **NOT RUN**이다. 자동 recovery/failure tests는126개 regression에 포함돼 통과했다. malformed/backfill 독립 누적 카운터는 결과에 따로 노출되지 않으므로 그 항목의 별도 계측은 **PARTIAL**로 남긴다. 최종 system_events는INFO STARTUP/SHUTDOWN각1건이며 정상완료다.

## 독립 Decimal accounting / Reconciliation

BUY1회 후 SELL 주문이 여러Fill로 부분체결되어 전량청산됐다. Fill10건을 저장순서대로 독립Decimal 계산해 DB/runtime의 cash·quantity·cost·fees·realized PnL을 정확 equality로 비교했다. float tolerance를 사용하지 않았다.

| 원장 항목 | 독립 계산 및 DB/runtime 공통 값 |
|---|---|
| Cash / Equity | `999611.328632360000000000000000`KRW |
| BTC quantity / remaining cost / average entry | `0` / `0` / `0` |
| Fees | `99.908887640000000000000000`KRW |
| Realized PnL | `-388.671367640000000000000000`KRW |
| Unrealized PnL | `0` |
| Open orders | 0 |
| Fill count | 10 |
| Final market cursor | `2026-09-30T02:24:00+00:00` |
| Risk kill switch / peak/day/week equity | false /1,000,000 /1,000,000 /1,000,000KRW |

최종 reconciliation **PASS**, mismatches0. SQLite `PRAGMA integrity_check=ok`. Fill/order/client ID/OHLCV unique key중복각0. 정상종료 시 lease를반납했으므로 종료DB owner가빈값인것은예상동작이며 token1은그대로다. 손실은합격기준이아니다. 실제동작한리스크는기존전략/회계상태와정확히연결됐고, loss limit/kill switch고장주입은자동회귀에서별도검증했다.

## Network safety audit

| 항목 | 횟수 |
|---|---:|
| Public REST | 63 |
| Public WS connections / messages | 1 /27,512 |
| Private API | 0 |
| Order HTTP | 0 |
| Cancel HTTP | 0 |
| Guard blocked attempts | 0 |

Public GET allowlist와 SimulationBroker만사용했다. 실제 balance·order·cancel·private auth가실행되지않았다.

## 최종 Acceptance Gate

사용자의15개성공조건을확인했다:60분이상실측,정상종료,미복구feed오류없음,reconciliation/accounting/중복효과/fencing위반없음,cache상한준수,이번구간의비정상RSS증가증거없음,Decimal원장PASS,DB integrityok,관측된risk fail-open없음,Private/실제주문0,사후전체126개회귀통과. **C1 PASS / DONE**으로기록한다.

원본은 `reports/phase45c1_run_20260930_approved`; 필수canonical산출물은 `reports/phase45c1`에복사했다. 이전유실시도의선별재구성CSV와달리이번CSV는연속원본이다. 이전보고서는 `reports/phase45c1_attempts/retry_58m30s/previous_report.md`에보존했다. PostgreSQL은별도ENVIRONMENT_LIMITATION을유지한다. C2/24h/Phase5는이번작업에서시작하지않았다.
