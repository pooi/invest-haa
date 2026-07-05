# invest-haa

토스증권 OpenAPI의 조회 전용 API를 이용해 HAA 월간 신호와 가상 주문 계획을 만드는 애플리케이션입니다. 이 버전은 실제 주문 API를 호출하지 않습니다.

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

지정한 월의 월말 수정종가로 HAA 신호와 목표 비중을 계산합니다. 현재 보유자산, USD 매수 가능 금액, 현재가, 판매 가능 수량과 수수료를 조회하여 매도 우선의 가상 주문 계획을 만들고 SQLite와 Slack에 기록합니다. 실제 주문은 제출하지 않습니다.

```bash
uv run haa plan --signal-month 2026-06
uv run haa plan --signal-month 2026-06 --late
```

`--late`는 예정 시점보다 늦게 수동 생성한 계획임을 기록할 때 사용합니다. 같은 `signal-month`의 계획은 한 번만 생성할 수 있습니다.

### `haa daemon`

5분 간격으로 미국 장 운영시간을 확인하는 단일 인스턴스 데몬을 실행합니다. 다음 달 미국 정규장이 열리면 이전 월의 가격을 동기화하고 아직 처리되지 않은 HAA dry-run 계획을 한 번 생성합니다. 실패한 Slack 알림도 outbox에서 재시도합니다.

```bash
uv run haa daemon
```

### `haa runs`

최근 dry-run 실행 목록을 SQLite에서 조회합니다. 토스증권 API는 호출하지 않습니다. 기본 20건이며 최대 100건까지 지정할 수 있습니다.

```bash
uv run haa runs
uv run haa runs --limit 50
```

### `haa show-run`

실행 ID에 해당하는 신호월, 운용금액, 목표 상태와 매도·매수 순서의 가상 주문을 SQLite에서 조회합니다. 토스증권 API는 호출하지 않습니다.

```bash
uv run haa show-run <RUN_ID>
```

데이터베이스 스키마는 최초 실행 시 자동 생성됩니다. 운영 배포에서 명시적으로 마이그레이션하려면 `uv run alembic upgrade head`를 사용합니다.
