# Phase 4 재시작·복구 운영 절차

Paper 전용이다. API Key나 거래소 실제 주문 메서드를 사용하지 않는다.

1. 동일 config, strategy class/version, DB URL 및 account로 `python -m trading_bot paper --config config/paper_upbit.toml --duration 180 --out reports/restart`를 실행한다.
2. 시작 시 DB에서 Account, Position, Fill, Order, Risk, kill, Market Cursor를 복원한다.
   전략 상태는 DB에 저장한 완료 OHLCV를 순서대로 재생해 다시 계산한다. 전략/리스크 설정 SHA-256 또는
   전략 클래스 identity가 바뀌면 기존 계좌를 조용히 이어서 돌리지 않고 멈춘다.
3. 확정된 cursor 다음 시각부터 REST Feed가 누락 봉을 조회한다. 연속 봉이 채워지지 않으면 GAP이고
   신규 거래를 하지 않는다. backfill 후 새 정상 호가에서만 판단한다. 과거 봉에는 소급 체결하지 않는다.
4. 미확정 CREATED Paper Intent는 상태 제공자가 검사한 후 CANCELLED로 기록한다. UNKNOWN은 자동
   재송신하지 않는다. 같은 Fill ID는 중복 적용되지 않는다.
5. 브로커 메모리와 DB의 현금·포지션·주문·kill 상태가 다르면 `RECONCILIATION_REQUIRED`를 DB에 고정하고
   신규 주문을 중지한다. 재시작만으로 해제되지 않는다.
6. 원인을 확인한 뒤 `python -m scripts.reconcile_paper --config config/paper_upbit.toml`로 상태를 조회한다.
   Paper DB 상태를 신뢰할 수 있고 위험/주문 상황을 검토했다면 같은 명령에 `--resolve`를 붙여 별도
   복구 엔진의 비교 검증을 수행한다. 일치할 때만 latch가 PAUSED로 바뀐다. 이후 Paper를 재시작하여
   cursor backfill을 먼저 수행한다. 이는 Paper 전용이며 실제 거래소 정산 절차가 아니다.

| 강제 종료 위치 | 테스트한 재시작 결과 |
|---|---|
| 주문 의도 직후 | Intent 존재, status 조회 → Paper 미시뮬레이션 CANCELLED; 중복 전송 없음 |
| checkpoint의 주문 상태 flush 후 | Intent만 확정, 봉/체결/계좌 롤백; 재조회·replay |
| Fill flush 후, Position 전 | Fill/Position/Account/checkpoint 전체 롤백; replay 1회 |
| Portfolio flush 후, commit 전 | 동일 트랜잭션 전체 롤백; replay 1회 |
| kill switch 확정 직후 | kill과 cursor 복원; 신규 BUY 거부 |

`tests/test_phase4_persistence.py`는 별도 자식 프로세스에서 `os._exit`으로 위 지점을 실제 종료시킨다.
예외 주입 테스트도 transaction rollback을 별도로 검사한다. 재시작 직후 저장된 cash/position/fee/PnL과
확정 cursor를 확인하고 동일 이벤트를 재생하여 중복 효과가 없음을 검증한다.

기존 전략 외의 플러그인은 완료봉 재생이 결정적이고 외부 부작용이 없어야 한다. 임의의 외부 상태를 가진
플러그인의 재시작 동일성은 자동 보장하지 않는다. DB 파일 유실/손상, host 장애, 복수 프로세스 동시 writer,
장시간 운영 및 실제 네트워크 회선 절단 시험은 별도 운영 검증이 필요하다.

## Phase 4.5 lease와 WebSocket 복구

운영 설정에서 `single_writer=true`가 필수다. 시작 시 DB lease를 획득하고 같은 계좌의
다른 owner가 살아 있으면 실패한다. 새 owner는 TTL 만료 뒤에만 token을 증가시켜 진입한다.
이전 프로세스가 살아나더라도 주문 intent·checkpoint 첫 UPDATE에서 token 불일치를 검출한다.
재시작은 DB 계좌·위험·cursor·전략 snapshot을 복원하고, REST로 완료 봉을 backfill한 뒤
새로운 WebSocket 호가가 확인될 때만 NORMAL로 진행한다. websocket disconnect/timeout은
미체결 주문 취소 및 신규 거래 중지로 이어진다.

