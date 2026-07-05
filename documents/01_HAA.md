# 1. HAA 투자법이란?

**HAA, Hybrid Asset Allocation**은 Wouter J. Keller와 Jan Willem Keuning이 제안한 전술적 자산배분 전략입니다. 기존 BAA, Bold Asset Allocation의 후속 전략으로, 더 단순하면서도 현금 비중을 낮추고, 상승장에서는 공격적으로 투자하며, 위험 국면에서는 방어자산으로 이동하도록 설계되었습니다. 원 논문은 HAA가 **전통적 듀얼 모멘텀**과 **카나리아 모멘텀**을 결합한 전략이라고 설명합니다. ([SSRN][1])

핵심 아이디어는 다음과 같습니다.

> **TIP, 즉 물가연동채 ETF의 모멘텀이 양수이면 시장이 위험자산 투자에 유리하다고 보고 공격자산 중 강한 자산에 투자한다. TIP 모멘텀이 음수이면 위험 국면으로 보고 방어자산으로 이동한다.**

HAA는 매월 말 리밸런싱하며, 모든 자산의 모멘텀은 동일한 방식으로 계산합니다. Allocate Smartly는 HAA의 모멘텀을 **1개월, 3개월, 6개월, 12개월 수익률의 단순 평균**으로 설명합니다. ([Allocate Smartly][2])

---

# 2. HAA의 핵심 구성 요소

## 2.1 자산군

HAA-Balanced 기준으로 보통 다음 3개 유니버스를 사용합니다.

| 구분                  | 역할          | ETF 예시                                                       |
| ------------------- | ----------- | ------------------------------------------------------------ |
| Canary / Protective | 시장 위험 신호 판단 | TIP                                                          |
| Offensive           | 위험자산 후보군    | SPY, IWM, EFA 또는 VEA, EEM 또는 VWO, VNQ, DBC 또는 PDBC, IEF, TLT |
| Defensive           | 방어자산 후보군    | IEF, BIL 또는 현금성 자산                                           |

TuringTrader의 오픈소스 구현은 HAA-Balanced의 공격자산으로 **SPY, IWM, VWO, VEA, VNQ, DBC, IEF, TLT**를 사용하고, 방어자산으로 **IEF, BIL**, 카나리아 자산으로 **TIP**을 사용합니다. ([GitHub][3])

Allocate Smartly의 설명도 공격자산 유니버스를 미국 대형주, 미국 소형주, 선진국 주식, 신흥국 주식, 미국 리츠, 원자재, 중기 미국채, 장기 미국채로 설명합니다. ([Allocate Smartly][2])

---

# 3. 모멘텀 계산 방식

HAA에서 사용하는 모멘텀 점수는 다음과 같습니다.

```text
Momentum(asset, t)
= average(
    Return_1M(asset, t),
    Return_3M(asset, t),
    Return_6M(asset, t),
    Return_12M(asset, t)
  )
```

수식으로 쓰면:

```text
R_nM(asset, t) = Price(asset, t) / Price(asset, t - n months) - 1

Momentum(asset, t)
= [R_1M + R_3M + R_6M + R_12M] / 4
```

실제 구현에서는 `/4`를 하지 않고 합산값만 써도 **순위와 양수/음수 판단은 동일**합니다. TuringTrader 구현도 1, 3, 6, 12개월 수익률을 합산하는 방식으로 계산합니다. ([GitHub][3])

중요한 점은 가격 데이터로 **수정종가, adjusted close**를 사용하는 것입니다. Allocate Smartly는 계산에 dividend-adjusted closing price를 사용한다고 명시합니다. ([Allocate Smartly][4])

---

# 4. HAA-Balanced 전략 규칙

HAA-Balanced의 기본 흐름은 다음과 같습니다.

## Step 1. 매월 마지막 거래일에 모든 자산의 모멘텀 계산

대상:

