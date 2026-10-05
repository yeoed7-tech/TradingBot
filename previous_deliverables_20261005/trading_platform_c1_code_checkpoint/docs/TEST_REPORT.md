# Phase 4 테스트 보고서

Python 3.12.14. 기준: 2026-09-28.

## 자동 테스트

| 실행 명령 | 결과 |
|---|---|
| `python -m pytest -q --junitxml=reports/phase4/phase3_regression_before.xml` | 기존 Phase 1~3: **79 passed** (5.24s) |
| `python -m pytest -q tests/test_phase4_persistence.py` | Phase 4: **22 passed** |
| `python -m pytest -q --junitxml=reports/phase4/all_tests.xml` | 전체: **101 passed** (5.03s), 1 Starlette/httpx deprecation warning |

고정된 Alembic 0001 스키마로 upgrade한 뒤 ORM autogenerate diff가 비어 있음도 확인했다.
최종 전체 테스트를 다시 실행했다. 실패/skip 없음. warning은 TestClient
의존성에서 발생했으며 HTTP/API 테스트는 정상 통과했다.

검증 범위: ORM/migration upgrade·downgrade, 주문 client ID 멱등성·충돌,
Fill ID 재전달, 매수/매도 회계와 현금·원가·PnL·수수료, 동일 트랜잭션 3지점 롤백,
실제 자식 프로세스 `os._exit` 5지점, risk kill/position/cursor 재시작,
중복 market/Fill/Order, gap→backfill→NORMAL, DB/broker mismatch latch, 9개 API 및 Dashboard,
redaction/로테이션 로그. 이전 Backtest 79개도 유지했다.

## 실제 공개 시세 + DB Paper 검증

1차(기존 코드를 Phase 4로 연결한 구현 중간):

```bash
python -m scripts.public_integration --duration 150 --out reports/phase4/public_integration
```

- 공개 API 46/46 성공, 정상 이벤트 41건, 가상 주문 2건/체결 3건, 주문 HTTP 0건.
- DB 검증: orders 2, fills 3, 완료봉 122, cursor 07:49 UTC, cash 999,823.4504242601 KRW.

동일 DB 재시작:

```bash
python -m scripts.public_integration --duration 70 --out reports/phase4/restart_integration
```

- 공개 API 23/23 성공, 완료봉 124로 전진, cursor 07:51 UTC.
- cash 999,823.4504242601 KRW, orders 2, fills 3, 기존 position 0.00000001 BTC 및 risk kill false 유지.
- 중복 가상 주문·체결 없음, 실제 주문 HTTP 0건.

최종 코드로 별도 깨끗한 DB에서 150초 재실행:

```bash
python -m scripts.public_integration --config reports/phase4/final_live.toml \
  --duration 150 --out reports/phase4/final_live_first
```

- 공개 API 47/47 성공, 정상 이벤트 42건, 가상 주문 2건·체결 2건, 실제 주문 API 0건.
- 1,000,000 KRW 시작 → cash/equity 999,802.51063318 KRW, 실현 PnL -197.48936681999476 KRW,
  fees 99.99526682 KRW, risk_killed=false, integration_success=true. 이는 배관 검증이지 수익성 검증이 아니다.
동일 DB 최종 코드 재시작:

```bash
python -m scripts.public_integration --config reports/phase4/final_live.toml \
  --duration 50 --out reports/phase4/final_live_restart
```

- 공개 API 16/16 성공, 정상 이벤트 13건. DB 완료봉 122→123, cursor 07:56 UTC.
- cash 999,802.51063318 KRW, orders 2, fills 2, realized PnL -197.48936681999476 KRW,
  fees 99.99526682 KRW, position quantity 0, risk kill false가 그대로 유지됐다.
- 신규 중복 주문/체결 0, 실제 주문 API 0, integration_success=true.
- 증거: `final_live_db_status.json`, `final_live_evidence.sqlite3`, 각 실행의 summary/events.


## 미실행/한계

