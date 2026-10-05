# Phase 3 Test Report

판정: **PARTIAL / 실제 공개 시세 E2E 미통과**.
오프라인 테스트의 통과를 실제 거래소 연결 성공으로 대체하지 않았다.

## 실행 환경과 자동 테스트

- Python 3.12.14, ccxt 4.5.84, pytest 9.1.1.
- 명령: `python -m pytest -q --junitxml=reports/phase3/pytest.xml`
- 최종 결과: **77 passed in 3.29s**, 실패 0, skip 0.
- 기계 판독 기록: `reports/phase3/pytest.xml`.

| 파일 | 테스트 수 | 결과 |
|---|---:|---|
| tests/test_core.py | 27 | PASS |
| tests/test_research.py | 10 | PASS |
| tests/test_phase3_adapter.py | 12 | PASS |
| tests/test_phase3_feed.py | 5 | PASS |
| tests/test_phase3_paper.py | 23 | PASS |

## 검증 범위

| 영역 | 검증 내용 |
|---|---|
| Adapter | UTC milliseconds, ticker/OHLCV/book 정규화, 역순 정렬, 중복/충돌, 잘못된 가격, metadata, precision |
| 요청 안정성 | pagination, 429 재시도, 지수 backoff, timeout, 반복 네트워크 실패 |
| Feed | 정상 스트림, 미완성 봉 제외, 중복 봉 제거, 누락 검출, cursor 유지, reconnect/gap backfill |
| Freshness | stale 호가/봉과 늦게 소비된 이벤트 차단, 반복 실패 latch |
| Paper | BUY/SELL/HOLD, 다음 호가 체결, limit·부분체결, 지연·만료, 최소금액/수량/정밀도 |
| 회계 | bid/ask·slippage·fee 수계산, 보유수량·평균원가·실현/미실현 PnL·현금·자산 |
| Risk | 종목 비중, MDD, 일 손실, 수동 kill, 데이터 장애 취소, 비정상 호가에서 매도도 차단 |
| 복구 | backfill 과거 가격으로 체결하지 않음, 새 신호와 현재 호가로만 재개 |
| 안전 | 공개 façade에 주문 메서드 없음, private/POST/DELETE/Authorization 차단, 주문 메서드 spy=0 |
| 출력 | 종료 시 연결 close, 실패/관측 제한 결과 파일 저장 |

## CCXT 자체 변환 경로 검증

`test_ccxt_real_parser_guarded_transport_to_paper`는 실제 GuardedUpbit/ccxt 메서드와 파서를 사용한다.
교체한 것은 HTTP 응답 계층뿐이다. 원형 market/ticker/candle/orderbook 응답을 통과시켜
Adapter → Feed → Strategy → Risk → SimulationBroker → Portfolio의 가상 왕복 체결을 확인했다.

- create_order AsyncMock await_count = 0.
- cancel_order AsyncMock await_count = 0.
- 관측한 HTTP 요청은 전부 허용된 공개 GET 경로.
- 실제 서버 연결 테스트가 아니라 **오프라인 계약 통합 테스트**임을 명시한다.

검증 중 fixture에서 trade_timestamp를 빠뜨린 문제가 발견되어 실제 Upbit 스키마대로 보완했다.
과거 가격 급등락 테스트 한 건은 의도치 않게 기존 비정상가격 kill을 작동시켜,
소급 체결 검증과 위험정지 검증이 충돌하지 않도록 그 fixture 가격을 조정했다.
위험 엔진을 느슨하게 바꾸거나 테스트를 skip하지 않았다.

## Backtest 회귀

1. 수정 전 기존 37개 테스트: 모두 통과.
2. 수정 후 기존 37개 테스트: 모두 통과.
3. `python -m trading_bot demo --out reports/phase3/backtest_regression` 실행 성공.
4. EMA / RSI / breakout 각각의 equity.csv와 trades.csv를 기존 압축파일에 있던 보고서와
   pandas.assert_frame_equal로 비교: **6개 파일 모두 동일**.
5. HistoricalFeed → run_feed와 기존 run(frame) 결과 일치 테스트 통과.

증거: `reports/phase3/regression_comparison.json`, `reports/phase3/backtest_regression/`.
리스크 엔진과 기존 전략 소스는 변경하지 않았다.

## 실제 공개 API 테스트 — FAIL

실행 명령:

```bash
python -m scripts.public_integration --duration 150 --out reports/phase3/public_integration
```

- 시작 UTC: 2026-09-28T00:56:33.986237+00:00 (한국 09:56:33).
- 종료 UTC: 2026-09-28T00:56:35.957126+00:00.
- 최대 관측 요청은 150초였으나 초기 연결 실패로 약 2초 후 종료했다. 150초간 정상 수신했다고 주장하지 않는다.
- endpoint: `GET https://api.upbit.com/v1/market/all`.
- 공개 HTTP 시도 3회, 모두 실패.
- 오류: `PublicDataUnavailable: load_markets: ExchangeNotAvailable: upbit GET https://api.upbit.com/v1/market/all`.
- feed status: FAILED; risk_killed: true.
- 정상 market event / processed bar: **0 / 0**.
- 가상 주문 / 가상 체결: **0 / 0**.
- 실제 주문 HTTP 요청: **0** (transport 감사 경로에서 주문 endpoint 전송 없음).
- `integration_success: false`, 프로세스 exit code 1.

원인 후보를 넘어 네트워크 정책/거래소 장애를 단정할 증거는 확보하지 못했다.
허용된 API 조회만 시도했으며 다른 경로로 접근 제한을 우회하지 않았다.

원본 결과: `reports/phase3/public_integration/summary.json`, `events.jsonl`, `config.json` 등.
최초 시도와 최종 시도가 동일한 최초 endpoint에서 실패했다. 최종 코드의 재시도 결과를 보관했다.

## 미검증

- 실제 공개 시세에서 정상 신호·가상 체결·PnL이 연속 작동하는지.
- 실제 네트워크 중단/복구 시 업비트 API 동작. 장애 주입 테스트만 통과했다.
- Docker 이미지 빌드·컨테이너 실행: 환경에 Docker 명령 없음.
- 장시간 운영, DB 복구, 실거래: 이번 범위 밖이며 구현/실행하지 않았다.

14개 완료 조건 중 실제 연결 관련 1/2/3/13이 미충족이므로 Phase 3은 완료가 아니다.
