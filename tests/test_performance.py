from decimal import Decimal

import pytest

from invest_haa.performance import calculate_monthly_performance


def test_monthly_performance_uses_previous_weights_and_adjusted_closes():
    result = calculate_monthly_performance(
        {
            "SPY": {"2026-05": Decimal("100"), "2026-06": Decimal("110")},
            "IEF": {"2026-05": Decimal("100"), "2026-06": Decimal("98")},
        },
        "2026-06",
        {"SPY": Decimal("0.75"), "IEF": Decimal("0.25")},
    )

    assert result.total_return == Decimal("0.070")
    assert result.asset_returns == {"SPY": Decimal("0.1"), "IEF": Decimal("-0.02")}
    assert result.contributions == {"SPY": Decimal("0.075"), "IEF": Decimal("-0.005")}


def test_monthly_performance_rejects_incomplete_weights():
    with pytest.raises(ValueError, match="total exactly 1"):
        calculate_monthly_performance(
            {"SPY": {"2026-05": Decimal("100"), "2026-06": Decimal("110")}},
            "2026-06",
            {"SPY": Decimal("0.5")},
        )
