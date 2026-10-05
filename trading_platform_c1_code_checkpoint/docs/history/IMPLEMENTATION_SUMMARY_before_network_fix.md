# Phase 3 구현 요약

상태: **PARTIAL — 코드/오프라인 검증 완료, 실제 공개 API 통합 성공 미확보**.
기준일: 2026-09-28. 기반 파일: trading_platform_v0.1_phase1-2.zip.

## 기존 프로젝트 점검

| 영역 | 기존 구조 | 이번 처리 |
|---|---|---|
| Market Data | CSV 검증, 동기화 OHLCV batches | 그대로 사용, HistoricalFeed로 감쌈 |
| Strategy | 완성 봉 입력 → 목표비중 Signal, 플러그인 로딩 | 전략 인터페이스/기존 전략 수정 없음 |
| Risk | 비중·현금 한도, 일/주 손실, MDD, ATR, kill | **RiskEngine 소스 변경 없음** |
| Portfolio | 현금·평균원가·부분매도 PnL·완결 거래 | 회계 유지, 조회용 snapshot 메서드 추가 |
| Backtest | 완료 봉 순서 조율, 다음 봉 체결 | HistoricalFeed 및 공통 TradingSession 사용 |
| Execution | 목표비중→주문, 동일 종목 중복 차단, 만료 | 최소수량/구간별 tick 적용 |
| SimulationBroker | 시가·수수료·슬리피지·부분체결 | 선택적 Quote 입력 확장, 기존 봉 체결 경로 유지 |
| 이벤트 | Bar/Signal/Order/Fill | 불변 Quote/FeedEvent와 FeedState 추가 |
| 설정 | 엄격한 Pydantic + TOML | PaperConfig/ReconnectConfig 추가 |
| 테스트 | 37개, 네트워크 없는 연구 검증 | 기존 유지 + Phase 3 40개 = 77개 |
| 문서 | README와 ROADMAP, ARCHITECTURE 없음 | ARCHITECTURE 신규 작성, 상태·검증 문서 추가 |

## 구현한 내용

1. `core/exchange/upbit_public.py`: ccxt.async_support 기반 Upbit 공개 전용 어댑터.
   ticker/OHLCV/orderbook 정규화, market metadata/precision, 시뮬레이션 수수료·제약 정보를 제공한다.
   계정별 정보는 요청하지 않고, 별도 계좌 계약은 명시적인 unavailable 오류를 낸다.
2. GuardedUpbit: 공개 조회 GET/path/host allowlist 및 Authorization 거부.
   공개 façade에는 실제 주문 메서드가 없고 Paper Engine에는 façade조차 주입하지 않는다.
3. `data/feeds.py`: HistoricalFeed, ReplayFeed, RealtimeExchangeFeed.
   시간 범위 pagination, 완료 봉만 처리, 동일 timestamp 중복 제거, gap 검사와 cursor 유지/backfill.
4. REST polling + ccxt rate limiter + 요청 timeout + bounded exponential backoff.
   실패/누락/stale 동안 주문 판단·체결 중지. 반복 실패는 FAILED로 고정한다.
5. `core/session.py`: 포트폴리오·리스크·실행기·가상 브로커·전략 검증을 공통 조립.
6. `paper_trading/engine.py`: 현재 ask/bid를 기존 SimulationBroker에 전달.
   스프레드·추가 슬리피지·tick·수량 step·최소금액/수량·유동성 상한과 비용을 반영한다.
   회계는 기존 Portfolio.apply만 사용한다.
7. `paper_trading/runner.py`: 공개 연결 수명주기, 관측 시간 제한, 예외 시 종료와 결과 기록.
8. CLI paper, 공개 연결 진단 스크립트, 소규모 JSON/JSONL 실행 결과.

## 원칙과 의도적인 범위 제한

- 실제 체결을 과거 backfill 시가로 소급 생성하지 않는다. 지표만 갱신하고 최신 봉의 새 신호만 제안한다.
- 데이터 장애 후 대기 주문은 취소한다. stale 호가로 청산하거나 재개하지 않는다.
- 무거래로 생략된 봉과 네트워크 유실을 자동 구분하지 않는다. 연속 봉을 복원하지 못하면 보수적으로 중지한다.
- Paper는 한 종목/한 프로세스 실행이며 session 중복 방지를 제공한다. DB 저장/재시작 복구는 이번 범위 밖이다.
- REST만 구현한다. 새 WebSocket 연결/인증 API/실거래/대시보드/AI 연구 기능은 추가하지 않았다.
- 이 변경에는 새로운 수익률 목표나 전략 최적화가 없다.

## 실제 연결 결과

공개 `GET https://api.upbit.com/v1/market/all` 요청이 3회 모두 ExchangeNotAvailable로 실패했다.
정상 시장 이벤트·전략 실행·가상 체결을 실제 시세로 확인하지 못했다.
따라서 이번 결과물을 **Phase 3 완료**라고 표시하지 않는다.
실제 API 실패 기록과 오프라인 테스트 기록은 TEST_REPORT와 reports/phase3에 포함되어 있다.
