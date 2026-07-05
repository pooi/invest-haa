# HAA 자동투자용 토스증권 Open API 구현 설계

> 작성일: 2026-07-06  
> 검토 기준: 토스증권 Open API v1.1.5  
> 전략 기준: [`01_HAA.md`](./01_HAA.md)의 HAA-Balanced

## 1. 결론

**토스증권 Open API만으로 HAA 신호 계산, 보유자산 확인, 미국 ETF 매도·매수, 체결 확인까지 구현할 수 있다.**

구현에 필요한 핵심 기능이 모두 제공된다.

- 미국 ETF 10종의 수정주가 일봉 조회
- 계좌 및 보유수량 조회
- USD 매수 가능 금액 조회
- 미국 주식 시장가 매수·매도
- 소수점 매수(금액 주문)와 소수점 매도(수량 주문)
- 주문의 멱등 처리, 상태 조회, 취소
- 미국 장 운영시간 조회

다만 다음 세 가지는 API 명세만으로 확정할 수 없다.

1. **자동 환전은 구현할 수 없다.** 환율 조회 API는 있지만 환전 주문 API는 없다. 리밸런싱 전에 충분한 USD 매수 가능 금액이 있어야 하며, 원화 자동주문 가능 여부는 실계정으로 별도 확인해야 한다.
2. **과거 캔들 보존기간이 명시되어 있지 않다.** 12개월 모멘텀에는 최소 13개 월말 또는 약 253거래일의 수정주가가 필요하다. 캔들 API는 페이지당 200개이므로 페이지네이션은 가능하지만, 최초 연동 시 모든 ETF에서 충분한 과거 데이터가 반환되는지 검증해야 한다.
3. **모의투자·샌드박스가 문서에 없다.** 초기에는 주문 생성을 비활성화한 `dry-run`과 소액 실계정 검증이 필요하다.

따라서 최종 판정은 다음과 같다.

| 범위 | 판정 | 조건 |
| --- | --- | --- |
| HAA 신호 계산 | 구현 가능 | 10개 ETF의 12개월 이상 수정주가 확보 |
| 목표 비중 계산 | 구현 가능 | 보유자산과 USD 매수 가능 금액 사용 |
| 미국 ETF 자동 리밸런싱 | 구현 가능 | USD 매수 가능 금액 사전 확보 |
| 자동 환전까지 포함한 무인 운용 | 현재 명세로 불가 | 별도 환전 또는 추가 API 필요 |

## 2. 구현할 HAA 규칙

```text
Canary    = TIP
Offensive = SPY, IWM, VEA, VWO, VNQ, DBC, IEF, TLT
Defensive = IEF, BIL
Lookbacks = 1, 3, 6, 12개월
Top N     = 4
```

자산 `a`의 월말 모멘텀은 다음과 같다.

```text
R_n(a, t) = P(a, t) / P(a, t-n개월) - 1
M(a, t)   = [R_1 + R_3 + R_6 + R_12] / 4
```

- `P`는 `adjusted=true`로 받은 수정 종가다.
- 일봉을 미국 현지 거래일 기준 월별 마지막 캔들로 축약한다.
- `TIP <= 0`이면 최우수 방어자산 100%다.
- `TIP > 0`이면 공격자산 상위 4개에 슬롯당 25%를 배정한다.
- 상위 4개 중 모멘텀이 0 이하인 슬롯은 최우수 방어자산으로 대체한다.
- 같은 방어자산으로 대체된 슬롯은 합산한다.

신호에 사용한 월말 종가를 안 뒤 같은 종가로 체결할 수는 없다. 실전 시스템은 **미국 월말 정규장 종료 후 신호를 확정하고 다음 미국 영업일 정규장에 거래**한다.

## 3. 필요한 API

Base URL은 `https://openapi.tossinvest.com`이다. 토큰 발급을 제외한 API는 Bearer 토큰이 필요하고, 계좌·자산·주문 API에는 `X-Tossinvest-Account` 헤더가 추가로 필요하다.

