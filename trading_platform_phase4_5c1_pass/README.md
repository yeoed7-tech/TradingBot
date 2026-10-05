# 모듈형 자동투자매매 연구 플랫폼 v0.3 — Phase 4

**Paper Trading 운영 상태 저장·재시작 복구·읽기 전용 모니터링 구현. 실제 주문 API는 호출하지 않습니다.**

기존 백테스트에 공개 시세 전용 Upbit Adapter, Historical / Replay / Realtime Feed,
동일 회계·리스크·체결기를 사용하는 PaperTradingEngine을 추가했습니다.
실제 돈을 쓰는 경로, 거래소 주문 전송, Phase 4/5는 구현하지 않았습니다.

## 바로 확인할 문서

- `docs/IMPLEMENTATION_SUMMARY.md`: 기존 구조 점검과 구현/변경 범위
- `docs/TEST_REPORT.md`: 101개 테스트, 회귀 비교, 수정 후 실제 공개 API 성공 증거
- `docs/ARCHITECTURE.md`: 데이터 흐름, 주문 차단, 체결·장애 의미
- `docs/ROADMAP.md`: DONE / PARTIAL / NOT IMPLEMENTED 현황
- `docs/DATABASE.md`, `docs/RECOVERY.md`: DB와 강제 종료 후 복구 절차
- `docs/NEXT_STEPS.md`: 검증 제한과 기술부채

## 설치

Python 3.12 이상. 검증 환경 Python 3.12.14 / ccxt 4.5.84.

```bash
cd trading_platform
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m pytest -q
```

아래 명령은 프로젝트 루트에서 실행합니다. API Key/Secret이 필요하지 않습니다.
`.env`를 읽지 않으며 ccxt 클라이언트에 인증정보를 전달하는 설정도 없습니다.

## Paper Trading 실행

```bash
python -m trading_bot paper \
  --config config/paper_upbit.toml \
  --strategy ema_cross \
  --symbol BTC/KRW \
  --timeframe 1m \
  --duration 180 \
  --out reports/my_paper
```

기존 진입점 `python -m trading_bot.main paper ...`도 유지합니다.
`--duration`은 초 단위의 최대 관측 시간이며 기본 180초입니다.
전략이 HOLD를 내면 가상 주문이 없는 것이 정상입니다. EMA는 초기 120개 완료 봉으로 워밍업합니다.
실시간 데이터는 **REST polling**으로 받습니다. WebSocket은 사용하지 않습니다.
이번 실제 어댑터 범위는 **업비트 KRW 현물·실행당 한 종목**입니다.
기존 백테스트의 여러 종목 지원은 유지됩니다.

출력: `summary.json`, `config.json`, `orders.json`, `fills.json`, `snapshots.json`, `events.jsonl`.
평균 진입가는 진입 수수료를 포함한 원가 기준이며, 실현/미실현 PnL과 비용을 기록합니다.
이 파일들은 보고서이며, 재시작 복구의 기준은 설정한 DB입니다. 동일 DB·설정으로 다시 실행하면 확정 상태를 복원합니다.

## 공개 API 통합 검증 재실행

```bash
python -m scripts.public_integration \
  --duration 150 \
  --out reports/public_integration_retry
```

이 명령은 배관 검증용 DiagnosticCycle을 사용합니다. 초기 완료 봉들을 처리한 뒤 가상 매수 목표,
다음 완료 봉에는 가상 청산 목표를 내므로 전략의 시장 조건을 기다릴 필요가 없습니다.
**투자전략 검증이나 수익성 평가가 아닙니다.** 유동성·최소금액·리스크에 의해 미체결될 수 있습니다.
실제 가격·호가를 얻지 못하면 실패(exit 1), 정상 이벤트 2개 이상·완료 봉·가상 체결·정상 최종 상태를
확인하면 성공합니다. 각 조건과 결과는 summary.json에 기록합니다.

수정 후 결과는 `reports/phase3/public_integration_fixed/summary.json`입니다.
공개 API 54/54 성공, 정상 이벤트 48건, 가상 주문 2건·체결 3건, 실제 주문 호출 0건입니다.
원인은 서버 CCXT 클라이언트의 환경 프록시·시스템 CA 미반영이었으며 휴대폰 설정 문제가 아닙니다.
TLS 검증을 유지한 수정과 로컬 재현 방법은 `docs/NETWORK_FIX.md`에 설명합니다.
독립 REST/WebSocket 진단 도구는 `tools/upbit_connection_diagnostics.zip`에 동봉했습니다.
이전 실패 기록도 보존했습니다. 3분 검증은 장시간 운영·수익성 검증을 뜻하지 않습니다.

