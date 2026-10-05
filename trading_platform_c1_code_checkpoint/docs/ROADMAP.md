# 단계별 ROADMAP — Phase 4 운영 기반

기준: 2026-09-28, v0.2.1. **Phase 3 사용자 지정 14개 완료 조건: DONE**.
2026-09-28 수정 후 실제 Upbit 공개 시세 180초 Paper E2E가 성공했다. 장시간 운영 검증은 별도다.
DONE은 해당 범위의 코드와 테스트가 존재한다는 뜻이며, 공개 시세 통합 성공을 대체하지 않는다.

## Phase 1·2

DONE — 기존 연구 파이프라인 유지. 기존 37개 테스트 통과.
EMA/RSI/돌파 3전략의 기존 자산곡선과 완결 거래 CSV가 리팩터링 후에도 동일하다.

## Phase 3 원래 ROADMAP 항목별 상태

| 항목 | 상태 | 근거 / 제한 |
|---|---|---|
| ccxt async Upbit 공개 어댑터 구현 | DONE | 실제 ccxt 메서드·파서를 사용한 HTTP fixture 테스트 포함 |
| 실제 거래소 공개 연결 | DONE | 수정 후 공개 API 54회 성공; TLS 검증 유지 |
| ticker/OHLCV/orderbook 정규화 | DONE | timestamp/가격 검증, 실제 ccxt 파서 경로 테스트 |
| balance/positions/orders/fills 계약 분리 | DONE | 인증 접근은 UnavailableAccountAccess로 명시적 거부; paper 주입 없음 |
| 실제 인증 계좌 조회 | NOT IMPLEMENTED | 이번 범위에 필요하지 않음, private API 호출 없음 |
| 수수료/precision/최소주문 규칙 | PARTIAL | ccxt metadata + 공개 정책 스냅샷 + 설정 수수료; 실제 계정별 최신 규칙 조회 없음 |
| 거래소별 실제 주문 ID/clientOrderId 검증 | NOT IMPLEMENTED | 실제 주문을 만들지 않으므로 Phase 5로 유지 |
| pagination/rate limiter/backoff/timeout | DONE | 페이지 경계·429·timeout·네트워크 테스트 |
| 완료되지 않은 봉 제외/중복 제거 | DONE | adapter/feed/consumer 중복 검증 |
| 누락 탐지와 재접속 backfill | DONE | cursor 유지, gap 복구 후 순서 처리; 오프라인 장애 주입 검증 |
| Historical/Replay/Realtime Feed | DONE | 공통 이벤트 계약과 기존 Backtest 연결 |
| Paper Engine + 기존 Execution/SimulationBroker 재사용 | DONE | 새 회계 구현 없음, 실제 ccxt fixture E2E 가상 왕복 체결 |
| 연결 끊김/stale/비정상/반복 실패 fail closed | DONE | 미체결 취소, 신규 판단 차단, terminal failure 및 risk kill |
| 세션 내 중복 이벤트 replay | DONE | 주문·체결·잔고 중복 없음 |
| 서버 재시작 후 Paper 계좌/미체결 복구 | DONE | Phase 4 DB cursor/order/portfolio/risk 복원; 실제 계좌는 범위 밖 |
| 실제 공개 시세 연속 관측 및 E2E | DONE | 180초, 정상 이벤트 48건, 가상 주문 2건/체결 3건 |
| 실제 주문 호출 0 검증 | DONE | 주문 메서드 spy=0, HTTP public allowlist, 수정 후 공개 GET만 54회 |

## 사용자가 지정한 14개 완료 조건

| # | 완료 조건 | 상태 | 증거 |
|---|---|---|---|
| 1 | ccxt async 실제 공개 시세 연결 성공 | DONE | public_integration_fixed: 공개 API 54/54 성공 |
| 2 | 실제 ticker/OHLCV/필요 시세 수신 성공 | DONE | metadata/ticker/완료봉/orderbook 수신 |
| 3 | 전략이 실제 실시간 데이터로 동작 | DONE | DiagnosticCycle BUY/SELL/HOLD 및 완료봉 123개(워밍업 120개 포함) |
| 4 | Risk Engine 정상 적용 | DONE | 한도·MDD·일 손실·kill 테스트 |
| 5 | SimulationBroker 가상 체결 | DONE | 매수/매도·지정가·부분체결 테스트; 실제 시세에서 매수 부분체결 후 전량 매도 확인 |
| 6 | Portfolio/PnL 정상 계산 | DONE | 수계산 수수료·평균원가·실현/미실현 PnL |
| 7 | 연결 끊김 테스트 | DONE | DISCONNECTED 시 미체결 취소 |
| 8 | reconnect 테스트 | DONE | 정상 데이터 검증 후 복구 |
| 9 | gap backfill 테스트 | DONE | cursor 미진전→누락 복구→중복 없는 반영 |
| 10 | duplicate replay 테스트 | DONE | 중복 봉·호가·이벤트에서 회계/주문 불변 |
| 11 | stale market data 거래 차단 | DONE | feed 및 실행 직전 freshness 검증 |
| 12 | 기존 Backtest regression | DONE | 기존 37개 + 3전략 CSV 일치 |
| 13 | 실제 공개 시세 통합 성공 | DONE | integration_success=true; 프로세스 exit 0 |
| 14 | 실제 거래소 주문 0건 | DONE | façade 메서드 없음, transport 제한, spy/실제 공개 요청 감사 |

