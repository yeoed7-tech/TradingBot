# 공개 시세 연결 수정 — v0.2.1

휴대폰 연결 설정 문제가 아니다. 이 Python 애플리케이션이 실행되는 Work 서버의 HTTP 클라이언트 설정 문제였다.

## 원인과 수정

독립 진단에서 CCXT 기본 설정은 직접 DNS 조회에서 실패했고, 환경 프록시만 적용하면 인증서 검증에서 실패했다.
환경 프록시와 시스템 신뢰 인증서를 함께 사용했을 때 공개 ticker 조회가 성공했다.
분류: `CLIENT_PROXY_AND_CA_CONFIGURATION_MISMATCH`.
전체 Public API 접근 불가인 `ENVIRONMENT_NETWORK_LIMITATION`으로 분류할 증거는 없었다.

`GuardedUpbit`가 다음 설정을 사용하도록 수정했다.

- `aiohttp_trust_env=True`: 실행 서버에 설정된 환경 프록시를 존중한다.
- `ssl_context=ssl.create_default_context()`: 시스템 신뢰 CA로 인증서와 호스트명을 검증한다.
- 요청 timeout 기본값을 8초에서 15초로 조정한다. 재시도 횟수와 위험·stale 기준은 유지한다.
- TOML의 `network_trust_env`, 선택적 `ca_bundle_path`로 운영 환경별 설정을 분리한다.

TLS 검증 비활성화, 프록시 우회, API Key 추가, 휴대폰 설정 변경은 하지 않았다.
잘못된 사용자 지정 CA 경로에서는 즉시 실패하며 비보안 연결로 fallback하지 않는다.
공개 GET allowlist와 실제 주문 차단 구조는 유지한다.

## 로컬에서 검증

프로젝트 루트에서:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m scripts.public_integration --duration 180 --out reports/local_public_check
```

API Key 없이 업비트 공개 REST 데이터만 사용하며 모든 주문은 SimulationBroker에서 가상 처리한다.
프록시가 없는 일반 환경에서는 시스템 기본 직접 연결을 사용한다.
프록시 주소·인증정보는 코드나 보고서에 넣지 않는다.
사설 CA가 필요한 환경은 관리자가 제공한 신뢰 번들을 `ca_bundle_path`에 지정한다.

동봉한 `tools/upbit_connection_diagnostics.zip`에는 DNS/TLS/REST/WebSocket 최소 검증 스크립트와
exception chain, HTTP status/body, close code, 재시도 횟수, raw payload 기록이 있다.
이 플랫폼의 Realtime Feed는 REST polling이며 WebSocket 운영 Feed를 추가한 것은 아니다.

수정 후 실행 결과와 범위 판정은 TEST_REPORT.md 및 ROADMAP.md를 참조한다.
