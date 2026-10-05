# 다음 단계 — Phase 4.5 Operational Follow-up

**C1은 PASS / DONE이다.** 2026-09-30 새 단일 프로세스로 Paper 프로그램 3,600.276초, soak runner 3,602.007초를 연속 실행했다. 전체 회귀는 실행 전후 126개 통과했다. 자세한 증거와 범위는 `PHASE_4_5_C1_REPORT.md`에 있다.

**C2 6시간 Paper는 PASS / DONE이다.** 2026-10-03 실행 및 범위는 `PHASE_4_5_C2_REPORT.md`를 참고한다. 다음 운영 단계는 새 DB를 사용하는 24시간 soak이며 별도 실행으로 판정한다.

| 남은 작업 | 상태 | 필요한 검증 |
|---|---|---|
| 6시간 Paper | PASS / DONE | 21,602.016초, 표본 720개, 독립 Decimal/reconciliation 및 SQLite integrity PASS. DB 약 279 KB/h 증가, log +201 B, RSS 계측 불가. `PHASE_4_5_C2_REPORT.md` |
| 24시간 Paper | NOT RUN | C2 이후 별도 요청과 새 DB 사용 |
| 작은 후반 RSS 증가의 장기 추세 | PARTIAL | 이번 Windows 6시간 실행의 RSS 표본은 계측 불가. 1시간 C1 추세 외에 장기 RSS slope는 미확인 |
| PostgreSQL migration/Decimal/rollback/unique/fencing | ENVIRONMENT_LIMITATION | Docker/psql가 없는 현재 환경. 준비된 `docker-compose.postgres.yml`과 `scripts.verify_postgres`로 별도 검증 |
| malformed/backfill 독립 누적 계측 | PARTIAL | 현재 최종 JSON에 별도 카운터가 없음. 실제 HTTP는 adapter transport audit를 기준으로 확인 |
| Public WS 실연결 disconnect/reconnect/재시작 acceptance | PARTIAL | 이번 자연 운전은 reconnect/stale/gap 0. 모의 장애 회귀는 통과했지만 실제 장애 acceptance는 별도 수행 |
| 여러 호스트의 clock skew와 network partition | PARTIAL | 로컬 역행·도약/lease/fencing 시험 통과. 멀티호스트 조건은 검증 필요 |
| SQLite disk full/손상·백업 복원 | PARTIAL | 실제 write lock과 주입된 checkpoint 실패는 차단. 실제 디스크 장애·복원은 별도 시험 |
| 장기 retention/백업 정책 | PARTIAL | INFO event/중복 snapshot 수동 prune 구조 유지. 주문·체결·회계 원장·필수 recovery state는 보존 |
| 다종목 및 다수 active order | PARTIAL | 현재 BTC/KRW 한 종목. active order와 복구 캐시 상한 확장은 별도 정책 필요 |
| 외부 plugin의 전략 state snapshot | PARTIAL | 기본 EMA/RSI/Breakout 결정성은 검증됨. 임의 외부 상태 plugin은 별도 검증 |

Phase 4.5 전체는 운영·환경 gate가 남아 **PARTIAL**이다. Phase 5 private 인증·실제 balance/order/cancel 기능은 **NOT IMPLEMENTED**이며 자동으로 시작하지 않는다. 이전 실패 실행은 최종 C2 증거와 합산하지 않았다.
