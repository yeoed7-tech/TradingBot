# Phase 4 데이터베이스

SQLAlchemy 2.x ORM(`trading_bot/persistence/models.py`)과 Alembic revision `0001`을 사용한다.
개발 기본값은 `sqlite:///data/database/paper.sqlite3`이다. URL을 `postgresql+psycopg://...`로
바꾸어도 같은 모델·저장 계층을 사용한다. 이 환경에는 Docker가 없어 PostgreSQL 실서버 검증은
`ENVIRONMENT_LIMITATION`으로 남겼다. 계정/실거래 API는 연결하지 않는다.

## 테이블과 제약

| 테이블 | 내용 / 중복 키 |
|---|---|
| ohlcv | exchange, symbol, timeframe, timestamp 복합 unique |
| signals | 시각, 전략, run id, BUY/SELL/HOLD, 목표비중, 메타데이터, mode |
| orders | 내부 ID primary key, client_order_id unique, 상태와 수량·시각 |
| fills | exchange_fill_id primary key, 주문 FK, 가격·수량·비용·실현 PnL |
| accounts | 계정별 현금, 초기현금, 누적 실현 PnL/수수료 |
| positions | account + symbol primary key, 수량/원가/평균 진입가/실현 손익 |
| portfolio_snapshots | 현금/시장가치/자산/손익/수수료/낙폭 |
| risk_state | kill, 일·주 기준 자산, peak, 손실, 연속 손실, ATR/이전 종가 |
| market_cursors | 거래소/종목/시간봉별 확정 봉과 quote 시각, engine index |
| strategy_runs | 버전·설정·전략+리스크 canonical SHA-256·mode·상태 |
| system_events | 시각·severity·component·event·message·redacted context |

주문 의도는 `ExecutionEngine.submit`의 durable hook을 통해 **SimulationBroker가 체결하기 전에**
독립 트랜잭션으로 기록된다. 동일 client_order_id는 같은 의도를 반환하며 다른 내용은 거부한다.
프로세스 종료로 CREATED 의도가 남으면 Paper 전용 status provider가 `CREATED`를 검사하고
미시뮬레이션 의도를 CANCELLED로 기록한다. UNKNOWN 상태는 자동 해제하지 않는다.
향후 Live의 상태 조회 인터페이스는 이 경계 뒤에 연결해야 하며 이번 코드에는 실제 주문 메서드가 없다.

체결 API `PaperLedger.apply_fill()`은 Fill ID 존재 확인 → 기존 Portfolio 회계 적용 → Fill 저장 →
Account/Position/Snapshot 갱신을 **한 DB 트랜잭션**에 넣는다. rollback 지점 주입과 동일 Fill 재전달을
검증했다. Paper 실행 이벤트도 주문 상태·신호·봉·새 Fill·계좌·Position·Risk·Cursor를 한 checkpoint
트랜잭션에서 확정한다. 이벤트 처리 중 메모리 상태와 DB가 다르면 현재 프로세스는 중단하고,
재시작 시 DB에서 재구축한다. 별도로 확정된 Order Intent는 삭제하지 않고 상태 확인한다.

기존 Portfolio는 float 회계다. 장시간 운영/엄밀한 원화 소수점 회계를 위해 Decimal 전환과
병렬 writer/transaction 격리는 후속 검증이 필요하다. SQLite는 단일 writer 운영을 전제로 한다.

## 설치·Migration

프로젝트 루트에서:

```bash
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m alembic current
```

Alembic 실행 전 SQLite 파일의 부모 디렉터리 `data/database`를 만든다. Paper CLI는 시작 시 이를 생성하고
`migrate()`를 수행한다. Migration은 빈 개발 DB와 테스트 DB에서 upgrade/downgrade/upgrade를 검증했다.
기존 DB의 백업·이전 릴리스 데이터 import는 제공하지 않는다.

## 로컬 PostgreSQL 검증

```bash
docker compose -f docker-compose.postgres.yml up -d --wait
PAPER_TEST_DATABASE_URL='postgresql+psycopg://paper:local_test_only@127.0.0.1:55432/paper_test' \
  python -m scripts.verify_postgres
docker compose -f docker-compose.postgres.yml down
```

스크립트는 localhost의 `paper_test` DB만 허용한다. migration, 주문 멱등성, 체결 accounting을 확인한다.
현재 Work 실행 환경에 Docker 명령이 없어 실제 PostgreSQL 실행 결과는 없다.

## 0002_decimal_accounting 및 운영 테이블