- `docker --version` → `command not found` (exit 127). PostgreSQL 실서버 ORM/migration 테스트:
  **ENVIRONMENT_LIMITATION**. 로컬 Docker 검증은 `DATABASE.md`의 절차를 사용한다.
- 실제 NIC/거래소 장시간 장애, DB 디스크 손상, 다중 writer, 장시간 운영은 시험하지 않았다.
- WebSocket은 Phase 3의 별도 독립 연결 진단으로 검증했고 본 Paper Realtime Feed는 REST polling이다.
- 실제 주문 전송은 구현·실행하지 않았으며 모든 실제 요청은 allowlist의 공개 GET이었다.

## Phase 4.5 실제 실행 기록

| 명령/시험 | 결과 | 상태 |
|---|---|---|
| 시작 전 `python -m pytest -q` | 101 passed, 1 warning, 5.63s | DONE |
| 최종 `python -m pytest -q` | 113 passed, 1 warning, 8.13s | DONE |
| `python -m pytest -q tests/test_phase45_hardening.py --maxfail=1` | 12 passed, 1 warning, 2.60s | DONE |
| SQLite Alembic 0001→0002→0001→head | 기존 12.345 현금 보존, lease 테이블 생성/제거 | DONE |
| 중복 trader fork/강제 종료/만료/fencing | 두 번째 거부, 1초 TTL 뒤 token 2, 이전 token 거부 | DONE |
| EMA·RSI·돌파 state snapshot/full replay | 각 40봉 신호 동일 | DONE |
| REST 공개 시세 `python -m scripts.soak_paper --seconds 90 --quote-source rest ...` | 실제 92.00초, 정상 24 event, 공개 API 29/29, 0 live HTTP | PARTIAL |
| WS 공개 시세 최초 probe | opening handshake TimeoutError | FAILED (첫 시도) |
| WS 공개 시세 `python -m scripts.soak_paper --seconds 60 --quote-source websocket ...` | 실제 연결, 정상 4 event, 가상 주문/체결 각 1, STALE_DATA 반복 후 FAILED, 실제 주문 0 | PARTIAL |
| synthetic `python -m scripts.benchmark_feed` | 1/10/50 symbols: 약 355k/409k/413k strategy dispatch events/s | PARTIAL (전 Feed/DB 측정 아님) |
| PostgreSQL 실서버, 1/6/24시간 soak | 실행하지 못함/하지 않음 | ENVIRONMENT_LIMITATION (PG), NOT IMPLEMENTED (장시간) |

REST 92초 7 sample에서 RSS 184,086,528→184,250,368 B, DB 151,552 B 일정,
로그 21,263→23,366 B. snapshot 2→25. 60초 WS 시도에서 공개 REST API 4/4,
실제 주문 HTTP 0. 장시간 메모리 안정성, 실제 WS 강제 종료 복구는 뒤의 별도 절에서 검증했다. 1/6/24시간과 전면 Decimal 정산은 입증하지 않았다. 추가 수정 후 WS 재실행 결과는 별도로 아래 기록한다.

### 최신 호가 읽기 수정 후 재검증

| 명령 | 결과 | 상태 |
|---|---|---|
| 수정 후 WS 공개 시세 `python -m scripts.soak_paper --seconds 95 --quote-source websocket --database /tmp/phase45_ws_fixed.sqlite3 --out reports/phase45_ws_fixed --sample-seconds 15` | 실제 97.00초, NORMAL, 23 event, 가상 주문/체결 1, stale/gap 0, 실제 주문 0 | DONE (97초 범위) |

WebSocket 메시지 backlog를 발견해 별도 읽기 루프로 최신 호가만 보존한 뒤 재시험했다.
Public REST 4/4 성공, reconnect 0, integration_success=true. 7 sample의 RSS
183,353,344→184,623,104 B, DB 131,072→151,552 B, 로그 25,037→26,188 B.
1/6/24시간 안정성과 실제 네트워크 재접속 E2E는 이 결과만으로 완료 표시하지 않는다.

### 같은 DB 정상 종료 후 WebSocket 재시작

`python -m scripts.soak_paper --seconds 70 --quote-source websocket --database /tmp/phase45_ws_fixed.sqlite3 --out reports/phase45_ws_restart --sample-seconds 15`

