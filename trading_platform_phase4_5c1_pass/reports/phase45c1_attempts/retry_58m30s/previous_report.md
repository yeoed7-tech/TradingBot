# Phase 4.5-C1 — 1-Hour Real Public Paper Acceptance

**판정: ENVIRONMENT_LIMITATION. 1시간 Acceptance: NOT RUN.**

## 실행 이력과 증거 한계

| 시도 | 실제 확인 범위 | 결과 |
|---|---|---|
| 최초 Work 실행 | 약 2,820.48초 / 47분 | 실행 환경 초기화 후 DB·원시 계측·최종 감사 없음 |
| 재시도 1 | 60.039691592초 | FAILED: 초기 Public REST 조회가 writer lease TTL 30초를 넘김. heartbeat가 feed 시작 뒤에만 작동하던 결함 발견 |
| 수정 후 재시도 2 | 마지막 직접 확인 **3,510.207527254초 / 58분 30초** | 다음 요청에서 실행 환경 초기화와 파일 유실 확인. 3,600초 종료 결과 없음 |
| 복구 후 짧은 실제 공개 시험 | 약 92.005초 Paper / 약 100.019초 관측 wrapper | NORMAL, 독립 Decimal 대조·reconciliation PASS. **1시간 Acceptance 아님** |

58분 30초 이후 실제 종료 시각과 환경 초기화 원인은 확인하지 못했다. 휴대폰 앱 종료가 원인이라는 증거도 없다. 서로 다른 시도의 시간을 합산하지 않는다. `reports/phase45c1/runtime_metrics.csv`는 도구 응답에서 살아남은 **선별 표본 4개를 재기록**한 자료이며 연속 원본이 아니다. 이전 47분 자료는 `reports/phase45c1_attempts/initial_47m`에 보존했다.

## 58분 30초 재시도의 관측값

- 시작 관측: 2026-09-29 15:36:01 UTC (2026-09-30 00:36:01 KST).
- 마지막 관측: 2026-09-29 16:34:31.322048 UTC.
- 설정: `config/paper_upbit.toml`, EMA20/100, weight0.1, Upbit KRW-BTC (`BTC/KRW`), 1m, 가상 현금1,000,000KRW. 전략 변경 없음.
- writer owner: `23a86bec-b5d5-4abe-af88-9ec7333c59c6`, fencing token1. 마지막 heartbeat 갱신 확인.
- 첫 **30초 표본** RSS151,179,264B, 마지막 표본187,215,872B. 실제 시작/종료/max/RSS 전체 기울기는 **NOT RUN**: 원시 시계열과 최종 파일 유실.
- 마지막 DB 관측348,160B. OHLCV178 / signal59 / order0 / Fill0 / snapshot973 / system event1 / error event0.
- 마지막 관측 현금1,000,000KRW, 수수료·실현손익0. 거래가 없었으므로 이 구간으로 반복 Fill 회계를 실증했다고 주장하지 않는다.
- 최종 feed 합계·재연결·backfill·malformed 합계, 캐시 최대값, 최종 Decimal 원장·reconciliation·DB 무결성·network audit: **NOT RUN**.

## 필요한 최소 수정

1. lease 취득 직후 heartbeat를 시작해 공개 REST 초기 조회 중에도 갱신한다. `DurablePaperTrading.run`은 전달받은 heartbeat를 재사용한다. TTL을 임의로 늘리지 않았다.
2. heartbeat task가 이미 실패했어도 종료 보고서 저장 및 공개 transport 정리가 진행되도록 처리한다. 신규 주문 판단은 실패 상태에서 중단된다.
3. C1 wrapper의 `--config`를 child soak 명령에 전달한다.
4. 초기 REST 지연 및 heartbeat 실패 주입 시험2개 추가. 소스는 보관한 checkpoint에서 복구했다.

## 복구 후 실제 짧은 시험

명령:

```bash
.venv/bin/python -m scripts.phase45c1_accept --seconds 90 --sample-seconds 10 --database reports/phase45c1_recovery_smoke/paper.sqlite3 --out reports/phase45c1_recovery_smoke
```