### 3.1 필수 API

| 단계 | API | 용도 | HAA 구현 시 사용법 |
| --- | --- | --- | --- |
| 인증 | `POST /oauth2/token` | 액세스 토큰 발급 | Client Credentials, 만료 전 재발급 |
| 종목 검증 | `GET /api/v1/stocks` | 종목·시장·통화·상장상태 조회 | 10개 티커가 `ACTIVE`, USD, ETF 계열인지 시작 시 확인 |
| 가격 이력 | `GET /api/v1/candles` | 1분/일봉 OHLCV 조회 | `interval=1d&adjusted=true&count=200`, `nextBefore`로 추가 조회 |
| 현재가 | `GET /api/v1/prices` | 현재가 다건 조회 | 주문 직전 평가 및 허용오차 계산 |
| 계좌 | `GET /api/v1/accounts` | 계좌 목록 조회 | `BROKERAGE` 계좌의 `accountSeq` 선택 |
| 보유자산 | `GET /api/v1/holdings` | 보유수량·평가액 조회 | 현재 비중과 매도 수량 계산 |
| 매수여력 | `GET /api/v1/buying-power?currency=USD` | 현금 기반 USD 매수 가능 금액 | 목표 포트폴리오 총액 계산 및 과매수 방지 |
| 장 운영시간 | `GET /api/v1/market-calendar/US` | 미국 세션·휴장일 조회 | 다음 영업일 및 정규장 주문 가능 여부 판단 |
| 주문 생성 | `POST /api/v1/orders` | 매수·매도 주문 | 매도 후 매수, 모든 주문에 `clientOrderId` 부여 |
| 주문 목록 | `GET /api/v1/orders?status=OPEN|CLOSED` | 진행/종료 주문 조회 | 중복 리밸런싱 방지 및 재시작 복구 |
| 주문 상세 | `GET /api/v1/orders/{orderId}` | 체결 상태·수량·가격 조회 | 매도 체결 확인 후 매수 단계 진행 |

### 3.2 권장 API

| API | 용도 |
| --- | --- |
| `GET /api/v1/sellable-quantity` | 실제 판매 가능 수량을 매도 직전에 재확인 |
| `GET /api/v1/commissions` | 최소 주문금액·현금 버퍼와 성과 기록에 수수료 반영 |
| `POST /api/v1/orders/{orderId}/cancel` | 제한시간 내 미체결 주문 취소 |
| `GET /api/v1/exchange-rate` | 원화 기준 리포트용 참고 환율. 실제 주문 환율과 다를 수 있음 |

`orderbook`, `trades`, `price-limits`, 주문 정정 API는 시장가 기반 월 1회 전략의 MVP에는 필수가 아니다.

## 4. API 제약과 설계 반영

### 4.1 인증

- 토큰은 OAuth 2.0 Client Credentials Grant로 발급한다.
- refresh token은 없다. 만료 시 다시 발급한다.
- 예시 만료시간은 86,400초지만 응답의 `expires_in`을 신뢰한다.
- 클라이언트당 유효 토큰은 하나다. 새 토큰을 발급하면 기존 토큰은 즉시 무효화된다.
- 다중 인스턴스가 각각 토큰을 발급하지 않도록 토큰 발급 주체를 하나로 제한한다.
- `client_secret`과 토큰을 로그·DB 평문에 남기지 않는다.

### 4.2 수정주가 캔들

요청 예시는 다음과 같다.

```http
GET /api/v1/candles?symbol=TIP&interval=1d&count=200&adjusted=true
Authorization: Bearer <access_token>
```

