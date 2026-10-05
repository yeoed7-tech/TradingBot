# 모듈형 자동투자매매 연구 플랫폼 — v0.1

**첫 번째 납품 범위: Phase 1·2, 오프라인 연구 파이프라인.**

`Market Data → Strategy → Signal → Risk → Execution / Portfolio → Backtest → Report`

실행 가능한 소스, 3개 전략, 테스트, 합성 데이터, 생성된 보고서, Docker 구성을 포함합니다.
실제 거래소 연결, 실시간 페이퍼트레이딩, DB 복구, 웹 모니터링, 실거래는 아직 구현하지 않았습니다.
이 버전을 전체 5개 Phase가 완료된 플랫폼으로 해석하지 마세요.

## 1. 실행 환경과 빠른 시작

Python **3.12 이상**. 검증 환경은 Python 3.12.14입니다. 네트워크는 최초 의존성 설치 때만 필요합니다.

```bash
cd trading_platform
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m pytest -q
python -m trading_bot.main demo --out reports/demo
```

`reports/demo/index.html`을 브라우저에서 열면 전략 비교가 보입니다.
각 전략 폴더의 `index.html`에는 6개 그래프와 전체 성과 지표가 있습니다.
데모는 900일 × 2종목의 **합성 데이터(seed=42)** 를 사용합니다. 실제 암호화폐 수익률이 아닙니다.
단일 스크립트 진입점 `python main.py ...` 또는 설치 후 `trading-research ...`도 지원합니다.
명령어는 프로젝트 루트에서 실행합니다.

## 2. 구현 현황

| 영역 | 이번 버전 |
|---|---|
| 데이터 | UTC CSV, OHLCV 검증, 중복·결측·간격 불일치 거부, 여러 종목 동기화 |
| 전략 | 플러그인 인터페이스, EMA 20/100, Wilder RSI, 일봉 종가 확인 돌파 |
| 포트폴리오 | 현금·여러 종목 현물 매수·평균원가·수수료·실현손익·완결 거래 |
| 리스크 | 종목/총 투자비중, 일/주 손실, MDD, 연속손실, 비정상 가격, 슬리피지, 수동 kill() |
| 포지션 크기 | Fixed Fractional 투자비중 상한, ATR 기반 위험예산 |
| 체결 | 시장가/지정가, 다음 봉 이후 체결, 지연, 수수료, 슬리피지, 가격/수량 단위, 부분체결, 만료 |
| 주문 | UUID, 상태 전이 검사, 동일 ID 중복 제출 방지, 종목별 활성 주문 1개 |
| 연구 | 시간순 3분할, Grid Search, 이웃 파라미터 안정성, Rolling Walk Forward |
| 분석 | 15개 지표, 6개 그래프, 전략 비교, 동일 종목 바스켓 Buy & Hold |
| 기록 | JSONL 이벤트, 주문/체결/거래/자산/월별수익 CSV, 설정을 포함하는 metrics.json |
| 확장 | ExchangeAdapter 프로토콜·MockExchange, 가중 목표비중 StrategyPortfolio |
| 실거래 | **구현 안 됨. CLI 거부, live_trading=true 설정도 검증에서 거부** |

## 3. 디렉터리 구조와 책임

```text
trading_platform/
  config/default.toml           실행 설정
  config/grid.json              파라미터 탐색 공간
  trading_bot/
    config/settings.py          엄격한 Pydantic 설정 검증
    data/market_data.py          데이터 검증·CSV·합성 데이터
    core/events/models.py       Bar / Signal / Order / Fill
    core/exchange/               거래소 계약과 오프라인 테스트 대역
    core/execution/engine.py     주문 의도 처리와 SimulationBroker
    core/portfolio/engine.py     현금·원가·PnL 회계
    core/risk/engine.py          주문 허용, 크기 제한, 비상정지
    strategies/                 교체 가능한 전략
    backtest/engine.py          시간 순서 조율
    backtest/validation.py      분할·탐색·워크포워드
    analytics/                 지표와 HTML/PNG 보고서
    monitoring/events.py       JSONL 이벤트 기록
    main.py                    CLI
  tests/                       네트워크 없는 pytest
  reports/demo/                실제 생성한 예제 보고서
  reports/walk_forward/        실제 실행한 검증 결과
  docs/                        설계와 이후 단계 작업 목록
  Dockerfile
  docker-compose.yml
```

