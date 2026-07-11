# invest-haa

토스증권 OpenAPI를 이용해 HAA 월간 신호와 주문 계획을 만들고, 선택적으로 미국 ETF 실주문을 실행하는 애플리케이션입니다. 기본값은 실제 주문을 제출하지 않는 dry-run입니다.

## 시작하기

```bash
cp .env.sample .env
uv sync --extra dev
uv run haa accounts
# 출력된 accountSeq와 나머지 설정값을 .env에 입력
uv run haa sync-prices
uv run haa validate
uv run haa plan --signal-month 2026-06
uv run haa daemon
```

`haa accounts`는 `TOSS_CLIENT_ID`와 `TOSS_CLIENT_SECRET`만으로 계좌 식별값을 조회합니다. 확인한 `BROKERAGE` 계좌의 `accountSeq`를 `TOSS_ACCOUNT_SEQ`에 설정합니다. 모든 API 사용 명령은 단일 프로세스 잠금을 사용하므로 데몬 실행 중에는 별도로 실행할 수 없습니다.

## 명령어

### `haa accounts`

토스증권에서 접근 가능한 계좌의 `accountSeq`와 계좌 유형을 조회합니다. 다른 설정값을 채우기 전에 `TOSS_ACCOUNT_SEQ`를 확인할 때 사용합니다. 새 액세스 토큰을 발급하므로 같은 클라이언트의 기존 토큰은 무효화될 수 있습니다.

```bash
uv run haa accounts
```

### `haa sync-prices`

HAA 대상 ETF 10종이 거래 가능한 USD ETF인지 검증하고, 종목별 최근 400거래일의 수정 일봉을 가져와 SQLite에 upsert합니다. 기존 데이터도 다시 조회하여 배당이나 분할로 변경된 수정주가를 갱신합니다.

```bash
uv run haa sync-prices
```

### `haa validate`

환경설정, `BROKERAGE` 계좌, 대상 ETF, 저장된 가격 이력을 검사합니다. 최신 완료 월을 기준으로 13개월의 공통 월말 데이터가 있어 실제 신호를 계산할 수 있는지도 확인합니다. 준비되지 않은 경우 진단 결과를 출력하고 종료 코드 `1`을 반환합니다.

```bash
uv run haa validate
```

### `haa plan`

지정한 월의 월말 수정종가로 HAA 신호와 목표 비중을 계산합니다. 현재 보유자산, USD 매수 가능 금액, 현재가, 판매 가능 수량과 수수료를 조회하여 매도 우선 주문 계획을 만들고 SQLite와 Slack에 기록합니다. 이전 달의 목표 비중이 있으면 전월말부터 당월말까지의 수정종가 수익률을 적용한 전략 월간 수익률과 종목별 기여도도 Slack에 함께 기록합니다. 최초 실행은 비교할 이전 목표 비중이 없으므로 다음 달부터 실적을 산출합니다. `LIVE_TRADING=false`이면 계획만 저장하고, `true`이면 매도 체결 후 매수를 순서대로 실행합니다.

```bash
uv run haa plan --signal-month 2026-06
uv run haa plan --signal-month 2026-06 --late
```

`--late`는 예정 시점보다 늦게 수동 생성한 계획임을 기록할 때 사용합니다. 같은 `signal-month`의 계획은 한 번만 생성할 수 있습니다.

## 운용 금액과 실행 시점

`CAPITAL_CEILING_USD`는 매월 새로 투자하는 금액이 아니라 HAA 전략이 운용할 **총자산의 최대 한도**입니다. 실제 운용 기준 금액은 다음과 같이 계산하며, 여기서 수수료를 고려한 현금 버퍼를 추가로 남깁니다.

```text
운용 기준 금액
= min(
    CAPITAL_CEILING_USD,
    HAA 대상 ETF 평가액 + USD 매수 가능 금액
  )
```

예를 들어 계좌에 USD 1,000을 넣고 `CAPITAL_CEILING_USD=2000`으로 설정하면 처음에는 약 USD 1,000으로 시작합니다. 이후 수익은 다음 달 운용 금액에 포함되어 복리로 재투자되며, 운용 자산이 USD 2,000을 넘으면 최대 USD 2,000까지만 전략에 배정합니다. 손실로 자산이 USD 900이 되고 별도 USD 현금이 없다면 다음 달에는 약 USD 900을 기준으로 운용합니다.