- 페이지당 최대 200개 봉이다.
- 다음 페이지는 응답의 `nextBefore`를 `before`에 그대로 전달한다.
- 최소 13개월, 권장 400거래일을 받아 로컬 DB에 저장한다.
- 응답 가격은 JSON 문자열이므로 `float` 대신 `Decimal`로 파싱한다.
- API 응답 순서를 가정하지 않고 `timestamp`로 오름차순 정렬한다.
- 같은 `(symbol, timestamp, adjusted)`는 upsert한다.
- 수정주가가 과거 기업행동에 따라 변경될 수 있으므로 매월 최근 400거래일을 다시 동기화한다.

API는 `adjusted=true`를 지원하므로 HAA의 배당·분할 반영 가격 요건과 일치한다. 다만 명세에는 “수정주가 적용”이라고만 되어 있고 배당 및 분할의 개별 조정 방식은 설명하지 않는다. 초기 검증에서 알려진 배당락 구간을 외부 데이터와 비교하는 것이 안전하다.

### 4.3 미국 주식 소수점 주문

HAA는 25% 단위 목표 비중이므로 소수점 주문이 현금 잔여를 줄이는 데 유리하다.

- 소수점 **매수**: 미국 주식 `MARKET` + `orderAmount`(USD 금액), 정규장만 가능
- 소수점 **매도**: 미국 주식 `MARKET` + `quantity`, 소수점 6자리까지, 정규장만 가능
- 지정가 매수 수량은 정수만 가능하다.
- 금액 주문은 정규장 밖에서 `422 amount-order-outside-regular-hours`가 발생한다.

따라서 MVP는 다음처럼 주문한다.

```json
{
  "clientOrderId": "haa-20260701-SPY-buy-01",
  "symbol": "SPY",
  "side": "BUY",
  "orderType": "MARKET",
  "orderAmount": "1234.56"
}
```

```json
{
  "clientOrderId": "haa-20260701-VWO-sell-01",
  "symbol": "VWO",
  "side": "SELL",
  "orderType": "MARKET",
  "quantity": "12.345678"
}
```

`clientOrderId`는 최대 36자이며 10분간 멱등성 키로 동작한다. 네트워크 타임아웃 시 새 ID로 다시 주문하지 말고 같은 ID로 재요청한 뒤 주문 목록/상세를 조회한다. 애플리케이션 DB에서는 리밸런싱 주기 전체에 대해 별도의 유일성 제약을 둬야 한다.

### 4.4 호출 제한

문서상 주요 그룹 제한은 다음과 같다. 실제 값은 변경될 수 있으므로 응답 헤더를 우선한다.

| 그룹 | 문서상 TPS | 관련 작업 |
| --- | ---: | --- |
| `AUTH` | 5 | 토큰 발급 |
| `ACCOUNT` | 1 | 계좌 조회 |
| `ASSET` | 5 | 보유자산 조회 |
| `STOCK` | 5 | 종목 정보 |
| `MARKET_INFO` | 3 | 장 운영시간·환율 |
| `MARKET_DATA` | 10 | 현재가 |
| `MARKET_DATA_CHART` | 5 | 캔들 |
| `ORDER` | 6 | 주문 생성·취소·정정 |
| `ORDER_HISTORY` | 5 | 주문 조회 |
| `ORDER_INFO` | 6 | 매수여력·판매수량·수수료 |

`429`에서는 `Retry-After`를 따르고 지수 백오프와 jitter를 적용한다. `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`도 메트릭으로 기록한다.

## 5. 리밸런싱 실행 절차

```text
월말 종료 감지
  → 가격 동기화
  → 신호/목표비중 계산
  → dry-run 결과 저장 및 검증
  → 기존 OPEN 주문 확인
  → 보유자산·매수여력 스냅샷
  → 목표보다 많은 자산 매도
  → 매도 체결 확인
  → 보유자산·매수여력 재조회
  → 목표보다 적은 자산 매수
  → 최종 체결 확인
  → 실제 비중·잔여현금·오차 기록
```

### 5.1 실행 전 조건

다음 조건 중 하나라도 실패하면 주문하지 않는다.