## 설정

`config/paper_upbit.toml`의 `[paper_trading]`:

| 설정 | 의미 |
|---|---|
| exchange / symbol / timeframe | upbit, BTC/KRW, 1m 등 |
| starting_cash | 가상 초기 현금, KRW |
| fee_rate / slippage_bps | 가상 수수료와 스프레드 외 추가 슬리피지 |
| network_trust_env / ca_bundle_path | 환경 프록시 사용 여부 / 선택적 신뢰 CA 파일; 기본 시스템 CA |
| poll_interval / request_timeout | 조회 주기 / 요청별 최대 대기 초 |
| quote_max_age | 거래소 호가 timestamp의 최대 허용 나이 |
| stale_data_timeout | 마지막 완료 봉의 종료 시점 이후 허용 초 |
| clock_skew_tolerance | 거래소 시각이 로컬보다 앞설 수 있는 허용 초 |
| warmup_bars / page_size / max_pages | 초기 봉 수 / 페이지 크기 / 최대 페이지 수 |
| max_gap_bars | 자동 복구 가능한 누락 기간 상한 |
| max_book_participation | 관측된 최우선 호가 수량 중 가상 체결 상한 |
| reconnect.* | 요청 재시도, 지수 backoff, 연속 실패 종료 기준 |
| market_rules.* | 최소금액·최소수량·수량 step·가격 구간별 tick |

가상 수수료 0.0005는 설정한 **시뮬레이션 가정**이며 계정별 실제 수수료를 조회한 결과가 아닙니다.
가격 구간별 tick과 최소금액은 공식 공개 문서를 확인한 정책 스냅샷입니다.
ccxt public metadata에는 계좌별 최소금액이 없으므로 그 값을 조회했다고 주장하지 않습니다.
호가 정책이 바뀌면 설정과 검증을 갱신해야 합니다.

전략 파라미터는 기존 `[strategy.params]`, 위험한도는 기존 `[risk]`를 그대로 사용합니다.
paper의 현금·수수료·슬리피지는 `[paper_trading]` 값이 core settings에 반영됩니다.
`execution.delay_bars=1`은 신호를 만든 이후 처음 관측한 새로운 호가부터 체결 가능하다는 뜻입니다.
2 이상은 추가 완료 봉을 기다립니다. 만료도 완료 봉 개수로 계산합니다.

## Phase 4 데이터베이스·모니터링

`config/paper_upbit.toml`에는 `[persistence] enabled = true`와 SQLite URL이 있다.
프로젝트 루트에서 실행하면 DB migration을 적용하고, 중단된 Paper 계정의 Cash/Position/Risk/Order/Cursor를
복원한 후 누락 봉을 조회한다. 다른 전략 코드·전략/리스크 설정이면 동일 계정을 조용히 이어서 사용하지 않는다.

```bash
python -m trading_bot paper --config config/paper_upbit.toml --duration 180 --out reports/paper_run
python -m trading_bot monitor --config config/paper_upbit.toml --host 127.0.0.1 --port 8000
```

별도 터미널의 브라우저에서 `http://127.0.0.1:8000/`로 읽기 전용 Dashboard를 확인한다.
`/health`, `/status`, `/portfolio`, `/positions`, `/orders`, `/fills`, `/strategies`, `/risk`, `/events`도 제공한다.
monitor는 DB만 읽고 거래 엔진을 받지 않는다. 기본 호스트 localhost를 유지한다.

Mismatch latch가 걸린 경우 `python -m scripts.reconcile_paper --config config/paper_upbit.toml`로 상태를 읽고
`docs/RECOVERY.md`의 확인 절차를 따른다. `--resolve`는 검토 후 Paper 전용 DB/브로커 비교를 실행한다.
설정, migration 및 로컬 PostgreSQL 검증 절차는 `docs/DATABASE.md`에 있다.

이번 Work에서는 SQLite와 강제 종료/재시작/실제 공개 REST E2E, 전체 101개 테스트를 확인했다.
PostgreSQL 실서버 검증은 Docker 부재로 **ENVIRONMENT_LIMITATION**이다.

## 기존 백테스트와 전략 추가

```bash
python -m trading_bot demo --out reports/demo_new
python -m trading_bot backtest --data my_ohlcv.csv --config config/default.toml --out reports/backtest
python -m trading_bot compare --data my_ohlcv.csv --out reports/comparison
python -m trading_bot walk-forward --data my_ohlcv.csv --out reports/walk_forward
```