```text
Canary:
- TIP

Offensive:
- SPY
- IWM
- VEA 또는 EFA
- VWO 또는 EEM
- VNQ
- DBC 또는 PDBC
- IEF
- TLT

Defensive:
- IEF
- BIL 또는 Cash
```

각 자산에 대해 1, 3, 6, 12개월 모멘텀 점수를 계산합니다.

---

## Step 2. TIP 모멘텀으로 시장 국면 판단

```text
if Momentum(TIP) > 0:
    Risk-On
else:
    Risk-Off
```

HAA는 TIP을 단일 카나리아 자산으로 사용합니다. TIP의 모멘텀이 음수이면 금리 상승, 인플레이션 상승, 주식·채권 동반 약세 가능성을 반영하는 위험 신호로 해석합니다. TrendXplorer는 HAA가 단일 카나리아 자산을 통해 시장 위험을 판단하고, 카나리아 모멘텀이 좋지 않으면 방어 투자로 전환한다고 설명합니다. ([Index Swing Trader][5])

---

## Step 3. 방어자산 중 최고 모멘텀 자산 선택

방어자산 후보:

```text
DEFENSIVE = [IEF, BIL]
```

```text
best_defensive = asset with highest Momentum among [IEF, BIL]
```

즉, 방어 국면이라고 해서 무조건 채권을 사는 것이 아니라, **IEF와 BIL 중 모멘텀이 더 강한 자산**을 선택합니다. TuringTrader 구현에서도 방어자산을 모멘텀 기준으로 정렬해 가장 높은 하나를 선택합니다. ([GitHub][3])

---

## Step 4. Risk-On이면 공격자산 상위 4개 선택

공격자산 8개를 모멘텀 기준으로 내림차순 정렬합니다.

```text
ranked_offensive = sort OFFENSIVE by Momentum descending
top_assets = top 4 assets
```

HAA-Balanced는 공격자산 8개 중 상위 절반, 즉 4개를 선택합니다. TuringTrader 구현도 공격자산 개수의 절반을 보유하도록 설정되어 있습니다. ([GitHub][3])

---

## Step 5. 선택된 공격자산의 절대 모멘텀 필터 적용

Risk-On 상태라고 해도, 상위 4개 공격자산 각각의 모멘텀이 음수이면 해당 자산은 보유하지 않습니다.

```text
for each asset in top_assets:
    if Momentum(asset) > 0:
        hold asset
    else:
        replace with best_defensive
```

이 부분이 **듀얼 모멘텀**입니다.

듀얼 모멘텀은 두 조건을 동시에 봅니다.

```text
1. Relative Momentum:
   공격자산 후보 중 상대적으로 강한가?

2. Absolute Momentum:
   자기 자신의 모멘텀이 양수인가?
```

Allocate Smartly도 HAA가 공격자산 중 모멘텀 상위 4개를 고른 뒤, 각 자산의 모멘텀이 양수이면 25%씩 투자하고, 그렇지 않으면 그 부분을 방어자산 또는 현금성 자산으로 대체한다고 설명합니다. ([Allocate Smartly][2])

---

## Step 6. Risk-Off이면 전부 방어자산으로 이동

TIP 모멘텀이 0 이하이면 공격자산을 고르지 않습니다.

```text
if Momentum(TIP) <= 0:
    portfolio = 100% best_defensive
```

TuringTrader 구현도 카나리아 자산의 모멘텀이 음수이면 선택된 공격자산 전체를 방어자산으로 대체합니다. ([GitHub][3])

---

# 5. 전체 알고리즘 의사코드

아래 의사코드는 AI가 실제 Python 코드로 구현하기 좋은 형태입니다.