전략은 완성된 `Bar`만 읽습니다. 거래소 API나 자산 잔고에 접근하지 않으며 수량을 계산하지 않습니다.
Portfolio는 체결을 회계에 반영하고, RiskEngine은 전략의 목표비중을 제한합니다.
ExecutionEngine이 주문을 생성하고 SimulationBroker가 체결을 만듭니다.
백테스트마다 전략·리스크·포트폴리오 상태는 새로 생성합니다.

## 4. CSV 백테스트

```csv
timestamp,symbol,open,high,low,close,volume
2024-01-01T00:00:00Z,BTC/USDT,42000,43000,41000,42500,1000
2024-01-02T00:00:00Z,BTC/USDT,42500,43500,42000,43000,1200
```

- timestamp는 **봉 시작 시간**, volume은 **기초자산 수량**입니다.
- 최소 2개 봉. 실제 전략은 충분한 워밍업과 평가 기간이 필요합니다.
- 모든 종목은 같은 봉 간격과 같은 타임스탬프 집합을 가져야 합니다.
- 모든 종목은 같은 표시 통화(예: USDT)를 사용해야 합니다. 환전 엔진은 없습니다.
- `bar_seconds=86400`은 일봉, `3600`은 시간봉입니다. 돌파 전략은 일봉 전용입니다.
- 누락·상장폐지 종목을 자동 채우지 않습니다. 사용자 데이터의 생존편향은 별도 확인해야 합니다.

```bash
python -m trading_bot.main backtest --data my_ohlcv.csv --config config/default.toml --out reports/run
python -m trading_bot.main compare --data my_ohlcv.csv --out reports/comparison
```

`compare`는 3개 기본 전략의 기본 파라미터를 동일한 포트폴리오/리스크 설정에서 비교합니다.
개별 파라미터 변경은 `backtest`의 `[strategy.params]`를 사용하세요.
수익률뿐 아니라 CAGR, MDD, Sharpe, Sortino, 거래 수를 함께 비교합니다.

## 5. 설정

설정은 TOML로 분리했습니다. 모르는 필드, 잘못된 범위, NaN 등을 거부합니다.

```toml
[strategy]
name = "ema_cross"
[strategy.params]
fast = 20
slow = 100
weight = 0.4
```

- `target_weight=None`: HOLD, 현재 수량 유지.
- `target_weight=0`: 보유 포지션 청산 목표.
- `target_weight=0.4`: 자산의 40%를 해당 종목에 배분하자는 제안. 리스크 엔진이 축소할 수 있습니다.
- `risk.fixed_fraction=0.35`: 고정비중 모드에서 **종목별 목표 총 비중** 35% 상한입니다. 매 신호마다 35%를 추가 매수하는 뜻이 아닙니다.
- `risk.sizing="atr"`: `위험예산 × 자산 / (ATR × atr_multiple)`에 해당하는 목표수량 상한.
- ATR은 완료된 최근 `atr_period` 봉의 True Range 단순평균입니다.
- `risk.rebalance_tolerance`: 자산 대비 주문 차액이 작은 리밸런싱을 생략. 목표 0 청산은 예외.
- `execution.delay_bars=1`: 종가 신호 다음 봉 시가에 최초 체결 가능.
- `risk`의 손실 수치는 0.03 = 3%처럼 양의 소수로 설정합니다.
- 종목별 규칙은 `[symbol_rules."BTC/USDT"]` 아래 `min_notional`, `price_tick`, `quantity_step`으로 재정의할 수 있습니다.

기본 `max_gross_weight<=1`로 공매도·차입·레버리지는 지원하지 않습니다.
기본값은 사용자 자본이나 거래소 추천을 의미하지 않는 연구용 예시입니다.

## 6. 체결·리스크 모델의 정확한 의미

1. 봉 시작에 기존 주문을 처리합니다. 종가 신호는 미래 봉에서만 실행합니다.
2. 시장가: 시가에 불리한 고정 슬리피지 적용 후 불리한 방향으로 tick 반올림.
3. 지정가: 시가와 비용을 적용한 체결가가 지정가보다 유리한 경우만 체결.
   봉 중간 고가/저가 터치 체결은 지원하지 않습니다. 큐 순위도 추정하지 않습니다.