`MAX_SINGLE_ORDER_USD`는 운용 총액이나 월 납입액이 아니라 **주문 한 건의 최대 허용 금액**입니다. 예를 들어 `MAX_SINGLE_ORDER_USD=1000`이면 매수 또는 매도 주문 한 건의 예상 금액이 USD 1,000을 초과할 때 실행을 중단합니다.

HAA 신호와 실제 주문의 기준 시점은 서로 다릅니다.

```text
매월 마지막 미국 거래일 장 마감
→ 해당 월말 수정종가로 HAA 신호 확정
→ 다음 달 첫 번째 미국 거래일 정규장에 리밸런싱
→ 다음 리밸런싱까지 보유
```

따라서 신호는 매월 말 기준으로 계산하고, 실제 주문은 다음 달 초에 실행합니다. 데몬이 첫 거래일에 실행되지 못했다면 이후 정규장에서 실행하고 해당 실행을 `late=true`로 기록합니다.

## 실주문 활성화

먼저 dry-run 결과와 계좌를 확인한 뒤 `.env`에 다음 값을 설정합니다.

```dotenv
LIVE_TRADING=true
LIVE_TRADING_ACCOUNT_SEQ=123456
MAX_SINGLE_ORDER_USD=1000
ORDER_FILL_TIMEOUT_SECONDS=120
ORDER_STATUS_POLL_SECONDS=2
```

`LIVE_TRADING_ACCOUNT_SEQ`는 `TOSS_ACCOUNT_SEQ`와 정확히 같아야 합니다. 주문 하나의 예상 금액이 `MAX_SINGLE_ORDER_USD`를 넘으면 전체 실행을 중단합니다. 실주문은 미국 정규장에서만 가능하며 다음 순서를 따릅니다.

```text
매도 주문 → 매도 체결 확인 → USD 매수 가능 금액 재조회
→ 매수 주문 → 매수 체결 확인 → 완료
```

주문이 거부·취소되거나 제한시간 안에 체결되지 않으면 실행 상태를 `HALTED`로 기록합니다. 시간 초과 주문에는 취소 요청을 제출합니다. 자동 환전은 지원하지 않으므로 계좌에 충분한 USD 매수 가능 금액이 있어야 합니다.

```bash
uv run haa validate
uv run haa plan --signal-month 2026-06
uv run haa show-run <RUN_ID>
```

### `haa daemon`

5분 간격으로 미국 장 운영시간을 확인하는 단일 인스턴스 데몬을 실행합니다. 다음 달 미국 정규장이 열리면 이전 월의 가격을 동기화하고 아직 처리되지 않은 HAA 계획을 한 번 생성합니다. `LIVE_TRADING=true`이면 이어서 실주문을 실행합니다. 실패한 Slack 알림도 outbox에서 재시도합니다.

```bash
uv run haa daemon
```

명령을 실행한 프로세스와 서버가 계속 살아 있는 동안에는 월간 실행을 자동으로 확인합니다. 터미널 종료나 서버 재부팅에도 자동으로 복구하려면 `systemd`, Docker restart policy 또는 Supervisor 같은 프로세스 관리 도구로 데몬을 등록해야 합니다. 주문 실패로 실행이 `HALTED`된 경우에는 자동 재시도하지 않으므로 Slack 알림과 실행 상태를 확인해야 합니다.

### `haa runs`

최근 dry-run 또는 실주문 실행 목록을 SQLite에서 조회합니다. 토스증권 API는 호출하지 않습니다. 기본 20건이며 최대 100건까지 지정할 수 있습니다.

```bash
uv run haa runs
uv run haa runs --limit 50
```

### `haa show-run`

실행 ID에 해당하는 신호월, 운용금액, 목표 상태, 주문 계획과 실주문 체결 결과를 SQLite에서 조회합니다. 토스증권 API는 호출하지 않습니다.

```bash
uv run haa show-run <RUN_ID>
```

데이터베이스 스키마는 최초 실행 시 자동 생성됩니다. 운영 배포에서 명시적으로 마이그레이션하려면 `uv run alembic upgrade head`를 사용합니다.