- 10개 티커 모두 종목 마스터에서 조회되고 거래 가능 상태다.
- 각 티커에 신호일 포함 최소 13개 연속 월말 수정종가가 있다.
- 신호일은 모든 티커에서 동일한 미국 거래월의 마지막 거래일이다.
- 계산 결과의 목표 비중 합이 정확히 1이다.
- 해당 월의 리밸런싱이 이미 완료되지 않았다.
- HAA 티커에 미확정 `OPEN` 주문이 없다.
- 미국 정규장이고 금액/소수점 주문이 가능한 시간이다.
- kill switch가 꺼져 있고 `live-trading`이 명시적으로 활성화돼 있다.

### 5.2 총 투자금과 목표금액

HAA 전용 계좌 또는 HAA 전용 종목만 존재한다는 전제가 가장 안전하다.

```text
portfolio_usd
  = HAA 대상 보유종목의 현재 평가액 합
  + USD cashBuyingPower
  - safety_cash_buffer

target_value[symbol]
  = portfolio_usd * target_weight[symbol]
```

권장 현금 버퍼는 `max(수수료 추정액, portfolio_usd × 0.5%)`로 시작하고 실제 체결 결과에 따라 조정한다. 계좌에 HAA 외 종목이나 별도 목적 현금이 있다면 설정값 `capital_ceiling_usd`를 두고 그 범위만 운용한다.

### 5.3 주문 차이 계산

```text
delta_value[symbol] = target_value[symbol] - current_value[symbol]
```

- `delta < -tolerance`: 초과분을 수량 기반 시장가로 매도
- `delta > tolerance`: 부족분을 금액 기반 시장가로 매수
- 그 외: 거래하지 않음

권장 허용오차는 `max(5 USD, portfolio_usd × 0.25%)`다. 매도 수량은 현재가로 산출하되 `sellable-quantity`를 초과하지 않고 소수점 6자리에서 내림한다.

모든 매도를 먼저 완료해야 매수 가능 금액과 체결가가 확정된다. 부분 체결이면 완료 또는 취소가 확정될 때까지 매수 단계로 넘어가지 않는다.

## 6. 모멘텀 계산 구현

달력일에서 30·90·180·365일을 빼지 않는다. 각 티커의 미국 거래일 일봉을 월말 시계열로 변환한 뒤 행 위치 기준으로 계산한다.

```python
LOOKBACKS = (1, 3, 6, 12)

def momentum(monthly_close, symbol, signal_month):
    s = monthly_close[symbol].loc[:signal_month].dropna()
    if len(s) < 13:
        raise InsufficientHistory(symbol)

    p0 = s.iloc[-1]
    returns = [(p0 / s.iloc[-1 - n]) - 1 for n in LOOKBACKS]
    return sum(returns) / len(returns)

def target_weights(monthly_close, signal_month):
    tip = momentum(monthly_close, "TIP", signal_month)
    defensive = {s: momentum(monthly_close, s, signal_month)
                 for s in ("IEF", "BIL")}
    best_defensive = max(defensive, key=defensive.get)

    if tip <= 0:
        return {best_defensive: 1.0}

    offensive = ("SPY", "IWM", "VEA", "VWO", "VNQ", "DBC", "IEF", "TLT")
    scores = {s: momentum(monthly_close, s, signal_month) for s in offensive}
    top4 = sorted(offensive, key=lambda s: (-scores[s], s))[:4]

    weights = {}
    for symbol in top4:
        selected = symbol if scores[symbol] > 0 else best_defensive
        weights[selected] = weights.get(selected, 0) + 0.25
    return weights
```

동점일 때 결과가 매 실행마다 바뀌지 않도록 티커 오름차순을 2차 정렬 기준으로 고정한다. 모든 계산은 `Decimal`을 사용하고 DB에는 원본 가격, 신호일, 개별 수익률, 모멘텀, 순위, 최종 비중을 함께 저장한다.

## 7. 권장 시스템 구조