4. 유동성 상한은 **직전 완료 봉 거래량 × 참여율**입니다. 현재 봉의 미래 거래량을 보지 않습니다.
5. 주문의 미체결분은 다음 봉으로 이월하며 만료 시 취소합니다. 남은 자산/위험 한도가 없으면 취소합니다.
6. 신규 주문에는 최소 주문금액을 적용합니다. 유효한 주문의 부분체결은 그보다 작을 수 있습니다.
7. 매수 체결 직전에 현재 시가로 현금과 총/종목 위험 한도를 다시 검사합니다.
8. 한 종목의 기존 주문과 목표 방향이 반대가 되면 취소합니다. 같은 방향이면 만료/체결을 기다립니다.
9. 비상정지는 해당 실행 전체에 유지됩니다. 일자가 바뀌어도 자동 재개하지 않습니다.
   신규 매수를 차단하고 미체결 매수를 취소하지만, 매도는 허용합니다. **자동 강제청산이 아닙니다.**
10. MDD 및 일/주 손실은 시가와 종가 평가에서 감지합니다. 손실 기준은 전일/전주 마지막 평가자산이며 갭 손실도 반영합니다.
11. ATR 위험예산은 **1회 최대손실 보장/손절 주문이 아닙니다.** 갭, 가격 움직임에 따라 손실한도를 넘을 수 있습니다.
12. 종료 시 미체결 주문만 취소합니다. 미청산 포지션은 마지막 종가 평가로 남기며 강제 매도 비용을 넣지 않습니다.
13. 가격 변동 후 보유비중이 일시적으로 상한을 초과할 수 있습니다. 상한은 추가 매수 시 검사하며 지속 강제청산 제약이 아닙니다.
14. 현재 회계의 금액은 부동소수점입니다. 수량 step/tick 처리에는 Decimal을 사용하지만 실거래용 통화별 Decimal 회계 검증은 후속 단계입니다.

## 7. 성과 정의

- 수익률·CAGR·MDD·변동성은 소수 단위. 차트에는 %를 표시합니다.
- 연환산은 365.25일, 무위험수익률 0, 표본 표준편차를 사용합니다.
- Sortino의 하방편차는 양의 수익을 0으로 둔 전체 구간 RMS입니다.
- 최대낙폭은 음수. Calmar는 CAGR / abs(MDD).
- **거래 1건은 종목별 0 → 보유 → 0의 완결 왕복**입니다. 부분 매도 손익은 체결 기록에 먼저 기록하고, 거래 통계는 완전 청산 시 반영합니다.
- 진입·청산 수수료를 손익에 포함합니다. 미청산 거래는 승률/손익비/거래 수에서 제외합니다.
- Average Loss는 음수. Payoff Ratio는 평균이익 / abs(평균손실).
- 손실 거래가 없을 때 Profit Factor는 무한대 대신 `null/N/A`, 거래가 없을 때 승률도 `null/N/A`.
- Exposure는 포지션을 보유한 종가 관측치 비율이며 평균 투자비중과 다릅니다.
- Benchmark는 데이터에 있는 종목을 첫 평가봉 시가에 동일비중 매수한 **비용 없는** 보유 기준선입니다.
  BTC 단일 데이터이면 BTC Buy & Hold가 됩니다. 순수익 비교로 오해하지 마세요.

## 8. 학습/시험/검증과 최적화

```bash
python -m trading_bot.main split --data my_ohlcv.csv --train-end 2024-01-01 --test-end 2026-01-01 --out reports/splits
python -m trading_bot.main optimize --data reports/splits/train.csv --grid config/grid.json --out reports/grid
python -m trading_bot.main walk-forward --data my_ohlcv.csv --train-bars 300 --test-bars 100 --out reports/wf
```

경계일은 다음 구간의 첫 날짜입니다. 예: train은 2024-01-01 미만, test는 2026-01-01 미만.
Grid Search에는 **학습 데이터만** 전달하세요. 사용자가 전체 데이터를 입력하면 CLI가 그 의도를 판별할 수 없습니다.
추천 파라미터는 최고 수익률이 아니라 인접 격자점의 평균 Sharpe를 기준으로 고릅니다.
이웃 표준편차, 경계 선택, 적은 거래 수 경고를 포함하지만 통계적 과최적화 증명은 아닙니다.