`alembic upgrade head`는 0001의 account/position/order/fill/snapshot 숫자 컬럼을
`Numeric(38,12)`로 변경하고 `trader_leases`, `heartbeats`를 생성한다.
SQLite batch migration은 기존 데이터를 복사하며 downgrade는 Float로 돌아간다.
테스트에서 12.345 기존 현금 값을 upgrade/downgrade/upgrade 동안 보존했다.
저장 직전 금액·수량을 1e-8 단위 HALF_EVEN으로 양자화하지만 SQLite NUMERIC 저장 방식과 현재 ORM의 `asdecimal=False` 때문에 애플리케이션 회계는
아직 Decimal이 아니다. 0002는 최종 회계 정밀도의 충분조건이 아니다.

lease는 계좌를 PK로 공유하고, 토큰을 재사용하지 않는다. 주문/체결/위험/cursor와
같은 DB transaction의 시작에서 fencing 조건을 확인한다. 오래된 INFO system event와
오래된 portfolio snapshot만 명시적인 `retention.prune()`에서 삭제한다. 마지막 snapshot,
WARNING/ERROR/CRITICAL, 주문·체결·회계 원장·OHLCV는 보존한다.
PostgreSQL 실서버: **ENVIRONMENT_LIMITATION**; Docker 절차는 위 명령을 따른다.

## 0003_exact_accounting — Phase 4.5-B

`0001 → 0002_decimal_accounting → 0003_exact_accounting` 순서다. Account/Position/Order/Fill/Snapshot의 금액·수량과 risk_state의 peak/day/week/last equity는 ORM `Mapped[Decimal]` 및 `ExactDecimal(Numeric(65,24,asdecimal=True))`이다. SQLite의 NUMERIC affinity는 binary float를 경유할 수 있어 실제 저장 타입은 TEXT(Decimal 정규 문자열)로 정한다. DB 값 때문에 추가 양자화하지 않는다. Market OHLCV와 통계 비율은 별도로 Float다.

0003은 accounts.fill_count, orders.fills_seen을 추가하고 기존 fills에서 backfill한다. 이전 0002 데이터는 최대 그 당시에 저장된 유효 숫자만 보존된다. 이미 Float/SQLite NUMERIC에서 잃은 하위 자릿수를 복원하지는 못한다. SQLite `0002 → 0003 → 0002 → 0003` 값을 보존하는 시험을 실행했다. **Migration 전 DB 백업**을 권장한다. 0003 이후 새로 만들어진 12자리 초과 정밀도 값은 0002로 downgrade할 때 손실될 수 있으므로 운영 자료가 있는 DB에서 downgrade하지 않는다.

전역 order/fill 기본키와 unique constraint가 durable 중복 차단이다. Account의 누적 합계와 Fill ID 추가는 동일 트랜잭션에서 확정한다. ORM 복구는 최근 N건을 역순 조회해 메모리에 채우며 누적 건수는 DB counters를 읽는다. `retention.prune()`은 INFO 이벤트/오래된 redundant snapshots만 제거한다. 주문·체결·계좌·위험·cursor·OHLCV는 삭제하지 않는다.

실서버 PostgreSQL은 이 환경에서 실행하지 못했다(**ENVIRONMENT_LIMITATION**). `docker compose -f docker-compose.postgres.yml up -d --wait` 후 `PAPER_TEST_DATABASE_URL='postgresql+psycopg://paper:local_test_only@127.0.0.1:55432/paper_test' python -m scripts.verify_postgres`로 0003, Decimal fee, rollback, 중복, fencing을 검증한다.

## C1 증거 보존

이번 최소수정에는 schema/migration변경이 없다. 58분30초 Work DB가 유실되어 최종원장대조는NOT RUN이다. 복구 후 짧은92초 새SQLite DB에서 독립Decimal 원장대조, risk/cursor/open orders reconciliation 및 integrity검증은PASS였다. `reports/phase45c1_recovery_smoke/paper.sqlite3`를 원시증거로 보존한다. 주문/Fill0인 시험은 반복체결 실증이 아니며 기존자동회귀에서 해당효과를 검증한다. PostgreSQL실서버는ENVIRONMENT_LIMITATION.

## C1 실제1시간 DB 증거

최신 `reports/phase45c1/paper_1h.sqlite3`는정상종료후DB다. Orders2/Fill10/Positionrow1(qty0,cost0)/OHLCV180/Signal61/Snapshot1178/SystemEvent2. integrityok, client/internal order/fill/OHLCV키중복0, 독립Decimal원장PASS. schema/migration변경은없다. 이전유실DB자료와합산하지않았다. PostgreSQL별도ENVIRONMENT_LIMITATION.