**14개 조건 충족. Phase 4·5는 착수하지 않았다.**

근거: `reports/phase3/public_integration_fixed/`, `pytest_after_network_fix.xml`.
기존 연결 실패는 history 문서와 원래 public_integration 결과에 보존했다.
인증 계좌별 규칙·재시작 복구 등 범위 밖 항목의 상태는 그대로 유지한다.

## Phase 4 — 사용자 지정 18개 완료 조건: DONE (SQLite/Paper 범위)

| # | 항목 | 상태 | 근거 |
|---|---|---|---|
| 1 | SQLAlchemy 2.x ORM | DONE | `persistence/models.py`, 11개 테이블 |
| 2 | Alembic migration | DONE | 0001 upgrade/downgrade/upgrade 테스트 |
| 3 | SQLite | DONE | 실제 Paper 실행과 재시작, 파일 기반 회계 |
| 4 | 주문 idempotency | DONE | client_order_id unique, outbox 중복·충돌 테스트 |
| 5 | Fill exactly-once 효과 | DONE | Fill ID primary key, 중복 적용 후 회계 동일 |
| 6 | Portfolio accounting transaction | DONE | Fill+Position+Cash+Snapshot 한 트랜잭션, 3지점 rollback |
| 7 | Risk 재시작 복구 | DONE | 일/주 기준·peak·loss·ATR/이전 종가 복원 |
| 8 | Position 재시작 복구 | DONE | 수량·원가·평균진입가·현금 보존 테스트 |
| 9 | Kill switch 재시작 복구 | DONE | 실제 자식 프로세스 종료 후 kill 유지 |
| 10 | Market cursor 복구 | DONE | 마지막 확정 완료봉 DB 복원 |
| 11 | Gap backfill 후 realtime | DONE | 누락 시 GAP→연속봉 조회→NORMAL 테스트 |
| 12 | Duplicate replay | DONE | 봉/주문/Fill 반복 입력, account 값 불변 |
| 13 | Crash recovery | DONE | os._exit 5개 경계 + exception rollback 7개 경우 |
| 14 | Reconciliation mismatch 신규 주문 중단 | DONE | DB/SimulationBroker 비교, latch·재시작 차단 |
| 15 | FastAPI 상태 조회 | DONE | 9개 읽기 API + health, TestClient |
| 16 | Dashboard 핵심 상태 | DONE | 상태/전략/자산/위험/주문/체결/오류 표시 |
| 17 | 민감정보 redaction | DONE | DB 이벤트·로그/API/화면 테스트 |
| 18 | Phase 1~3 regression | DONE | 기존 79개, 최종 전체 101개 통과 |

추가 검증: 실제 Upbit 공개 시세+DB Paper E2E 첫 실행 성공, 실제 주문 0건.
동일 DB 재시작 결과는 `TEST_REPORT.md`의 최종 기록을 따른다.
PostgreSQL **실서버 테스트: ENVIRONMENT_LIMITATION** (Docker 명령 없음). 모델/URL/compose/
로컬 검증 스크립트는 제공한다. 이는 위 18개 필수 기준에 포함된 SQLite 검증을 대신하지 않는다.
장시간 운영 또는 실제 네트워크 회선 단절의 시험 결과로 확대 해석하지 않는다.

## Phase 5 — NOT IMPLEMENTED

실제 인증 거래소 주문/취소, 실계좌 reconciliation, 실자금·선물/레버리지,
실거래 활성화 및 자동 전략 교체는 구현하지 않았다. `live` 명령은 계속 거부한다.

## Phase 4.5 — Pre-Live Operational Hardening (PARTIAL)

기준: 2026-09-29 KST. Phase 4의 기존 완료 범위는 유지하며 Phase 5는 **NOT IMPLEMENTED**.
이 표의 DONE은 명시한 부분 경계에 대한 코드·자동 테스트가 있다는 뜻이다.
실행하지 않은 장시간/실서버 시험은 DONE으로 취급하지 않는다.