Walk Forward는 train 구간에서만 선택하고 바로 다음 test에서 평가합니다. 시험 구간은 중복되지 않습니다.
시험 시작 전 학습 데이터는 지표 워밍업에만 사용하고 주문은 시험 구간 이후에 생성합니다.
**각 fold는 초기 현금을 새로 받습니다. 연속 운용 결과로 합성하지 않습니다.**
마지막 test_bars 미만 잔여 구간은 평가하지 않습니다. 별도의 최종 Validation 구간은 사람이 보존해야 합니다.
Bayesian Optimization, 다중검정 보정, Deflated Sharpe는 미구현입니다.

## 9. 새 전략 추가

`trading_bot/strategies/custom_strategy.py` 파일을 만들고 다음처럼 구현합니다.

```python
from trading_bot.strategies.base_strategy import Strategy
from trading_bot.core.events.models import Signal

class CustomStrategy(Strategy):
    def __init__(self, weight=0.2):
        self.weight = weight
        self.last = {}

    def on_data(self, bars):
        signals = []
        for symbol, bar in bars.items():
            previous = self.last.get(symbol)
            target = None if previous is None else (self.weight if bar.close > previous else 0.0)
            signals.append(Signal(symbol, target, "custom", "one-bar momentum"))
            self.last[symbol] = bar.close
        return signals
```

TOML에는 `name="trading_bot.strategies.custom_strategy:CustomStrategy"`, params에 `weight=0.2`를 지정합니다.
기존 거래/회계/리스크/백테스트를 수정할 필요가 없습니다. 신뢰할 수 있는 로컬 Python 플러그인만 사용하세요.
단순 BUY/SELL 전략은 매수 시 목표비중, 매도 시 0, HOLD 시 None으로 변환하면 됩니다.
지정가 전략은 Signal에 `order_type=OrderType.LIMIT`, `limit_price=...`를 전달합니다.

여러 전략은 `StrategyPortfolio([(0.4, strategy_a), (0.3, strategy_b), (0.3, strategy_c)])`로 합칠 수 있습니다.
이는 목표비중을 합산한 계좌이며 전략별 독립 원장/손익 귀속은 없습니다.

## 10. Paper Trading / Live Trading

이 릴리스에는 연결 실행 경로가 없습니다.

```bash
python -m trading_bot.main paper  # 명시적 오류, 주문 없음
python -m trading_bot.main live   # 명시적 오류, 주문 없음
```

`LIVE_TRADING=TRUE` 환경변수를 주어도 활성화되지 않습니다. `.env`를 읽거나 API 키를 요구하지 않습니다.
실거래 전환 방법은 **현재 버전에서는 없음**입니다. Phase 3–5 구현·통합검증 후 제공해야 합니다.
MockExchange는 계약 테스트용이며 거래소 연결 테스트를 통과했다는 의미가 아닙니다.

후속 작업과 실거래 승인 절차는 `docs/ROADMAP.md`에 적었습니다.

## 11. Docker

```bash
mkdir -p reports
# Linux bind mount에서 권한이 맞지 않으면 컨테이너 UID 또는 호스트 폴더 소유권을 조정하세요.
docker compose build
docker compose run --rm research
# 테스트:
docker compose run --rm research python -m pytest -q
```

실행 컨테이너는 네트워크를 차단한 연구 모드입니다. 설치 단계에는 패키지 다운로드가 필요합니다.
이 납품 환경에는 Docker 실행 파일이 없어 이미지 빌드/컨테이너 실행은 검증하지 못했습니다.
Python 직접 실행은 검증했습니다.

## 12. 테스트와 재현

```bash
python -m pytest -q tests/test_core.py      # Phase 1
python -m pytest -q tests/test_research.py  # Phase 2
python -m pytest -q
```

테스트는 전략, 회계, 미래 데이터 영향 차단, 주문 지연/부분체결/취소/중복, 최소금액,
포지션 크기, 총 위험 한도, 손실 제어, MockAdapter, 지표 수계산, 보고서 생성, 시간순 분할/탐색을 확인합니다.
`reports/verification.txt`에 실행 결과를 포함합니다.

공식 실행 도구 문서:
- Python TOML: https://docs.python.org/3.12/library/tomllib.html
- pytest: https://docs.pytest.org/en/stable/how-to/usage.html