CSV 스키마는 `timestamp,symbol,open,high,low,close,volume`입니다.
UTC 봉 시작 시각, 기초자산 수량 volume, 동일 표시통화를 사용합니다.
상세 백테스트·지표 정의는 `docs/PHASE1_2_README.md`의 연구 기능 부분을 참조하세요.
그 파일의 **Phase 3 미구현 문구는 이전 릴리스 기록**이며 현재 상태는 이 README와 ROADMAP이 우선합니다.

전략은 기존 `Strategy.on_data(bars) -> list[Signal]`을 구현하면 됩니다.
목표비중 0은 SELL, 양수는 목표 배분, None은 HOLD입니다.
`name="trading_bot.strategies.custom_strategy:CustomStrategy"`로 신뢰하는 로컬 플러그인을 선택할 수 있습니다.
전략은 거래소나 실행 모드를 알 필요가 없습니다.

## 제한과 안전

- Paper Engine에 거래소 객체를 주입하지 않습니다. feed가 전달한 데이터만 소비합니다.
- Public Adapter에는 create_order/cancel_order가 없습니다.
- 하부 ccxt transport는 지정한 공개 GET 경로만 허용합니다. private·주문·Authorization 전송은 거부합니다.
- balance/positions/orders/fills 인증 계약은 별도 UnavailableAccountAccess로 명시적으로 거부합니다.
- 연결 끊김·stale·gap에서는 모든 대기 가상 주문을 취소합니다. 과거 봉 backfill에서 소급 체결하지 않습니다.
- 반복 실패/비정상 데이터는 위험 정지를 유지합니다. 자동 재활성화하지 않습니다.
- 업비트에서 무거래 구간의 봉이 없는 경우도 GAP으로 중지합니다. 가짜 봉을 만들지 않습니다.
- 전략 주문은 현재 ask/bid, 추가 슬리피지, 보수적인 tick 반올림으로 가상 체결합니다.
- 동일 호가 timestamp는 유동성 재충전으로 보지 않습니다. 새 timestamp마다 최우선 수량을 다시 관측하며 큐·실거래 체결확률은 모델링하지 않습니다.
- UTC 기준 일/주 리스크, 현물 매수만 지원합니다. ATR 위험예산은 확정 손절 보장이 아닙니다.
- `python -m trading_bot live`는 계속 거부됩니다. 환경변수로 활성화할 수 없습니다.

## Docker

기존 Dockerfile을 업데이트된 requirements와 함께 사용할 수 있습니다.
기본 compose의 `network_mode: none`은 오프라인 연구용입니다.
공개 데이터 paper 전용 구성은 아래처럼 실행합니다.

```bash
docker compose -f docker-compose.paper.yml build
docker compose -f docker-compose.paper.yml run --rm paper
```

Paper 컨테이너에는 공개 인터넷 접근이 필요합니다. 자격증명을 마운트하지 않습니다.
Paper compose는 `paper_db` named volume으로 SQLite를 컨테이너 재시작 후에도 보관합니다.
이번 환경에는 Docker 실행 파일이 없으므로 컨테이너 빌드/실행은 미검증입니다.

## Phase 4.5 Paper 운영 실험

운영 예제 `config/paper_upbit.toml`은 공개 Upbit WebSocket 호가와 REST 완료봉을
사용하며, DB lease/fencing으로 같은 계좌의 두 번째 writer를 차단합니다.
`python -m scripts.soak_paper --hours 1 --database data/database/soak.sqlite3`
로 제한된 공개 시세 Paper soak을 실행하고 `docs/SOAK_TEST.md`를 참조하세요.
계좌 인증·실제 주문 API는 제공되지 않습니다. 이번 단계의 완료 조건 중 핵심 Decimal 회계와
1/6/24시간 검증은 남아 있어 Phase 4.5 전체는 PARTIAL입니다.

### Phase 4.5-B Decimal / bounded Paper

Paper 회계는 Decimal 24자리 내부 원장, ORM 0003 migration, `persistence.recent_cache_limit` 최근 메모리 캐시를 쓴다. 전체 주문/Fill은 DB에 남고 Backtest 연구 이력은 그대로 유지된다. `docs/PRE_LIVE_GATE.md`에서 코드 검증·장시간 Paper·PostgreSQL 진입 조건을 구분한다. 이 단계는 공개 시세의 가상 주문만 사용한다.