```python
OFFENSIVE = ["SPY", "IWM", "VEA", "VWO", "VNQ", "DBC", "IEF", "TLT"]
DEFENSIVE = ["IEF", "BIL"]
CANARY = "TIP"

LOOKBACKS = [1, 3, 6, 12]
TOP_N = 4


def momentum(prices, ticker, date):
    """
    prices: adjusted close price DataFrame
            index = trading dates
            columns = tickers
    ticker: asset ticker
    date: rebalance date, usually month-end trading day

    return:
        average of 1, 3, 6, 12 month returns
    """
    current_price = prices.loc[date, ticker]

    scores = []
    for m in LOOKBACKS:
        past_date = get_trading_day_n_months_ago(prices.index, date, m)
        past_price = prices.loc[past_date, ticker]
        scores.append(current_price / past_price - 1)

    return sum(scores) / len(scores)


def haa_signal(prices, date):
    """
    Return target portfolio weights on rebalance date.
    """

    # 1. calculate canary momentum
    tip_mom = momentum(prices, CANARY, date)

    # 2. select best defensive asset
    defensive_moms = {
        asset: momentum(prices, asset, date)
        for asset in DEFENSIVE
    }
    best_defensive = max(defensive_moms, key=defensive_moms.get)

    # 3. risk-off regime
    if tip_mom <= 0:
        return {best_defensive: 1.0}

    # 4. risk-on regime
    offensive_moms = {
        asset: momentum(prices, asset, date)
        for asset in OFFENSIVE
    }

    ranked_offensive = sorted(
        OFFENSIVE,
        key=lambda x: offensive_moms[x],
        reverse=True
    )

    top_assets = ranked_offensive[:TOP_N]

    # 5. apply absolute momentum filter
    weights = {}

    for asset in top_assets:
        if offensive_moms[asset] > 0:
            selected_asset = asset
        else:
            selected_asset = best_defensive

        weights[selected_asset] = weights.get(selected_asset, 0.0) + 1.0 / TOP_N

    return weights
```

---

# 6. 구현 시 중요한 디테일

## 6.1 리밸런싱 시점

HAA는 **매월 마지막 거래일 종가 기준**으로 계산하고, 다음 달 말까지 포지션을 유지합니다.

```text
Rebalance date = last trading day of each month
Holding period = until next month-end
```

TuringTrader 코드 주석도 매월 마지막 거래일 종가에 모멘텀을 계산하고, 다음 달 마지막 거래일까지 보유한다고 설명합니다. ([GitHub][3])

---

## 6.2 가격 데이터

권장 데이터:

```text
Adjusted Close
```

이유:

```text
ETF 배당, 분배금, 주식분할 등을 반영해야 실제 총수익률에 가까운 모멘텀을 계산할 수 있음
```

Allocate Smartly도 모든 계산이 배당 조정 종가를 기준으로 한다고 설명합니다. ([Allocate Smartly][4])

---

## 6.3 월 단위 Lookback 처리

1개월 전, 3개월 전, 6개월 전, 12개월 전 가격을 가져올 때 단순히 `date - 30 days`처럼 계산하면 안 됩니다.

권장 방식:

```text
1. 일봉 데이터를 월말 가격 데이터로 변환
2. 각 월말 기준으로 1, 3, 6, 12개월 전 월말 가격 사용
```

예시:

```python
monthly_prices = daily_prices.resample("M").last()
```

단, 실제 거래일 기준으로는 `M`보다 `BM`, business month-end, 또는 거래소 캘린더 기반 마지막 거래일을 쓰는 것이 더 정교합니다.

---

## 6.4 신호 계산과 매매 체결 시점

백테스트에서 가장 조심해야 하는 부분입니다.

가능한 방식은 두 가지입니다.

```text
방식 A:
월말 종가로 신호 계산 → 같은 월말 종가로 리밸런싱 체결

방식 B:
월말 종가로 신호 계산 → 다음 거래일 시가 또는 종가로 체결
```

원 전략 설명은 월말 종가 기준 리밸런싱에 가깝습니다. 다만 실제 백테스트에서는 look-ahead bias를 피하기 위해 다음 거래일 체결로 구현하는 경우도 많습니다.

보수적으로 구현하려면:

