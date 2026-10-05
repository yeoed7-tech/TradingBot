# 다음 단계 — Phase 4.5-C Operational Acceptance

Phase 4.5-B의 코드 변경과 단기 공개 WS 시험을 마쳤다. 1/6/24시간 실행 또는 PostgreSQL 실서버 결과 없이 장기간 안정성을 주장하지 않는다. Phase 5 인증·실거래는 금지 상태다.

| 작업 | 상태 | 다음 검증 |
|---|---|---|
| 실제 1h/6h/24h Paper | NOT RUN | 서로 다른 SQLite 파일로 `scripts.soak_paper --hours {1,6,24}` 실행; RSS 첫 안정 구간과 마지막 구간, DB/log 증가율, 재접속·stale·fill·risk 확인 |
| PostgreSQL migration/Decimal/rollback/unique/fencing | ENVIRONMENT_LIMITATION | Docker 환경에서 `scripts.verify_postgres`와 전체 DB 통합 테스트 실행 |
| 호스트 간 시계 이상과 네트워크 분리 | PARTIAL | 로컬 역행·만료는 차단하지만 여러 호스트가 DB와 시각이 어긋나는 조건은 시험 안 함; DB 시간 또는 외부 단조 시계 설계 검토 |
| SQLite lock/disk 장애 운용 | PARTIAL | 실제 write lock 및 주입된 checkpoint 실패는 차단됨; 실제 disk full/손상과 백업 복원은 별도 시험 |
| 장기 retention/백업 | PARTIAL | 주문·체결·회계·OHLCV는 보존, INFO 이벤트/중복 snapshot은 `retention.prune` 수동 실행; 자동 주기 실행은 안전성 검증 뒤 결정 |
| 다종목/복수 active order | PARTIAL | 현재 단일 `BTC/KRW` Paper; active order 수가 구성 상한을 넘는 다종목 확장은 별도 정책 필요 |
| plugin 전략 snapshot | PARTIAL | 기본 3전략은 결정성 검증; 외부 상태를 가진 임의 플러그인은 검증 필요 |
| Public WS 실제 disconnect/reconnect 장기 관측 | PARTIAL | 모의 테스트 및 기존 강제 종료 E2E 통과, 이 변경 뒤 단기 E2E에서 reconnect 0 |

단기 결과와 실행 명령은 `TEST_REPORT.md`, 운영 절차는 `SOAK_TEST.md`와 `OPERATIONS.md`, 진입 기준은 `PRE_LIVE_GATE.md`에 둔다.

## Phase 4.5-C1 이후 (2026-09-29)

- **ENVIRONMENT_LIMITATION:** Work에서 실제 Upbit Public WS Paper를 약 47분까지 관측했으나 exec-server 단절 및 workspace reset으로 1시간 연속 종료 결과와 원시 DB/계측이 유실됐다. `PHASE_4_5_C1_REPORT.md`를 참조한다.
- **NOT RUN:** C1 60분 완료, 최종 Decimal 회계/reconciliation/HTTP audit. 외부 로컬/VM에서 새 DB를 사용해 `python -m scripts.phase45c1_accept --database reports/phase45c1_retry/paper_1h.sqlite3 --out reports/phase45c1_retry` 한 명령을 재실행한다.
- C1이 **PASS**된 다음 작업만 **Phase 4.5-C2 — 6-Hour Operational Acceptance**로 진행한다. 이번 세션에는 C2/24h/Phase 5를 시작하지 않았다.
