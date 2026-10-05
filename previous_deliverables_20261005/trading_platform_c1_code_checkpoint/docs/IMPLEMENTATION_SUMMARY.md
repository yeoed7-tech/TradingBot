# Phase 4 구현 요약

상태: **SQLite 기반 Paper 운영·재시작 18개 완료 조건 DONE**, PostgreSQL 실서버 검증은
**ENVIRONMENT_LIMITATION**. Phase 5 실거래는 구현하지 않았다.

## 시작점

Phase 3의 ccxt Upbit 공개 REST 어댑터, Feed, Strategy → Risk → Execution → SimulationBroker →
Portfolio가 있었다. WebSocket은 별도 Public API 진단 도구에서 handshake/ticker 수신까지 확인된 반면,
운영 Realtime Feed는 REST polling이다. Phase 3 회귀 79개를 먼저 실행해 모두 통과했다.
실제 거래소 주문 호출 0이라는 안전 경계를 유지했다.

## 변경

- SQLAlchemy 2.x 11개 테이블과 Alembic 0001. SQLite 기본, PostgreSQL URL/드라이버/compose 준비.
- 주문 의도 client_order_id unique Outbox. CREATED Paper 의도는 재시작 시 미시뮬레이션 상태를 확인해 취소.
  UNKNOWN은 자동 재송신하지 않는다.
- Fill ID exactly-once, 기존 Portfolio.apply 회계를 재사용하는 한 DB transaction.
  Paper 이벤트 checkpoint에서 주문·체결·계좌·포지션·리스크·커서를 함께 확정한다.
- 마지막 확정 완료봉 이후의 gap backfill, 전략 완료봉 재생, 현금·원가·포지션·리스크/kill/주문 복원.
- DB/SimulationBroker 비교에서 불일치하면 RECONCILIATION_REQUIRED를 DB에 latch하고 주문 중단.
- 읽기 전용 FastAPI API 9개, 최소 Dashboard, 구성요소 health, 구조화/로테이션 로그, redaction.
- 실제 업비트 공개 시세를 이용한 새 DB Paper 실행과 기존 DB 재시작 증거를 기록했다.

강제 종료 지점 5개, 중복 replay, 일괄 rollback, 위험 정지, backfill, API/화면/로그를 테스트했다.
전략·리스크·기존 Portfolio 회계 규칙과 Backtest 경로는 변경하지 않았다.
운영 범위와 복구 절차는 `DATABASE.md`, `RECOVERY.md`, 검증 결과는 `TEST_REPORT.md`에 있다.

## Phase 4.5 작업 내역 (완료 조건 전체는 미충족)

- **DONE:** Alembic `0002_decimal_accounting`의 Numeric 컬럼·lease/heartbeat 테이블 및 SQLite 기존 데이터 upgrade/downgrade 테스트. DB Numeric 선언은 회계 내부 Decimal 전환의 완료를 뜻하지 않는다.
- **DONE:** 계좌별 lease 획득, 두 번째 프로세스 차단, 만료 복구, 증가 token, DB transaction 진입 전 fencing, 주기적인 lease 갱신.
- **DONE:** 공개 Upbit WebSocket orderbook parser/stream, REST 확정 봉/backfill 조합, 중복·순서 역전·silent timeout 처리의 모의 테스트.
- **DONE:** EMA·RSI·Breakout 전략 snapshot/restore와 결정성 비교, process/DB/strategy/feed heartbeat, 선택적 모니터 인증, 제한적인 INFO 이벤트·snapshot retention.
- **PARTIAL:** DB Numeric(38,12)와 저장 직전 1e-8 round-half-even 양자화는 마련했지만 SQLite와 기존 Portfolio/Execution의 핵심 float 계산이 남아 있다. 정밀 Decimal 회계 완료 조건 미충족.
- **PARTIAL:** 92초 실제 공개 REST Paper 관측; 1/6/24시간은 실행하지 않았다. 실 WebSocket 최초 60초 시험에서 stale 중단 원인을 backlog로 특정하여 최신값 보존 루프로 수정. 재실행 97초 NORMAL, 가상 주문·체결 각 1, 실제 주문 0. 1/6/24시간 안정성은 미검증.
- **PARTIAL:** DB 대조 범위를 fee, realized PnL, fill count, 위험 기준, cursor까지 늘렸다. 외부 브로커 상태와의 독립적인 전면 원장 검증은 추가 시험이 필요하다.
- **ENVIRONMENT_LIMITATION:** Docker/PostgreSQL 서버 없음. Phase 5 private API/실제 주문은 미구현.

추가 실제 검증: 공개 WS Paper 프로세스 45초에 SIGKILL, TTL 전 재시작 거부,
TTL 후 72초 재시작 성공. token 1→2, 완료봉 2개 backfill, 주문·체결 각각
1건 유지, 현금·수수료·실현손익 불변, 실제 주문 0건.

## Phase 4.5-B 실제 변경 (현재 상태)

앞의 Phase 4/4.5 내용은 당시 구현 이력이다. 이번 변경으로 Portfolio/Position/Order/Fill/Execution/SimulationBroker/Risk의 금전·수량 회계를 Decimal로 통일했다. Market Data/연구 analytics의 float는 Decimal 경계 밖에 둔다. 원장 24자리 HALF_EVEN, 주문 수량 ROUND_DOWN, 가격 tick 매수 CEILING/매도 FLOOR, ORM SQLite TEXT/PG NUMERIC(65,24) 정책을 분리했다. Alembic `0003_exact_accounting`은 기존 값과 account.fill_count/order.fills_seen을 이관한다.

Paper 실행은 `recent_cache_limit`에 따라 주문/체결/거래/이벤트/snapshot 메모리를 제한하고 DB를 전체 이력으로 쓴다. 복구는 누적 counter와 최근 N개 + active order를 읽는다. DB와 in-memory 원장 reconciliation에서 cash/quantity/cost/fees/realized는 정확한 Decimal equality로 비교한다. 연구 백테스트는 전체 이벤트를 보존하며 결과 DataFrame에서만 float로 변환한다. lease 시계 역행 검출과 SQLite lock/쓰기 실패 시 Paper 중단 테스트를 추가했다. Soak runner JSON의 계측 항목을 확장했다.

시작 전 113개 테스트 통과. 새 가속 수치/DB/장애 시험과 전체 회귀 결과 및 82초 공개 Upbit WS Paper E2E는 `TEST_REPORT.md`에 기록한다. PostgreSQL 실서버와 1/6/24시간 실행은 완료 증거가 없다. Phase 5 기능은 구현하지 않았다.