| 항목 | 실제 값 | 상태 / 범위 |
|---|---|---|
| 사전 전체 회귀 | 126 passed, 1 warning in 28.11s | DONE |
| 사후 전체 회귀 | 126 passed, 1 warning in 28.86s | DONE |
| Paper 시간 | 92.005376초 | 짧은 시험만 DONE |
| RSS 시작/max/종료/차이 | 168185856 / 201658368 / 201658368 / 33472512B | 짧은 원시 측정 |
| RSS 전체/후반 slope | 676008194 / 11794579B/h | 초기화 포함; 장시간 안정성 판정에 사용하지 않음 |
| DB 시작/종료/증가 | 0 / 151552 / 151552B | DONE, 짧은 시험 |
| 정상 feed event | 20 | DONE |
| 실제 Public REST / WS message / WS 연결 | 4 / 583 / 1 | transport audit 기준 |
| reconnect / stale / gap / duplicate | 0 / 0 / 0 / 0 | 짧은 시험 범위 |
| 주문 / Fill | 0 / 0 | 자연 시장 결과, 설정 변경 없음 |
| 최근 cache | {"orders": 0, "fills": 0, "events": 163, "snapshots": 20, "trades": 0, "execution_events": 0, "risk_events": 0} | 전부 상한1000 이내 |
| Decimal 독립 원장·runtime/DB 대조 | PASS | cash1,000,000 / positions없음 / fees0 / realized0 정확 일치 |
| 최종 reconciliation / DB integrity | PASS / ok | DONE, 짧은 시험 |
| 중복 order/Fill/client ID/OHLCV key | 전부0 | DONE, 짧은 시험 |
| Private / 주문 / 취소 HTTP / 차단 시도 | 0 / 0 / 0 / 0 | DONE, 짧은 시험 |
| exceptions / reconciliation mismatch | 0 / 0 | DONE, 짧은 시험 |

`feed.metrics.rest_requests=20`은 feed에서 수행한 논리 조회 횟수이며 ccxt/cache 경계의 실제 HTTP4회와 구별한다. malformed/backfill 별도 누적 카운터는 현재 결과에 독립적으로 노출되지 않아 장시간 집계를 검증한 것으로 기록하지 않는다.

경고1개는 FastAPI TestClient/Starlette의 httpx 사용 deprecation이다. `--seconds`는 성공 시에도 wrapper가 NOT RUN과 exit1을 반환하도록 설계되어 있다. 원시 파일은 `reports/phase45c1_recovery_smoke`에 보존했다.

## 최종 gate

실제60분 종료, 전체 원시 계측, 최종 Decimal 대조·reconciliation·network audit를 확보하지 못했으므로 **C1 PASS가 아니다**. CODE GATE는126개 회귀로 유지된다. C2는 시작하지 않는다. Phase5는 NOT IMPLEMENTED. PostgreSQL은 docker/psql가 없어 ENVIRONMENT_LIMITATION이다.

## 지속 가능한 외부 호스트에서 재실행

프로젝트 루트에서 Python3.12+ 환경과 의존성 설치 후, 존재하지 않는 전용 DB 경로로 실행한다.

```bash
python -m pip install -r requirements.txt
python -m scripts.phase45c1_accept --config config/paper_upbit.toml --database reports/phase45c1_local/paper_1h.sqlite3 --out reports/phase45c1_local
```

API Key는 필요 없다. 한 명령이 사전/사후 regression, 실제1h 공개 WS Paper, 계측, 원장 대조, 네트워크 audit를 실행한다. 호스트의 절전·종료를 피하고 결과 JSON과 원시 CSV/DB를 보존한다. `soak_summary.json`의 PASS와 각 audit를 함께 확인한다. 실패하면 새 DB로 처음부터 다시 실행한다. C1 PASS 증거가 확보된 뒤 다음 작업은 **Phase4.5-C2 — 6-Hour Operational Acceptance**다.