```text
scheduler
  └─ rebalance orchestrator
       ├─ Toss auth/client
       ├─ market-data sync
       ├─ HAA signal engine
       ├─ portfolio/reconciliation engine
       ├─ order executor
       └─ audit/alerting
```

권장 모듈 경계는 다음과 같다.

| 모듈 | 책임 |
| --- | --- |
| `toss_client` | 인증, 헤더, timeout, retry, rate limit, 응답 파싱 |
| `market_data` | 캔들 페이지네이션, 수정주가 저장, 월말 시계열 생성 |
| `strategy` | 순수 함수 형태의 HAA 모멘텀·목표비중 계산 |
| `portfolio` | 보유자산, 현금, 목표금액, 주문 차이 계산 |
| `execution` | 매도 우선, 체결 대기, 매수, 취소, 재시작 복구 |
| `repository` | 가격·신호·리밸런싱·주문·체결 audit trail |
| `scheduler` | 미국 월말 종료와 다음 영업일 실행 예약 |

최소 저장 모델은 다음과 같다.

- `daily_candles(symbol, timestamp, adjusted, OHLCV, fetched_at)`
- `signals(signal_month, symbol, r1, r3, r6, r12, momentum, rank)`
- `target_allocations(signal_month, symbol, target_weight)`
- `rebalance_runs(id, signal_month, mode, state, started_at, completed_at, error)`
- `orders(run_id, client_order_id, broker_order_id, symbol, side, requested_value_or_qty, status)`
- `executions(order_id, filled_quantity, average_price, commission, filled_at)`

`rebalance_runs.signal_month`에는 유일성 제약을 둬 같은 월의 이중 실행을 막는다.

## 8. 상태 머신과 장애 복구

```text
PLANNED
  → SELLING
  → WAITING_FOR_SELLS
  → BUYING
  → WAITING_FOR_BUYS
  → RECONCILING
  → COMPLETED

어느 단계에서든 복구 불가 오류 → HALTED
```

프로세스 재시작 시 로컬 상태만 믿지 않는다.

1. `OPEN` 주문을 조회한다.
2. 저장된 broker `orderId`의 상세를 조회한다.
3. 실제 보유자산과 USD 매수 가능 금액을 다시 읽는다.
4. 이미 체결된 수량을 반영해 남은 차이만 계산한다.
5. 사용자 확인 없이 `HALTED` 실행을 자동 재개하지 않는다.

주요 오류 처리:

| 상황 | 처리 |
| --- | --- |
| `401 expired-token` | 단일 토큰 관리자에서 1회 재발급 후 재시도 |
| `409 request-in-progress` | 같은 `clientOrderId`로 조회·재확인, 새 주문 금지 |
| `409 already-filled/canceled` | 주문 상세 조회 후 상태 수렴 |
| `422 insufficient-buying-power` | 매수 중단, 현금·체결 재조회, 자동 증액 금지 |
| `422 order-hours-closed` | 주문 중단, 다음 정규장으로 재예약 |
| `422 stock-restricted` | 전체 실행 `HALTED`, 사용자 알림 |
| `429` | `Retry-After` + 지수 백오프 + jitter |
| `5xx`/timeout | 멱등 키 유지, 주문 조회 후 제한 횟수 재시도 |

오류 로그에는 응답의 `requestId` 또는 `X-Request-Id`를 저장한다.

## 9. 운영 안전장치

- 기본 실행 모드는 항상 `dry-run`이다.
- 실주문에는 별도 환경변수 `LIVE_TRADING=true`와 계좌 allowlist를 모두 요구한다.
- 월 1회 스케줄 외 수동 재실행은 동일 `signal_month`에서 차단한다.
- 1회 주문·1일 누적 주문·포트폴리오 총액 상한을 설정한다.
- HAA 대상 10개 티커 외 주문은 코드 레벨 allowlist로 차단한다.
- 예상 목표와 실제 주문금액 차이가 설정 임계치를 넘으면 중단한다.
- 신호 데이터 결측, 비정상 가격 급변, 오래된 현재가는 주문 중단 사유다.
- 매도 체결 전 매수를 시작하지 않는다.
- 주문 전 계획, 주문 요청, 브로커 응답, 체결, 최종 비중을 변경 불가능한 audit log에 남긴다.
- 알림에는 신호, 목표비중, 주문 목록, 체결 결과, 잔여현금, 오류를 포함한다.

