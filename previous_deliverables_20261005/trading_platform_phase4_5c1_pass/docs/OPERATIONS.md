# Phase 4.5 Paper 운영

- 설치: `python -m pip install -r requirements.txt`; migration: `alembic upgrade head`.
- 시작: `python -m trading_bot paper --config config/paper_upbit.toml` (기존 CLI 도움말 참조).
- 기본 시세: Upbit Public WebSocket orderbook; REST는 OHLCV·복구. 네트워크가 WebSocket을
  막으면 `quote_source = "rest"`로 공개 REST Paper 관측이 가능하나 WebSocket 검증 완료가 아니다.
- 같은 DB/account에 두 프로세스를 띄우지 않는다. 운영 runner는 `single_writer=true`가
  아니면 시작을 거부한다. TTL을 지나치게 짧게 잡으면 느린 DB에서 정상 owner도 만료된다.
- 모니터 기본 bind `127.0.0.1`; 공개 인터넷으로 열지 않는다. 필요하면 프로세스 환경변수
  `PAPER_MONITOR_TOKEN`을 설정하고 요청 헤더 `x-monitor-token`을 전달한다. 비밀값은 파일에 쓰지 않는다.
- `/health`에서 application/database/market_feed/broker/strategy/risk_engine 및 heartbeat를
  살핀다. `DEGRADED`, `HALTED`, `RECONCILIATION_REQUIRED`면 주문 재개 전에 원인을 해결한다.
- `python -m scripts.benchmark_feed`는 1/10/50 자산 전략 dispatch만 측정한다.
- INFO 이벤트/스냅샷 정리는 `trading_bot.persistence.retention.prune`을 운영자가 별도
  실행할 때만 수행한다. 주문, 체결, OHLCV, 위험, 회계 원장은 삭제하지 않는다.
- 실제 거래소 인증, 계좌 조회, 주문·취소 API는 코드에 없다.

### 강제 종료 복구 검증

테스트 전용 새 DB로 `timeout -s KILL 45s python -m scripts.soak_paper --seconds 90
--database /tmp/paper_crash.sqlite3 --out reports/crash_before`를 실행한다.
즉시 두 번째 trader는 lease 때문에 거부되어야 한다. 기본 TTL 30초 만료 뒤
같은 DB로 `python -m scripts.soak_paper --seconds 70 --database
/tmp/paper_crash.sqlite3 --out reports/crash_after`를 실행한다.
재시작 전후 `orders`, `fills`, `accounts`, `market_cursors`, `risk_state`와
`trader_leases.fencing_token`을 비교한다. `timeout` 명령이 없는 OS는 별도
자식 프로세스에 SIGKILL을 보내 동일하게 시험한다. 실제 주문은 발생하지 않는다.

## Phase 4.5-B 운영 값

`config/paper_upbit.toml`의 `[persistence] recent_cache_limit = 1000`은 Paper에서 최근 주문/체결/거래/위험 이벤트/journal/snapshot의 메모리 상한이다. 원장 전체 이력은 DB에서 조회한다. 설정 변경은 전략/risk 해시를 바꾸지 않으므로 동일 DB 재시작 시 최근 복원 길이만 달라진다. 오랫동안 운용할 때 DB 파일과 로그 용량을 별도로 감시하고 `retention.prune()`은 감사 정보 보존 범위를 확인한 뒤 별도 작업으로 실행한다.

시계가 역행하거나 lease 만료, SQLite 잠금, checkpoint 쓰기 실패가 발생하면 신규 거래가 중단된다. 운영자는 상태를 확인하고 마지막 DB commit 이후 REST gap 복구와 공개 WebSocket freshness 확인을 거쳐 재시작한다. `RECONCILIATION_REQUIRED`가 있으면 확인 없이 해제하지 않는다. 장시간 실행은 `SOAK_TEST.md` 명령을 사용한다. API Key/실제 주문은 사용하지 않는다.

## C1 운영 Acceptance

`python -m scripts.phase45c1_accept --database reports/phase45c1_retry/paper_1h.sqlite3 --out reports/phase45c1_retry`를 안정적으로 1시간 이상 유지되는 호스트에서 실행한다. 이전 DB를 재사용하면 시작 전에 거부한다. `soak_summary.json`의 elapsed >= 3600, 회귀 전후, RSS 후반 기울기, bounded cache, Decimal 회계, reconciliation, `network_audit.json`의 Private/주문/취소 0을 함께 확인한다. Work 내 47분 시도는 완료 증거가 아니다. 오류가 생기면 새 DB로 처음부터 다시 시작한다.

## C1 실행환경 제한 (2026-09-30)

Work 재시도58분30초 표본 이후 프로세스/원시 DB가 다음 continuation에서 사라졌다. 정확한 reset 시각/원인은 미확인이다. 앱종료·휴대폰설정 문제로 단정하지 않는다. 초기public REST에서도 writer lease heartbeat가 유지되도록 수정했다. heartbeat실패는 보고서저장/공개transport정리 후 안전정지한다. 지속적인 로컬/VM에서 새DB로 C1을 실행하고 PASS 원시증거를 보존한다. C2/24h/Phase5 자동실행은 하지 않는다.

## C1 완료와 실행경로

2026-09-30 C1은PASS다. 제한된sandbox의FastAPI TestClient는최소앱에서도멈추므로환경제한과앱오류를구분한다. 승인된실행경로에서기존소스/전략그대로126개전후회귀와실제1hPublic WS Paper를완료했다.

## C2 6시간 Acceptance (2026-10-03)

새 DB의 Public WS Paper 21,602.016초 실행이 정상 종료했다. 표본720개, 가상주문/체결2/2, reconnect/gap/stale/duplicate 및 private/real order/cancel HTTP는0. 독립 Decimal 원장·reconciliation·SQLite integrity PASS, lease 반납 완료. Windows 전체 회귀에서는 `fork` 미지원 테스트 2건이 환경 비호환으로 실패했고 나머지124건은통과했다. RSS는Windows에서계측되지않았다. 세부 `PHASE_4_5_C2_REPORT.md`; 다음은별도 새DB 24h Paper다.