```python
signal_date = month_end_date
trade_date = next_trading_day(signal_date)
```

---

# 7. HAA-Balanced의 로직을 한 문장으로 요약

```text
매월 말 TIP의 1/3/6/12개월 평균 모멘텀이 양수이면 공격자산 8개 중 모멘텀 상위 4개를 동일비중으로 보유하되, 각 자산의 모멘텀이 음수이면 그 비중을 최우수 방어자산으로 대체하고, TIP 모멘텀이 음수이면 전체 포트폴리오를 최우수 방어자산으로 이동한다.
```

---

# 8. 예시 케이스

## Case 1. TIP 모멘텀이 양수이고 공격자산 상위 4개가 모두 양수

```text
TIP momentum > 0

Top 4 offensive:
1. SPY: +8%
2. VWO: +6%
3. VNQ: +5%
4. IWM: +3%

Portfolio:
SPY 25%
VWO 25%
VNQ 25%
IWM 25%
```

---

## Case 2. TIP은 양수지만, 상위 4개 중 일부가 음수

```text
TIP momentum > 0

Top 4 offensive:
1. SPY: +5%
2. IEF: +2%
3. VNQ: -1%
4. TLT: -3%

Defensive:
IEF: +2%
BIL: +0.4%

best_defensive = IEF

Portfolio:
SPY 25%
IEF 25%
IEF 25%
IEF 25%

최종:
SPY 25%
IEF 75%
```

---

## Case 3. TIP 모멘텀이 음수

```text
TIP momentum <= 0

Defensive:
IEF: -1%
BIL: +0.3%

best_defensive = BIL

Portfolio:
BIL 100%
```

---

# 9. HAA-Simple 변형

HAA에는 더 단순한 변형도 있습니다. HAA-Simple은 공격자산을 사실상 SPY 하나로 줄인 버전입니다.

Allocate Smartly가 정리한 HAA-Simple 규칙은 다음과 같습니다. ([Allocate Smartly][4])

```text
1. 매월 말 TIP과 SPY의 1, 3, 6, 12개월 평균 모멘텀 계산
2. TIP > 0 and SPY > 0 이면 SPY 100%
3. 둘 중 하나라도 음수이면 IEF와 BIL의 모멘텀 비교
4. IEF 모멘텀이 BIL보다 높으면 IEF 100%
5. 아니면 현금 또는 BIL 100%
```

의사코드:

```python
def haa_simple_signal(prices, date):
    tip_mom = momentum(prices, "TIP", date)
    spy_mom = momentum(prices, "SPY", date)

    if tip_mom > 0 and spy_mom > 0:
        return {"SPY": 1.0}

    ief_mom = momentum(prices, "IEF", date)
    bil_mom = momentum(prices, "BIL", date)

    if ief_mom > bil_mom:
        return {"IEF": 1.0}
    else:
        return {"BIL": 1.0}
```

다만 HAA-Simple은 구현은 쉽지만, HAA-Balanced보다 자산 집중도가 높습니다. Allocate Smartly는 HAA-Simple이 HAA-Balanced보다 단순하지만, 과거 테스트 기준으로 수익률·MDD·Sharpe 등에서 HAA-Balanced가 더 좋았다고 설명합니다. ([Allocate Smartly][4])

---

# 10. HAA가 기존 듀얼 모멘텀과 다른 점

일반 듀얼 모멘텀은 보통 다음 구조입니다.

```text
1. 여러 위험자산 중 상대적으로 강한 자산 선택
2. 선택된 자산의 절대 모멘텀이 양수이면 투자
3. 아니면 채권 또는 현금 보유
```

HAA는 여기에 **포트폴리오 전체의 위험 상태를 판단하는 카나리아 필터**를 추가합니다.

```text
기존 듀얼 모멘텀:
개별 자산의 모멘텀 중심

HAA:
개별 자산 모멘텀 + TIP 기반 시장 위험 필터
```

즉, HAA는 두 단계 방어 구조입니다.