## 10. 테스트 및 인수 기준

### 10.1 단위 테스트

- TIP 양수/0/음수의 세 경계
- 공격자산 상위 4개 선정
- 음수 공격자산을 방어자산으로 대체하고 비중 합산
- IEF/BIL 동점과 공격자산 동점의 결정적 처리
- 13개월 미만 데이터 거부
- 월말 휴장·시차·서머타임 처리
- 소수점 수량 6자리 내림
- 목표비중 합계 1 검증

### 10.2 통합 테스트

- 10개 티커 종목 마스터 조회
- 각 티커 수정 일봉 400개 이상 페이지네이션
- `nextBefore=null` 종료 처리
- 토큰 만료와 재발급
- `429` 재시도와 헤더 기록
- 주문 타임아웃 후 같은 `clientOrderId` 재조회
- 부분 체결, 취소, 거부 상태 수렴
- 프로세스 재시작 후 중복 주문이 없는지 검증

### 10.3 실계정 단계별 출시

1. **데이터 검증**: 주문 없이 2개월 이상 신호와 목표비중만 생성한다.
2. **수동 승인**: dry-run 결과를 사람이 승인한 뒤 소액 실주문한다.
3. **제한 자동화**: 투자상한을 낮게 두고 자동 주문하되 즉시 알림한다.
4. **정상 운용**: 최소 2회 리밸런싱의 주문·복구·정산이 검증된 뒤 한도를 올린다.

완료 기준은 다음과 같다.

- 10개 ETF 모두 13개 이상 월말 수정종가를 안정적으로 확보한다.
- 같은 입력으로 항상 같은 신호와 목표비중을 생성한다.
- 매도→체결→매수 순서가 보장된다.
- timeout과 재시작에서도 중복 주문이 발생하지 않는다.
- 최종 비중이 설정한 허용오차 안에 들어온다.
- 자동 환전 없이도 운용 가능한 USD 매수 여력이 확인된다.

## 11. 구현 순서

1. 토스 API 클라이언트, 인증, rate limit, 공통 오류 처리
2. 종목 검증과 수정 일봉 수집·저장
3. 월말 변환과 HAA 순수 계산 모듈 및 단위 테스트
4. 계좌·보유자산·매수여력 기반 dry-run 리밸런싱 계획
5. 주문 상태 머신, 멱등성, 재시작 복구
6. 소액 실계정 통합 테스트
7. 스케줄러, 알림, 운영 대시보드

MVP에서는 환율 리포트, 지정가/LOC, 주문 정정, 백테스트 UI는 제외한다. 먼저 월 1회 전략의 데이터 정확성, 중복 주문 방지, 장애 복구를 완성하는 것이 우선이다.

## 12. 공식 문서

- [토스증권 Open API 문서](https://developers.tossinvest.com/docs)
- [LLM용 문서 안내](https://developers.tossinvest.com/llms.txt)
- [Open API 개요 Markdown](https://openapi.tossinvest.com/openapi-docs/overview.md)
- [OpenAPI Markdown Reference](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md)
- [OpenAPI JSON — canonical source](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)

이 문서의 엔드포인트, 필드, 주문 제한, rate limit은 2026-07-06에 내려받은 공식 OpenAPI v1.1.5를 기준으로 했다. 토스증권은 제한 수치를 운영 상황에 따라 변경할 수 있다고 명시하므로 구현 시 문서 버전을 고정하지 말고 응답 헤더와 최신 OpenAPI 명세를 함께 확인해야 한다.
