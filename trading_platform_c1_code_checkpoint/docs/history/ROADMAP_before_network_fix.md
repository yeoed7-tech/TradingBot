# 단계별 ROADMAP — Phase 3 검증 체크포인트

기준: 2026-09-28, v0.2. **Phase 3 전체: PARTIAL**.
실제 Upbit 공개 API 연결이 실패했으므로 전체 완료 또는 실시간 운용 검증 완료라고 표시하지 않는다.
DONE은 해당 범위의 코드와 테스트가 존재한다는 뜻이며, 공개 시세 통합 성공을 대체하지 않는다.

## Phase 1·2

DONE — 기존 연구 파이프라인 유지. 기존 37개 테스트 통과.
EMA/RSI/돌파 3전략의 기존 자산곡선과 완결 거래 CSV가 리팩터링 후에도 동일하다.

## Phase 3 원래 ROADMAP 항목별 상태

| 항목 | 상태 | 근거 / 제한 |
|---|---|---|
| ccxt async Upbit 공개 어댑터 구현 | DONE | 실제 ccxt 메서드·파서를 사용한 HTTP fixture 테스트 포함 |
| 실제 거래소 공개 연결 | PARTIAL | market/all GET 3회 실패, ExchangeNotAvailable |
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
| 서버 재시작 후 계좌/미체결 복구 | NOT IMPLEMENTED | DB·복구는 Phase 4. 이번 실행을 다시 시작하면 새 가상 계좌 |
| 실제 공개 시세 연속 관측 및 E2E | PARTIAL | 실행 시도했으나 최초 시장조회 실패 |
| 실제 주문 호출 0 검증 | DONE | 주문 메서드 spy=0, HTTP public allowlist, 실제 시도 GET만 3회 |

## 사용자가 지정한 14개 완료 조건

| # | 완료 조건 | 상태 | 증거 |
|---|---|---|---|
| 1 | ccxt async 실제 공개 시세 연결 성공 | PARTIAL | 연결 시도 실패 |
| 2 | 실제 ticker/OHLCV/필요 시세 수신 성공 | PARTIAL | 정상 시세 0건 |
| 3 | 전략이 실제 실시간 데이터로 동작 | PARTIAL | 오프라인 파서→Feed→전략 테스트만 성공 |
| 4 | Risk Engine 정상 적용 | DONE | 한도·MDD·일 손실·kill 테스트 |
| 5 | SimulationBroker 가상 체결 | DONE | 매수/매도·지정가·부분체결 테스트; 실제 시세 증거는 미확보 |
| 6 | Portfolio/PnL 정상 계산 | DONE | 수계산 수수료·평균원가·실현/미실현 PnL |
| 7 | 연결 끊김 테스트 | DONE | DISCONNECTED 시 미체결 취소 |
| 8 | reconnect 테스트 | DONE | 정상 데이터 검증 후 복구 |
| 9 | gap backfill 테스트 | DONE | cursor 미진전→누락 복구→중복 없는 반영 |
| 10 | duplicate replay 테스트 | DONE | 중복 봉·호가·이벤트에서 회계/주문 불변 |
| 11 | stale market data 거래 차단 | DONE | feed 및 실행 직전 freshness 검증 |
| 12 | 기존 Backtest regression | DONE | 기존 37개 + 3전략 CSV 일치 |
| 13 | 실제 공개 시세 통합 성공 | PARTIAL | integration_success=false |
| 14 | 실제 거래소 주문 0건 | DONE | façade 메서드 없음, transport 제한, spy/실제 공개 요청 감사 |

**1·2·3·13 미충족. 이 상태로 Phase 4로 넘어가지 않는다.**

## Phase 4 — NOT IMPLEMENTED (이번 변경 없음)

- SQLAlchemy/Alembic, SQLite→PostgreSQL, OHLCV/주문/체결/포지션/상태 영속화.
- transaction/outbox, 체결 중복 원장 적용 방지, 재시작 복구/reconciliation.
- FastAPI 모니터링 UI, 접근제어, 로그 회전.
- crash/replay/SQLite·PostgreSQL 일치 검증.

## Phase 5 — NOT IMPLEMENTED (이번 변경 없음)

- 실제 인증 거래소 주문/취소, sandbox/testnet 검증, 응답 불명/취소 경합 조정.
- Decimal 통화 회계, 계좌별 수수료/규칙, 거래소 측 위험제어.
- 기본 비활성 + 승인된 전략/config hash, 사용자 승인 없는 활성화/교체 금지.
- 출금 비활성 키·secret manager·최소권한 운영.

공매도/선물/레버리지, AI 자동전략 생성, Bayesian Optimization, 완성형 웹 대시보드는 이번 범위 밖이다.