운영자는 `/health`의 `lease_active`, heartbeat, Feed 상태를 확인한다. 차이가 있으면
`RECONCILIATION_REQUIRED` latch가 유지된다. DB 복구/lease 강제 변경을 수동으로 하기 전에
프로세스가 실제로 종료됐는지 확인해야 한다. 시계가 크게 도약하거나 DB 연결이 실패하면
갱신/쓰기 거부로 신규 거래를 중단한다. 같은 호스트의 실제 Paper 프로세스 SIGKILL→TTL 만료→REST backfill→WebSocket 재진입은
아래와 같이 검증했다. 다른 호스트/DB 장애 전환은 미검증이다.

실제 Public WS crash recovery도 시험했다: `SIGKILL` exit 137 후 새 프로세스는
lease 유효 기간 동안 LeaseLost, TTL 뒤 token 1→2로 인계했다. cursor `16:18`에서
`16:20`으로 backfill하면서 주문·체결 DB 건수 1건, 현금·수수료·실현손익이 동일했다.
시험 명령과 값은 `TEST_REPORT.md`에 기록했다. 이 시험은 같은 호스트·SQLite의
단일 장애이며 PostgreSQL/network partition/장시간 분산 장애를 대신하지 않는다.

## Phase 4.5-B 복구 점검

0003 DB에서 account의 Decimal cash/누적 PnL/fees/fill_count, position의 quantity/cost와 최근 order/fill 최대 `recent_cache_limit`건, active order, risk와 cursor를 복원한다. 총 건수는 목록 길이가 아닌 DB counter이며, 중복 Fill ID는 무시된다. `reconciler.check()`는 회계 값에 float 허용 오차를 사용하지 않는다. 1e-24 단위 불일치도 `RECONCILIATION_REQUIRED`로 신규 결정을 중지한다.

SQLite BEGIN IMMEDIATE write lock에서 checkpoint/intent가 실패하면 Paper coordinator는 blocked 상태가 된다. 디스크 쓰기 예외도 같은 방식으로 멈추며, 미확정 in-memory engine을 계속 쓰지 않는다. 다음 실행에서 **마지막 DB commit cursor** 이후의 REST backfill과 새로운 WebSocket 호가를 거친다. 장애 중 불확실한 주문 상태는 검사하며 재전송하지 않는다. 벽시계 역행은 lease 호출에서 `LeaseLost`를 발생시키고 큰 정방향 도약은 만료 검사에서 막는다. 멀티호스트 clock skew, DB 유실/손상 및 실제 디스크 full은 추가 운영 검증 대상이다.

## 초기 연결 구간 writer heartbeat

lease 취득 직후부터 공개REST metadata/ticker 및 history 준비 중 heartbeat를 갱신한다. `DurablePaperTrading.run(..., heartbeat_task=...)`는 외부task를 재사용하며 task소유자가 종료한다. 실패task의 exception도 runner최종보고서로 남기고 공개연결을 정리한다. lease TTL을 늘려 우회하지 않는다. 느린REST와 heartbeat실패 자동시험이126개 전체회귀에 포함된다. Work reset후 유실된 DB를 일부표본으로 복구했다고 간주하지 않는다.

## C1 자연운전 결과

새실제1시간은정상종료했고lease반납후owner빈값/token1을확인했다. Feed cursor/risk/account/open orders종료reconciliationPASS. 이번실운전에는disconnect/stale/gap이없어자연장애복구시간은NOT RUN이다. 기존crash/reconnect/fencing자동시험은전체126개에포함돼통과했다. C1결과로실제장시간chaos복구까지완료했다고확대하지않는다.
