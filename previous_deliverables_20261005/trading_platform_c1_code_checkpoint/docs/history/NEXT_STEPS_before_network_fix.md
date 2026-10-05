# Phase 4 이전 남은 작업과 위험

## 필수: 실제 공개 시세 E2E 성공 확보

1. `api.upbit.com` 공개 API 접근이 가능한 실행 환경에서 설치 후 `python -m scripts.public_integration --duration 150 --out reports/public_integration_retry`를 실행한다.
2. 정상 metadata/ticker/OHLCV/book 수신, 새 완료 봉 관측, 전략 신호, Risk Decision,
   Simulation Order/Fill, Portfolio 변화, 실제 주문 HTTP 0을 결과 파일로 확인한다.
3. 재시도 결과가 실패이면 원인을 고치고 다시 검증한다. 현재 실패를 '거래소 장애'로 단정하지 않는다.
4. 코드·테스트·관측 증거가 모두 갖춰진 뒤 ROADMAP 1/2/3/13을 갱신한다.
   이번 결과물은 Phase 4 착수 승인이 아니다.

## 현재 모델/데이터의 기술부채

- Upbit 무거래 구간은 봉이 없을 수 있다. 현재는 누락과 구분하지 않고 GAP/fail closed한다.
  저유동성 종목을 확대하기 전에 명시적인 no-trade 정책과 별도 검증이 필요하다.
- REST polling 방식이다. WebSocket 재연결은 구현하지 않았으며 필요 시 공통 FeedEvent 경계 뒤에서 추가한다.
- KRW 현물 단일 종목만 실제 adapter profile로 지원한다. 여러 실시간 종목의 시각 정렬·결측 정책은 후속 범위다.
- 공개 market metadata의 precision은 ccxt descriptor다. 최소주문/tick은 검토된 공개 문서 스냅샷,
  수수료는 설정 가정이다. 변경 감지와 정책 갱신 절차가 필요하다.
- 계정별 수수료, maker/taker 할인, 제3통화 수수료, account chance는 조회하지 않는다.
- 현재 book fill은 최우선 bid/ask 잔량 참여율 모델이다. 같은 timestamp는 재사용하지 않지만
  새로운 timestamp마다 잔량이 재공급된다고 보는 가정이 있다. queue/market impact를 검증한 모델은 아니다.
- 플러그인은 신뢰하는 로컬 Python 코드여야 한다. 데이터·주문 인터페이스 분리는 악성 코드 격리가 아니다.
- 기존 회계의 금액은 float, 일/주 위험 경계는 UTC다. live 수준의 Decimal·통화·KST 경계 작업은 이번에 하지 않았다.
- pause 시 주문을 취소하므로 복구 후 최신 신호가 HOLD이면 주문이 재생성되지 않을 수 있다. 자동 과거신호 재전송은 하지 않는다.
- 반복 실패/invalid risk kill은 자동 해제하지 않는다. 기존 포지션의 지속 운용/회복 절차는 운영 설계가 필요하다.
- 메모리 저널·배열 기반이라 장시간 실행은 메모리가 증가한다. 이번 CLI는 duration으로 실행을 제한한다.
- 복구 cursor/중복 방지는 현재 프로세스 한정. 재시작은 새 가상 계좌다. 결과 JSON은 checkpoint가 아니다.
- 최신 봉 수정(revision)과 과거 거래소 데이터 정정 reconciliation은 구현하지 않았다.
- Docker 파일은 제공하지만 실제 빌드·컨테이너 실행 검증은 남아 있다.

## Phase 4에서 다룰 항목 — 지금은 구현하지 않음

DB·outbox·지속 cursor·원장 transaction·재시작 복구·로그 회전·인증된 모니터링.
이번 결손을 감추기 위해 간이 DB나 웹 화면을 먼저 추가하지 않는다.

## 검토한 공식 자료

- CCXT async/manual: https://github.com/ccxt/ccxt/wiki/Manual
- CCXT Upbit 구현: https://github.com/ccxt/ccxt/blob/master/python/ccxt/async_support/upbit.py
- Upbit minute candles: https://docs.upbit.com/kr/reference/list-candles-minutes
- Upbit rate limits: https://docs.upbit.com/kr/kr/reference/rate-limits
- Upbit KRW tick/minimum: https://docs.upbit.com/kr/docs/krw-market-info
- No-trade candle omission: https://global-docs.upbit.com/reference/list-candles-minutes

문서 확인과 실제 공개 API 수신 성공은 서로 다른 검증이다. 검색 결과나 저장된 예시를 실시간 수신 증거로 사용하지 않았다.
