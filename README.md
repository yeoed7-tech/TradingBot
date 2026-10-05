# TradingBot

자동투자매매 연구 플랫폼의 현재 작업본과 이전 설계·구현·시험 산출물을 관리하는 저장소입니다.

## 구성
- `trading_platform_phase4_5c1_pass/`: 현재 작업본. 설계 문서는 `docs/`, 소스는 `trading_bot/`, 시험 자료는 `reports/`에 있습니다.
- `trading_platform_c1_code_checkpoint/`: C1 코드 체크포인트.
- `trading_platform_phase45c2_6h_artifacts_20261003.zip`: C2 6시간 Paper 시험 결과와 관련 문서.
- `previous_deliverables_20261005/`: 기존 Documents 작업 폴더의 산출물 보관본 및 원본 ZIP. 파일별 SHA256은 `COPY_MANIFEST_SHA256.json`에 있습니다.

## 기록된 검증 범위
보관된 C2 보고서 기준 2026-10-03 공개 시세 기반 6시간 Paper 시험 및 독립 대사가 PASS입니다. Windows 전체 회귀는 124 passed / 2 failed이며, 두 실패는 fork 미지원 사례입니다. Windows 호환 회귀는 124 passed / 2 deselected입니다.
이는 현재 작업본에 대한 새로운 회귀 시험 결과가 아닙니다. 보관본과 현재 작업본에 코드 차이가 있으므로 변경된 코드의 검증은 별도로 수행해야 합니다.
Phase 4.5 전체는 PARTIAL이며, 24시간 시험 및 Phase 5 인증/실주문은 완료되지 않았습니다.

## 실행
각 프로젝트 폴더의 `README.md` 및 `docs/`를 참고하세요. 가상환경은 해당 폴더에서 새로 생성하고 의존성을 설치하세요.
실주문 없이 공개 시세와 SimulationBroker를 사용하는 연구용 Paper Trading 자료를 포함합니다.

## 보관 정책
설계, 코드, 테스트, 설정, 보고서, 로그, SQLite 시험 증거 및 ZIP을 첫 커밋에 보관합니다. 가상환경·캐시·인증정보는 제외합니다.