```text
1차 방어:
TIP 모멘텀이 음수이면 전체 위험자산 차단

2차 방어:
TIP이 양수여도 개별 공격자산 모멘텀이 음수이면 해당 자산만 방어자산으로 대체
```

TrendXplorer도 HAA가 듀얼 모멘텀에 카나리아 자산 기반의 포트폴리오 레벨 crash protection을 추가한 전략이라고 설명합니다. ([Index Swing Trader][5])

---

# 11. 백테스트 구현 체크리스트

AI에게 코드를 작성시키려면 아래 요구사항을 명확히 넣으면 됩니다.

```text
데이터:
- SPY, IWM, VEA, VWO, VNQ, DBC, IEF, TLT, TIP, BIL의 adjusted close 사용
- 가능한 한 월말 가격 사용

모멘텀:
- 1, 3, 6, 12개월 수익률의 단순 평균
- momentum = mean([P_t/P_t-1M - 1, P_t/P_t-3M - 1, P_t/P_t-6M - 1, P_t/P_t-12M - 1])

리밸런싱:
- 매월 마지막 거래일
- 신호는 월말 종가 기준
- 체결은 보수적으로 다음 거래일 종가 또는 시가로 처리 가능

전략:
- TIP momentum <= 0이면 defensive asset 중 momentum이 높은 자산 100%
- TIP momentum > 0이면 offensive universe에서 momentum 상위 4개 선택
- 선택된 각 공격자산이 momentum > 0이면 25% 배정
- momentum <= 0인 선택 자산은 best defensive asset으로 대체
- 동일 defensive asset으로 여러 번 대체되면 비중 합산

거래비용:
- 원 논문/구현 참고 시 0.1% 수준의 거래비용 가정 가능
- 세금은 별도 고려

성과지표:
- CAGR
- Volatility
- Sharpe Ratio
- Max Drawdown
- Monthly win rate
- Turnover
- Benchmark: 60/40, SPY buy-and-hold 등
```

---

# 12. Python 구현용 데이터 구조 예시

```python
config = {
    "offensive": ["SPY", "IWM", "VEA", "VWO", "VNQ", "DBC", "IEF", "TLT"],
    "defensive": ["IEF", "BIL"],
    "canary": "TIP",
    "lookbacks": [1, 3, 6, 12],
    "top_n": 4,
    "rebalance": "monthly",
    "price_type": "adjusted_close",
}
```

---

# 13. 코드 작성 시 흔한 실수

## 실수 1. TIP을 공격자산 후보에 넣는 것

TIP은 카나리아 자산입니다. 일반적인 HAA-Balanced에서는 TIP을 공격자산 후보로 쓰지 않습니다.

```text
TIP = 시장 위험 판단용
IEF/TLT = 공격자산 후보에도 포함 가능
IEF/BIL = 방어자산 후보
```

---

## 실수 2. TIP이 음수일 때도 공격자산을 일부 보유하는 것

HAA-Balanced에서는 TIP 모멘텀이 음수이면 전체 공격자산을 차단합니다.

```text
TIP <= 0 → 100% best defensive
```

---

## 실수 3. 공격자산 상위 4개를 고른 뒤 음수 모멘텀 필터를 빼먹는 것

HAA는 단순 relative momentum 전략이 아닙니다.

```text
상위 4개 선정 후,
각 자산의 absolute momentum도 확인해야 함
```

---

## 실수 4. 가격 데이터에 배당 조정을 반영하지 않는 것

ETF 전략에서는 배당 조정 여부에 따라 장기 백테스트 결과가 크게 달라질 수 있습니다. adjusted close를 쓰는 것이 좋습니다.

---

## 실수 5. 월말 리밸런싱에서 look-ahead bias 발생

월말 종가로 신호를 계산하면서 같은 종가 체결을 가정하면 실제 체결 가능성 논란이 생길 수 있습니다. 실전과 보수적 백테스트에서는 다음 거래일 체결을 사용하는 방식도 고려해야 합니다.

