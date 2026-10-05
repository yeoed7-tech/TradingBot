# Phase 4.5 Soak 관측

## 실행

```bash
python -m scripts.soak_paper --hours 1 --quote-source websocket --database data/database/soak.sqlite3 --out reports/soak_1h
python -m scripts.soak_paper --hours 6 --quote-source websocket --database data/database/soak6.sqlite3 --out reports/soak_6h
python -m scripts.soak_paper --hours 24 --quote-source websocket --database data/database/soak24.sqlite3 --out reports/soak_24h
```

Work에서 실제 진행한 공개 REST fallback 관측:

```bash
python -m scripts.soak_paper --seconds 90 --quote-source rest --database /tmp/phase45_soak.sqlite3 --out reports/phase45_soak --sample-seconds 15
```

결과: **PARTIAL**, 실제 92.00초, 7개 sample, 정상 Feed event 24건, 완료봉 122개,
공개 HTTP 요청 29회 성공, 가상 주문/체결 0건, 실제 주문 HTTP 0건.
첫/끝 RSS 184,086,528 → 184,250,368 B (+163,840 B), DB 151,552 → 151,552 B,
로그 21,263 → 23,366 B, portfolio snapshot 2 → 25. 90초 결과만으로 1/6/24시간의
메모리/DB 안정성을 주장할 수 없다. 결과 원본은 `reports/phase45_soak/soak.json`.

Runner는 RSS, DB/log 크기, 테이블 건수, public request audit, Feed gap/stale/normal,
WebSocket reconnect, risk/order/fill 및 exception 상태를 JSON으로 남긴다.
초기 probe는 handshake timeout이었다. 이후 60초 시도는 WS 연결·가상 주문/체결에 성공했지만
오래된 메시지 backlog로 stale 중단했다. 최신 호가 한 건만 보존하는 읽기 루프 수정 후:

```bash
python -m scripts.soak_paper --seconds 95 --quote-source websocket --database /tmp/phase45_ws_fixed.sqlite3 --out reports/phase45_ws_fixed --sample-seconds 15
```

실제 97.00초, 7 sample, 정상 23 event, 완료봉 121개, 가상 주문·체결 각 1,
stale/gap 0, 공개 REST API 4/4 성공, WebSocket reconnect 0, 실제 주문 HTTP 0.
RSS 183,353,344→184,623,104 B, DB 131,072→151,552 B, 로그 25,037→26,188 B.
초기 워밍업이 포함되므로 시작/끝 증가를 메모리 누수로 해석하지 않는다.
`reports/phase45_ws_fixed/soak.json`에 원본이 있다. 긴 WebSocket 연속 관측은 **PARTIAL**이다. 로컬에서 위 명령을 실행해 결과를 추가한다.

## 동일 DB 재시작 관측

첫 WebSocket 97초 실행 DB에 두 번째 70초 실행을 연결했다. 실제 72초 NORMAL,
완료 봉 121→123, 주문·체결 DB 건수 각각 1→1, 실주문 0.
원본은 `reports/phase45_ws_restart/soak.json`이다. 첫 프로세스는 정상 종료했다.

## Phase 4.5-B 계측과 실행 범위

`python -m scripts.soak_paper --hours 1|6|24 --quote-source websocket --database /tmp/<별도파일>.sqlite3 --out reports/<별도디렉터리>`를 한 번씩 실행한다. JSON은 start/end/duration, RSS min/max/delta, DB/log size, 테이블 counts, signals/orders/fills, reconnect/stale/gap/duplicate, 예외/risk, lease token, 최종 Decimal cash/equity/total PnL, 주문 HTTP 호출 수를 포함한다. RSS 초기 값은 모듈 로딩과 연결 초기화에 영향을 받으므로 안정화 후 sample들의 기울기도 살핀다.

이번 세션에 실제 실행한 것은 **82초 공개 WebSocket Paper smoke**뿐이다. `reports/phase45b_ws_smoke/soak.json`: NORMAL 17 events, order/fill 각 1, stale/gap 0, 공개 REST 시도 4건, 주문 HTTP 0, RSS 범위 152,326,144~186,081,280B. 1/6/24시간은 **NOT RUN**이며 가속 테스트 결과를 장시간 관측으로 대신하지 않는다. 100,000 market journal event, 12,000회 Decimal 체결, 2,000건 SQLite 원장/최근 100건 복원 자동 테스트를 별도로 실행했다.

## C1 전용 한 명령 실행

`python -m scripts.phase45c1_accept --database reports/phase45c1_retry/paper_1h.sqlite3 --out reports/phase45c1_retry`는 124개 전체 회귀를 전후로 실행하고 별도 Public WS Paper 프로세스의 자체 RSS/CPU 계측을 `runtime_self.jsonl`에서 수집한다. 별도 PID의 `/proc/<pid>`가 Work의 namespace와 일치하지 않을 수 있으므로 타 프로세스 RSS를 그 경로로 추정하지 않는다. 시작 상태, 30초 간격 DB/lease/heartbeat, 최종 독립 Decimal 재계산과 audit 파일을 만든다. 이미 존재하는 DB는 거부한다. `--seconds`는 짧은 진단 전용이며 1시간 판정은 NOT RUN이다.

Work 내 첫 시도는 약 47분 뒤 exec-server/workspace reset으로 최종 원시 파일을 잃었다. **C1 완료로 표시하지 않는다.** 위 명령은 프로세스를 1시간 이상 유지할 수 있는 로컬/VM에서 실행한다.
