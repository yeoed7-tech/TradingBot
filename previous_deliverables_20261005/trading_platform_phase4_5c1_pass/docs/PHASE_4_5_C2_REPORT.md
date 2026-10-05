# Phase 4.5-C2 — 6-Hour Public WebSocket Paper Acceptance

**PASS / DONE** (2026-10-03 KST). 새 SQLite DB로 공개 Upbit 시세를 사용한 SimulationBroker Paper 세션을 21,602.016초(6시간 2초) 연속 실행했다. 30초 표본 720개, 상태 NORMAL, 정상 shutdown, 예외 0, WS reconnect/gap/stale/duplicate 각 0이다. 가상 주문 2건은 모두 체결됐고 매수 후 전량 매도되어 열린 주문과 잔여 포지션은 없다.

## 실행 및 원시 증거

- 시작/종료: 2026-10-03 02:12:43 ~ 08:12:45 KST (UTC 보고서 시간 기준)
- quote source: Upbit public WebSocket; execution backend: `SimulationBroker`; authenticated account access: false
- 공개 REST 요청 7,111회, WS 수신 169,824건, 실제 private HTTP 및 real order/cancel HTTP 요청 0회
- 주문/체결 2/2, 신호 361, 처리 bar 480, 저장 snapshot 7,112
- 기초자산 1,000,000 KRW, 최종 현금/평가액 999,908.61424306 KRW, 실현손익 -91.38575694 KRW, 최종 미실현손익 0
- risk halt false, cache 관측치는 각 설정 상한 1,000 이하, system event는 정상 STARTUP/SHUTDOWN 각 1건
- DB 크기는 첫 30초 표본의 151,552 bytes에서 1,814,528 bytes로 1,662,976 bytes 증가(720개 표본 기준 선형 추정 약 279 KB/h). 로그는 65,379에서 65,580 bytes로 201 bytes 증가했다.
- `rss_bytes`는 Windows 실행 환경에서 720개 표본 모두 비어 있어 RSS 증가율은 평가하지 않았다. DB 크기 증가는 저장 snapshot 7,112건을 포함한 durable 기록이다.

## 사후 대사 및 회귀

독립 Decimal 원장 재계산 **PASS**: 현금·수수료·실현손익·체결 수·포지션·최종 snapshot·risk·cursor·open order가 DB/runner 간 일치했다. SQLite `integrity_check=ok`; order, client order, fill, OHLCV 중복 0; lease owner는 빈 값으로 반납됐다.

Windows 전체 회귀 실행은 **124 passed, 2 failed**였다. 두 실패는 `tests/test_phase45_hardening.py`의 프로세스 격리 테스트가 Windows에서 지원하지 않는 `multiprocessing.get_context('fork')`를 호출해 발생했다. 나머지 Windows 호환 회귀는 **124 passed, 2 deselected**다. 따라서 6시간 Paper acceptance와 독립 대사는 PASS지만, 전체 회귀의 두 프로세스 격리 사례는 이 Windows 실행에서 검증되지 않았다.

필수 산출물은 `reports/phase45c2_20261003_retry01/soak.json`, `paper_6h.sqlite3`, `reconciliation.json`, `process.stdout.log`, `pytest_full.txt`, `pytest_windows_compatible.txt`다. 이전 재시도 기록은 이 PASS 실행과 시간을 합산하지 않았다.

이번 C2 결과는 24시간 soak, 실제 WS 장애·재연결 수용 시험, RSS 추세, PostgreSQL 운영 검증 또는 Phase 5 인증/실주문을 완료했다는 뜻이 아니다. Phase 4.5 전체 상태는 잔여 gate 때문에 계속 **PARTIAL**이다.
