# Pre-Live Gate — Phase 4.5-B

현재 범위는 **공개 시세 Paper Trading**이다. Phase 5 private 인증·주문 코드는 없다. 상태는 실제 실행 증거에 한정한다.

## CODE GATE

| 항목 | 상태 | 증거 / 범위 |
|---|---|---|
| Decimal 주문·체결·원가·현금·PnL·위험 기준 자산 | DONE | `precision.py`, `Portfolio`, `ExecutionEngine`, `RiskEngine`, ORM `ExactDecimal`; float는 Market Data/분석 비율 경계에 한정 |
| 0001→0002→0003 / 0003→0002 SQLite 기존 값 보존 | DONE | `test_migration_0002_to_0003_and_back_preserves_existing_sqlite_values` |
| 부분체결·반복거래·전량청산·fee invariant | DONE | 12,000건 인메모리 회계 체결, 2,000건 SQLite 원장 체결 정확한 Decimal equality |
| Fill ID exactly once·transaction rollback·재시작 | DONE | 기존 113개 회귀와 신규 테스트; DB 2,000건 후 최근 100건만 복원 |
| Reconciliation 정확한 원장 비교 | DONE | 1e-24 KRW 차이도 불일치로 거부; quote/성과 비율은 별도 |
| Paper 주문·체결·이벤트·snapshot bounded cache | DONE | 설정 `persistence.recent_cache_limit`, 100,000 market-event 가속 테스트 및 2,000건 durable restore |
| Research full history 유지 / 전체 regression | DONE | 최종 `python -m pytest -q` 결과는 `TEST_REPORT.md` 참조 |
| SQLite 실제 lock, write failure, clock anomaly fail closed | DONE | 신규 시험에서 신규 결정 정지, cursor/계좌 미확정 상태 확인; 단일 호스트 범위 |
| private/order API 미호출 | DONE | 공개 전용 어댑터 구조 및 82초 실측 audit의 주문 HTTP 0 |

## OPERATIONAL GATE

| 항목 | 상태 | 증거 / 범위 |
|---|---|---|
| Decimal 변경 후 실제 Upbit Public WS Paper 짧은 E2E | DONE | 82.00초, NORMAL 17건, 가상 주문·체결 1건씩, 공개 REST 4회 성공, 실제 주문 HTTP 0 |
| 1시간 Paper | DONE | 2026-09-30 새 단일 실행: Paper3600.276초, soak3602.007초, 전후126개 회귀, Decimal/reconciliationPASS, Private/주문/취소0. `PHASE_4_5_C1_REPORT.md`와 원시DB/CSV 참조 |
| 6시간 Paper | DONE / PASS | 2026-10-03, 21,602.016초/720 표본, 독립 Decimal 대사·reconciliation·SQLite integrity PASS, private/주문/cancel HTTP 0. 세부 `PHASE_4_5_C2_REPORT.md` |
| 24시간 Paper | NOT RUN | `--hours 24`; 별도 DB/출력 디렉터리 사용 |
| 며칠간 memory/DB/log slope·실연결 장애·재시작 | PARTIAL | C1/C2 완료, C2에서 DB 약 279 KB/h·log +201 B 확인. RSS는 Windows에서 계측 불가, 24시간·며칠 실행 및 실연결 chaos는 미검증 |

## ENVIRONMENT GATE

| 항목 | 상태 | 증거 / 범위 |
|---|---|---|
| PostgreSQL 실서버 migration/Decimal/rollback/fencing | ENVIRONMENT_LIMITATION | 이 Work 환경에 Docker/psql 없음; `docker compose -f docker-compose.postgres.yml up -d --wait` 후 `python -m scripts.verify_postgres` 실행 |
| 외부 네트워크 분리·disk full·멀티호스트 clock skew | NOT RUN | 현재는 SQLite lock·mock write failure·로컬 시계 역행/도약만 자동 검증 |

다음 단계는 **Phase 4.5-C Operational Acceptance**다. 위 운영·환경 결과를 수집한 뒤 판단한다. Phase 5는 시작하지 않는다.

이전 Phase4.5-C1 유실 시도는 ENVIRONMENT_LIMITATION이었다. 최신 새 실행은 **PASS / DONE**이다. `PHASE_4_5_C1_REPORT.md`의 관측 범위와 유실 원인을 확인한다. C1 PASS 전 C2로 진행하지 않는다.


최신 C1/C2: **DONE / PASS**. 다음 운영 검증은 새 DB를 쓰는 24시간 Paper soak이다. malformed/backfill 독립 누적계측은 PARTIAL이며 이번 실운전에서 자연장애복구는 발생하지 않았다. PostgreSQL은 ENVIRONMENT_LIMITATION. Phase5는 시작하지 않는다.