실제 72.00초, NORMAL, 정상 이벤트 14건, 전체 완료봉 cursor 121→123,
orders/fills DB 건수 1→1(중복 효과 없음), REST 공개 API 4/4, WS reconnect 0,
실제 주문 HTTP 0. `reports/phase45_ws_restart/soak.json` 원본 보존.
이는 정상 종료 후 복구이며 강제 종료 실환경 E2E와 구분한다.

### 실제 WebSocket 프로세스 강제 종료→재시작

1. `timeout -s KILL 45s python -m scripts.soak_paper --seconds 90 --quote-source websocket --database /tmp/phase45_ws_crash.sqlite3 --out reports/phase45_ws_crash_before --sample-seconds 10` → exit 137.
2. 종료 직후 DB: account/position/order/fill/risk/cursor 각 1건, lease token 1,
   cursor `2026-09-28T16:18:00+00:00`. 즉시 새 owner 획득 시 `LeaseLost`로 거부.
3. TTL 만료 뒤 `python -m scripts.soak_paper --seconds 70 --quote-source websocket --database /tmp/phase45_ws_crash.sqlite3 --out reports/phase45_ws_crash_restart --sample-seconds 15` → 실제 72.00초, NORMAL, WS 메시지 162건 수신, 정상 이벤트 8건, token 2.
4. REST 복구 후 cursor `16:18`→`16:20`, OHLCV 120→122. 주문·체결 1→1.
   현금 899,866.7872144, 수수료 50.0415856, 실현손익 0은 종료 전 snapshot과
   복구 뒤 account/snapshot에서 같았다. position quantity 0.0008812 유지. 실제 주문 HTTP 0.

**DONE (이 시나리오 범위):** 같은 Paper DB·전략의 강제 종료, lease 인계, 완료봉
backfill, 새 WS quote, 중복 없는 회계. 1/6/24시간 soak 또는 PostgreSQL 장애 전환은 미검증.

## Phase 4.5-B 검증 (2026-09-28 UTC)

시작 전 기존 프로젝트 `python -m pytest -q`: **113 passed, 1 warning, 8.13s**, 문서의 기존 113개와 일치했다. Decimal 수정 뒤에도 기존 113개를 재실행해 모두 통과했다. 새로운 시험을 추가한 최종 전체 결과는 아래 최종 실행 기록을 따른다.

| 명령/시험 | 실제 결과 | 상태 |
|---|---|---|
| `python -m pytest -q tests/test_phase45b_precision.py` | 0002↔0003 SQLite 값 보존, 12,000회 부분매수/매도, 100,000 journal event, 2,000건 durable 주문/Fill·복구 최근 100, 실제 SQLite BEGIN IMMEDIATE lock, write fault, clock anomaly, 1e-24 reconciliation | DONE |
| 기존 113개 회귀 | Phase 1~4.5 전략/백테스트/공개 Feed/복구/API 전부 통과 | DONE |
| `python -m scripts.soak_paper --seconds 80 --quote-source websocket --database /tmp/phase45b_ws_smoke.sqlite3 --out reports/phase45b_ws_smoke --sample-seconds 15` | 실제 82.00초, NORMAL 17 event, signals 1, simulated order/fill 각 1, stale/gap/exception 0, reconnect 0, 공개 API 성공 3/4(1회 재시도), 실제 주문 HTTP 0, integration_success=true | DONE (짧은 smoke만) |
| Docker/psql 확인 | 명령 없음 | ENVIRONMENT_LIMITATION (PostgreSQL 서버) |
| 실제 1h/6h/24h | 실행하지 않음 | NOT RUN |