| # | 완료 조건 | 상태 | 증거와 제한 |
|---|---|---|---|
| 1 | 핵심 회계 Decimal 전환 | PARTIAL | Numeric(38,12) migration·정책 유틸; Portfolio/Execution/Risk float 남음 |
| 2 | Decimal migration | DONE | 0001→0002→0001→head 기존 값 보존 SQLite 테스트 |
| 3 | Accounting 회귀 | DONE | 전체 110개 pytest 중 기존 101개 통과; Decimal 전면 전환 회귀는 불가 |
| 4 | 단일 active trader | DONE | 동일 account 두 번째 실제 프로세스 fail closed |
| 5 | stale lease 복구 | DONE | TTL 후 token 증가, os._exit child 종료 뒤 인계 테스트 |
| 6 | fencing | DONE | 만료/탈취된 token의 DB 첫 쓰기 조건부 UPDATE 차단 |
| 7 | WebSocket realtime feed | DONE | 최신값 보존 수정 후 실제 Public WS 97초 NORMAL, 가상 체결 1; 1/6/24h 미실행 |
| 8 | REST recovery/backfill | DONE | 기존 Phase 3 경로 재사용, WS gap 모의 시험 |
| 9 | WS reconnect | PARTIAL | timeout/disconnect/중복/역순/재접속 모의 시험; 실제 장시간 연결 재개 미검증 |
| 10 | REST/WS 역할 | DONE | WS 호가, REST 확정 봉/시작·복구; Strategy는 FeedEvent만 수신 |
| 11 | soak runner | DONE | 1/6/24h 선택, RSS/DB/log/이벤트/주문/재접속 계측 |
| 12 | 실제 장시간 Paper | PARTIAL | 92초 REST + 수정 후 97초 WS 정상, 1/6/24h 미실행 |
| 13 | memory/log/DB growth | PARTIAL | 92초 7 sample, +163,840B RSS, DB 정체; 장기 추세 미확인 |
| 14 | 전략 snapshot/bounded recovery | DONE | 3전략 JSON 상태와 cursor 원자 저장, plugin fallback full replay |
| 15 | restart 결과 동일성 | DONE | 3전략 snapshot/full replay 동일, 실제 WS SIGKILL→TTL→token 2→REST backfill→72초 정상, 주문/체결·현금/수수료 불변 |
| 16 | monitoring heartbeat | DONE | lease/process/DB/feed/strategy timestamp, health 노출, 인증 opt-in |
| 17 | chaos tests | PARTIAL | REST/WS/DB/충돌/강제 종료 일부; disk-full/clock jump/PG 연결 상실 미검증 |
| 18 | duplicate trader process | DONE | child process가 동일 account lease 획득 거부 |
| 19 | 전체 Phase 1~4 regression | DONE | 최종 113 passed, 경고 1건 |
| 20 | 실제 주문 API 호출 0 | DONE | Public-only adapter 경계, REST·WS 관측 HTTP audit 0건 |

PostgreSQL 실서버: **ENVIRONMENT_LIMITATION** (Docker/PostgreSQL 실행파일 없음).
회계 Decimal, 1/6/24시간 WS soak, 장시간·다른 호스트 chaos 검증이 남아 있어 Phase 4.5 전체는 **PARTIAL**.
Phase 5 인증/실거래 주문은 시작하지 않는다.

## Phase 4.5-B — Accounting Precision & Runtime Boundedness

| 완료 조건 | 상태 | 근거 |
|---|---|---|
| Decimal 핵심 회계, ORM asdecimal, 0003 migration | DONE | `ExactDecimal`, SQLite TEXT 정밀 저장 / PG Numeric(65,24), 0002↔0003 값 보존 |
| 부분체결·수치 스트레스·Fill 중복·rollback·restart | DONE | 12,000회 인메모리 체결, 2,000회 durable Fill, 기존 crash/replay 회귀 포함 |
| Decimal reconciliation | DONE | cash/quantity/cost/fee/realized/risk 기준 정확 비교, 1e-24 차이 탐지 |
| 운영 이력 bounded, Research full history | DONE | 최근 cache 상한 설정; DB만 전체 이력, 100,000 event 가속 시험 |
| SQLite 잠금·write fault·clock anomaly | DONE | 실제 SQLite BEGIN IMMEDIATE 잠금 + fault injection + 시계 역행/만료 검사 |
| 실제 공개 WS Paper 짧은 smoke | DONE | 82초 NORMAL, Strategy→Risk→SimulationBroker→Decimal Portfolio→DB, 가상 주문/체결 1건, 주문 HTTP 0 |
| 전체 regression | DONE | 초기 113개 + Phase 4.5-B 신규 테스트; 최종 숫자는 `TEST_REPORT.md` 참조 |
| 실제 1/6/24h soak | NOT RUN | runner 준비, 실행 시간별 증거 없음 |
| PostgreSQL 실서버 | ENVIRONMENT_LIMITATION | Docker/psql 없는 환경, 로컬 통합 스크립트 개선 |

Phase 4.5 전체는 **PARTIAL**이며 다음 단계는 **Phase 4.5-C Operational Acceptance**다. Phase 5는 **NOT IMPLEMENTED**.

## Phase 4.5-C1 — 1-Hour Real Public Paper Acceptance

**ENVIRONMENT_LIMITATION / 1시간 항목 NOT RUN.** 시작 전 124개 회귀 통과, 공개 WS Paper 약 47분까지 직접 관측. Work exec-server 단절과 작업공간 reset으로 60분 최종 증거와 DB가 유실되어 PASS 불가. 로컬/VM 한 명령 재실행 절차는 `PHASE_4_5_C1_REPORT.md`와 `SOAK_TEST.md`를 따른다. C1 PASS 전 C2를 시작하지 않는다. Phase 5는 NOT IMPLEMENTED.
