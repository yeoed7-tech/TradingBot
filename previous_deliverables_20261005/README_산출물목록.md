# 이전 산출물 보관 — 2026-10-05
원본: C:\Users\은동\Documents\project_tradingBot
기존 PROJECT_GPT 파일은 덮어쓰지 않았습니다. 설계, 소스, 테스트, 설정, 보고서, 로그, DB, ZIP을 복사하고 SHA256으로 검증했습니다.
재생성 가능한 .venv, .git, __pycache__, .pytest_cache, *.egg-info는 제외했습니다.

## ZIP 범위
- original_zips/trading_platform_phase4_5c1_pass(2).zip: 설계·코드·C1 당시 reports 265개. C2 미포함.
- original_zips/trading_platform_c1_code_checkpoint.zip: 설계·코드·테스트 코드. reports 0개.
- original_zips/trading_platform_v0.1_phase1-2.zip: Phase 1–2 코드/문서/당시 reports.
- trading_platform_phase45c2_6h_artifacts_20261003.zip: C2 문서와 6시간 테스트 reports 17개. 소스 전체 미포함.
- trading_platform_phase4_5c1_pass/: 기존 작업 프로젝트 전체 및 C2 문서/결과.
- trading_platform_c1_code_checkpoint/: 기존 C1 코드 체크포인트.

## 복사 전 차이
원본 555개 파일 중 기존 PROJECT_GPT에서 11개 내용 불일치, 1개 누락. 두 버전을 모두 보존했습니다.
불일치: tests/conftest.py, tests/test_phase3_paper.py, tests/test_phase4_persistence.py, trading_bot/core/session.py, trading_bot/persistence/ledger.py, trading_bot/strategies/__init__.py, base_strategy.py, breakout_strategy.py, ema_cross.py, ensemble.py, rsi_strategy.py (모두 trading_platform_phase4_5c1_pass 내부).
누락: trading_platform_phase4_5c1_pass/trading_bot/strategies/laure_infinite.py.
COPY_MANIFEST_SHA256.json에 파일별 원본 경로, 크기, SHA256을 기록했습니다.