공개 WS 시험의 마지막 Decimal cash `899892.179844370000000000000000`, equity `999919.138554370000000000000000`, 누적 미실현 포함 PnL `-80.861445630000000000000000`. 6개 sample RSS min/max `152326144/186081280` bytes, DB 159744 bytes, log 36990 bytes. 초기화/통신 메모리 증가가 포함된 짧은 표본이다. 원본 `reports/phase45b_ws_smoke/soak.json`과 테스트 출력 `reports/phase45b_pytest.txt`를 보존했다. 해당 실제 실행은 변경 직후 소스에서 진행됐고, 보고서 집계의 `final_pnl`은 equity−initial cash로 정정했다. 장시간 선형 증가 여부는 이 표본으로 판단할 수 없다.

문서/soak 집계 이후 최종 테스트 결과를 추가로 기록한다.

최종 `python -m pytest -q > reports/phase45b_pytest.txt 2>&1`: **124 passed, 1 warning, 16.92s**. 경고는 FastAPI TestClient와 Starlette의 `httpx` 이전 API 사용 알림으로 시험 실패가 아니다. 0003 migration 단독 왕복은 신규 11개 중 1개에서, 0001/0002 기존 경로는 이전 회귀에서 함께 검증했다. PostgreSQL 실서버와 1/6/24시간은 실행하지 않았다.

### 백테스트 수치 비교 (기존 Phase 4.5 코드 vs Decimal 변경 코드)

`synthetic_data(400, symbols=('BTC/USDT',))`, 동일 기본 Settings, EMA(3,10), RSI(7,35,65), Breakout(0.5)를 각각 두 소스 트리에서 `PYTHONPATH=. python /tmp/phase45b_compare.py`로 실행했다. 원본 JSONL은 `reports/phase45b_backtest_comparison_{old,new}.jsonl`에 있다.

| 전략 | 기존 최종 자산 | 변경 후 최종 자산 | Fill 건수 기존→변경 | 자산 차이 |
|---|---:|---:|---:|---:|
| EMA | 99634.67028398384 | 99634.67028398383 | 10→10 | -1.46e-11 |
| RSI | 100681.48508586513 | 100681.48508586515 | 21→21 | +1.46e-11 |
| Breakout | 99679.65821798479 | 99679.65821798483 | 74→74 | +4.37e-11 |

변경은 백테스트 연구 DataFrame을 float로 투영할 때의 마지막 자릿수 수준이며 Fill 수와 전략 동작은 동일했다. Golden 데이터를 새 값으로 덮어쓰지 않았다. 이는 해당 synthetic 데이터 한 묶음의 비교로 한정한다.

추가 재시작 경계 시험에서 완료봉 이전 `risk_state.week`가 기존 코드에서 문자열 `null`로 저장되는 경우 복원이 예외로 끝나는 문제를 발견했다. 저장 시 SQL NULL, 과거 문자열 `null` 모두 `None`으로 복구하도록 수정했다. 금액성 peak/day/week의 24자리 Decimal 동일성 시험을 추가한 뒤 최종 124개를 재실행했다.

## Phase 4.5-C1 (미완료)

- 시작 전 `python -m pytest -q`: **124 passed, 1 warning, 18.05s**.
- 실제 `python -m scripts.soak_paper --hours 1 --quote-source websocket --database reports/phase45c1/paper_1h.sqlite3 --out reports/phase45c1 --sample-seconds 30`: 시작, 약 2,820.48초 마지막 직접 확인. Work exec-server reset으로 60분에 이르지 못하고 원시 DB/계측 유실. **ENVIRONMENT_LIMITATION**, 1시간 Acceptance **NOT RUN**.
- 복구된 코드에 C1 한 명령 계측/독립 원장 검증 스크립트를 추가했다. `--seconds 25` 짧은 진단은 실제 약 30초, 네트워크 공개 REST 4회/WS 메시지 37건, Private/주문/취소 HTTP 0, 독립 Decimal 대조 PASS. 시간 미달이므로 Acceptance 아님.
- 자체 프로세스 RSS 계측을 보완한 `--seconds 15` 진단은 약 20초, 원시 RSS 기록 성공, 무신호로 최종 reconciliation FAIL. 이 역시 1시간 증거가 아니다.
- 마지막 전체 `python -m pytest -q`: **124 passed, 1 warning, 17.22s**. PostgreSQL 실서버, 6/24시간 실행은 하지 않았다.