---

# 14. AI에게 코드 작성을 지시하는 프롬프트 예시

아래 프롬프트를 그대로 사용하면 됩니다.

```text
Python으로 HAA, Hybrid Asset Allocation, 전략 백테스트 코드를 작성해줘.

전략 조건:
- 사용 ETF:
  - Offensive: SPY, IWM, VEA, VWO, VNQ, DBC, IEF, TLT
  - Defensive: IEF, BIL
  - Canary: TIP
- 가격 데이터는 adjusted close를 사용
- 월말 리밸런싱
- 모멘텀은 1개월, 3개월, 6개월, 12개월 수익률의 단순 평균
- 매월 말 TIP 모멘텀이 0 이하이면 Defensive 중 모멘텀이 더 높은 자산에 100% 투자
- TIP 모멘텀이 0보다 크면 Offensive 중 모멘텀 상위 4개를 선택
- 선택된 4개 자산 각각에 대해 모멘텀이 0보다 크면 25% 투자
- 선택된 자산의 모멘텀이 0 이하이면 해당 25%를 Defensive 중 모멘텀이 더 높은 자산으로 대체
- 같은 자산이 여러 번 선택되면 비중을 합산
- 리밸런싱은 매월 마지막 거래일 기준으로 수행
- 성과지표로 CAGR, volatility, Sharpe ratio, max drawdown, 연도별 수익률을 계산
- SPY buy-and-hold와 60/40 포트폴리오를 벤치마크로 비교
- look-ahead bias를 피하기 위해 신호 계산일 다음 거래일부터 수익률을 반영
```

---

# 15. 요약

HAA는 다음처럼 이해하면 됩니다.

```text
HAA = TIP 기반 시장 위험 필터 + 공격자산 상대 모멘텀 + 개별 자산 절대 모멘텀 + 방어자산 모멘텀 선택
```

가장 중요한 구현 규칙은 이 한 줄입니다.

```text
TIP이 좋으면 공격자산 상위 4개를 사되, 나쁜 자산은 방어자산으로 대체하고, TIP이 나쁘면 전부 방어자산으로 간다.
```

HAA의 장점은 구조가 매우 단순해서 구현하기 쉽고, 주식·채권 동반 하락 같은 국면을 TIP 카나리아 신호로 회피하려 한다는 점입니다. 반면 단점은 TIP 신호에 대한 의존도가 높고, 월별 회전매매가 발생하며, 과거 TIPS 장기 데이터는 실제 ETF 이전 구간에서 시뮬레이션 가정이 들어갈 수 있다는 점입니다. Allocate Smartly도 TIPS 데이터가 1997년 이전에는 존재하지 않아 장기 시뮬레이션은 조심해서 봐야 한다고 언급합니다. ([Allocate Smartly][4])

[1]: https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4378728_code1935527.pdf?abstractid=4378728&mirid=1 "Dual and Canary Momentum with Rising Yields/Inflation: Hybrid Asset Allocation (HAA) by Wouter J. Keller, Jan Willem Keuning :: SSRN"
[2]: https://allocatesmartly.com/hybrid-asset-allocation/ "Hybrid Asset Allocation - Allocate Smartly"
[3]: https://github.com/fbertram/TuringTrader/blob/develop/BooksAndPubsV2/Keller_HAA_v2.cs "TuringTrader/BooksAndPubsV2/Keller_HAA_v2.cs at develop · fbertram/TuringTrader · GitHub"
[4]: https://allocatesmartly.com/dr-keller-keunings-simple-variation-of-hybrid-asset-allocation/ "Dr. Keller & Keuning's Simple Variation of \"Hybrid Asset Allocation\" - Allocate Smartly"
[5]: https://indexswingtrader.blogspot.com/2023/02/introducing-hybrid-asset-allocation-haa.html "TrendXplorer: Introducing Hybrid Asset Allocation (HAA)"
