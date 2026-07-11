from decimal import Decimal

import httpx
import pytest

from invest_haa.toss import TossApiError, TossClient


def response(request: httpx.Request, status: int, payload: dict, headers: dict | None = None):
    return httpx.Response(status, json=payload, headers=headers, request=request)


def test_token_and_decimal_price_parsing(settings):
    paths = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        if request.url.path == "/oauth2/token":
            return response(request, 200, {"access_token": "secret-token", "expires_in": 86400})
        assert request.headers["Authorization"] == "Bearer secret-token"
        return response(
            request,
            200,
            {"result": [{"symbol": "SPY", "timestamp": None, "lastPrice": "621.1234", "currency": "USD"}]},
        )

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    toss = TossClient(settings, client=client)
    prices = toss.prices(("SPY",))
    assert str(prices["SPY"].last_price) == "621.1234"
    assert paths == ["/oauth2/token", "/api/v1/prices"]


def test_429_uses_retry_and_reuses_token(settings):
    price_calls = 0
    sleeps = []

    def handler(request: httpx.Request):
        nonlocal price_calls
        if request.url.path == "/oauth2/token":
            return response(request, 200, {"access_token": "token", "expires_in": 86400})
        price_calls += 1
        if price_calls == 1:
            return response(
                request,
                429,
                {"error": {"code": "rate-limit-exceeded", "message": "slow"}},
                {"Retry-After": "2"},
            )
        return response(request, 200, {"result": []})

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    TossClient(settings, client=client, sleep=sleeps.append).prices(("SPY",))
    assert price_calls == 2
    assert sleeps == [2.0]


def test_token_429_is_retried(settings):
    token_calls = 0
    sleeps = []

    def handler(request: httpx.Request):
        nonlocal token_calls
        if request.url.path == "/oauth2/token":
            token_calls += 1
            if token_calls == 1:
                return response(
                    request,
                    429,
                    {"error": {"code": "rate-limit-exceeded", "message": "slow"}},
                    {"Retry-After": "3"},
                )
            return response(request, 200, {"access_token": "token", "expires_in": 86400})
        return response(request, 200, {"result": []})

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    TossClient(settings, client=client, sleep=sleeps.append).prices(("SPY",))
    assert token_calls == 2
    assert sleeps == [3.0]


def test_expired_token_is_refreshed_once(settings):
    token_count = 0
    price_count = 0

    def handler(request: httpx.Request):
        nonlocal token_count, price_count
        if request.url.path == "/oauth2/token":
            token_count += 1
            return response(request, 200, {"access_token": f"token-{token_count}", "expires_in": 86400})
        price_count += 1
        if price_count == 1:
            return response(request, 401, {"error": {"code": "expired-token", "message": "expired"}})
        assert request.headers["Authorization"] == "Bearer token-2"
        return response(request, 200, {"result": []})

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    TossClient(settings, client=client).prices(("SPY",))
    assert token_count == 2


def test_market_order_uses_account_header_and_idempotency_key(settings):
    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            return response(request, 200, {"access_token": "token", "expires_in": 86400})
        assert request.method == "POST"
        assert request.headers["X-Tossinvest-Account"] == "1"
        assert request.read().decode().count('"clientOrderId":"haa-202606-01-SPY-sell"') == 1
        return response(request, 200, {"result": {"orderId": "order-1"}})

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    order_id = TossClient(settings, client=client).create_market_order(
        client_order_id="haa-202606-01-SPY-sell",
        symbol="SPY",
        side="SELL",
        quantity=Decimal("1.5"),
    )
    assert order_id == "order-1"


def test_api_error_captures_request_id(settings):
    def handler(request: httpx.Request):
        if request.url.path == "/oauth2/token":
            return response(request, 200, {"access_token": "token", "expires_in": 86400})
        return response(
            request,
            400,
            {"error": {"code": "invalid-request", "message": "bad", "requestId": "req-1"}},
        )

    client = httpx.Client(base_url=settings.toss_base_url, transport=httpx.MockTransport(handler))
    with pytest.raises(TossApiError) as error:
        TossClient(settings, client=client).prices(("SPY",))
    assert error.value.request_id == "req-1"
