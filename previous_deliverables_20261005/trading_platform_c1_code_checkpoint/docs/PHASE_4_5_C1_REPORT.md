# Phase 4.5-C1 — 1-Hour Real Public Paper Acceptance

**판정: ENVIRONMENT_LIMITATION. 1시간 Acceptance: NOT RUN (미달).**

실제 Upbit Public REST/WebSocket Paper 운전을 `python -m scripts.soak_paper --hours 1 --quote-source websocket --database reports/phase45c1/paper_1h.sqlite3 --out reports/phase45c1 --sample-seconds 30`으로 시작했다. 시작 전 전체 회귀 **124 passed, 1 warning**. 전략은 설정 그대로 EMA(20,100, weight 0.1), BTC/KRW, 1m, 가상 현금 1,000,000 KRW였다. 인증 정보와 Private/Live 경로는 사용하지 않았다.

## 관측된 구간

| 항목 | 확인된 값 | 범위 |
|---|---:|---|
| 시작 | 2026-09-29 06:55:32 UTC | Work 내 Paper 프로세스 |
| 마지막 직접 관측 | 시작 후 **2,820.48초 (약 47분)** | 3,600초 미달 |
| writer | owner `85efd665-8e79-4b32-9245-8e11ee9c01bd`, token 1 | 관측 중 동일 |
| RSS | 시작 151,920,640B; 마지막 189,313,024B | 전체 max/end 및 1시간 slope 없음 |
| DB | 시작 0B; 30분 30초 지점 290,816B | 최종 크기·증가율 없음 |
| 정상 이벤트 | 마지막 표본 777건 | 그때까지 stale/gap/error 0 |
| WebSocket | 30분 30초 지점 13,960 valid messages, 연결 1회 | 최종 합계 없음 |
| 가상 주문/체결 | 30분 30초 지점 주문 1, 부분체결 3 | 최종 합계 없음 |
| 최근 이벤트 캐시 | 약 25분 30초에 1,000개 상한 도달, 47분 표본도 1,000 | 스냅샷 캐시 마지막 777/1,000 |

약 8분 30초 지점에서 DB 읽기 전용 복사본의 Fill부터 현금·수량·원가·수수료·실현손익을 Decimal로 재계산해 일치를 관측했다. 약 30분에는 SQLite `quick_check=ok`, 주문/Fill/OHLCV key 중복 0을 확인했다. **최종 상태 대조가 아니므로 합격 증거로 쓰지 않는다.** 원시 30초 계측 파일과 DB는 Work exec-server transport 단절 뒤 작업 공간이 이전 스냅샷으로 되돌아가면서 유실됐다. `reports/phase45c1/runtime_metrics.csv`는 도구 응답으로 살아남은 **선별 표본 4개만 재기록**한 것이며 연속 원본으로 간주해서는 안 된다.

## 필수 합격 조건의 상태

- 실제 elapsed >= 60분: **FAILED / 환경 중단**, 47분까지만 확인.
- 종료 후 Decimal 원장, 최종 reconciliation, DB integrity, 중복 효과, 네트워크 호출 audit: **NOT RUN**, 종료 DB와 어댑터 결과가 없음.
- 캐시 상한: **PARTIAL**, 관측 구간은 준수. 1시간 전체의 최대값 없음.
- RSS 지속 증가 판단: **PARTIAL**, 초기화 후 상승폭은 제한적이었지만 60분 전체 시계열이 없어 판정하지 않음.
- regression: **DONE**, 실행 전 124 passed, 환경 복구 후 코드와 도구 보완 뒤 124 passed.
- 실거래 주문/Private API: 실행 구조는 `GuardedUpbit`의 Public GET allowlist와 `SimulationBroker`; **1시간 종료 audit 수치는 미확보**이므로 0으로 기재하지 않음.

따라서 **C1 PASS가 아니다.** C2 6시간 시험은 시작하지 않는다. Phase 5 인증·주문 기능도 없다.

## 외부 로컬/VM 재실행

프로젝트 루트에서 새 전용 DB를 사용한다. 이 명령은 사전/사후 전체 pytest, 실제 1시간 Public WS Paper, 30초 간격 CPU/RSS/DB/heartbeat 계측, 네트워크 audit, 독립 Decimal 원장 검증, 종료 판정 파일을 순서대로 생성한다.

```bash
python -m pip install -r requirements.txt
python -m scripts.phase45c1_accept --database reports/phase45c1_retry/paper_1h.sqlite3 --out reports/phase45c1_retry
```

`reports/phase45c1_retry/soak_summary.json`, `runtime_metrics.csv`, `network_audit.json`, `reconciliation.json`, `start_state.json`, 사전/사후 pytest 로그를 확인한다. 별도 `--seconds`는 진단용이며 결과가 좋아도 NOT RUN으로 표시한다. PostgreSQL 실서버는 이 단계에서 실행하지 않았으므로 기존 ENVIRONMENT_LIMITATION이다.
