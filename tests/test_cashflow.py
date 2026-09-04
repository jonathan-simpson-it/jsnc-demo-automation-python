"""Tests for cash flow forecasting."""

from src.agents.cashflow import CashFlowForecaster


def test_basic_forecast():
    forecaster = CashFlowForecaster()
    result = forecaster.forecast(
        historical=[{"month": "2024-01", "revenue": 100000, "expenses": 80000}],
        periods=3,
        growth_rate=0.10,
    )
    assert len(result["projections"]) == 3
    # Period 1: revenue = 100000 * 1.10 = 110000
    assert result["projections"][0]["revenue"] == 110000.0
    # Period 2: revenue = 100000 * 1.10^2 = 121000
    assert result["projections"][1]["revenue"] == 121000.0
    # Period 3: revenue = 100000 * 1.10^3 = 133100
    assert result["projections"][2]["revenue"] == 133100.0


def test_forecast_empty():
    forecaster = CashFlowForecaster()
    result = forecaster.forecast(historical=[], periods=12, growth_rate=0.05)
    assert result["projections"] == []
    assert result["summary"] == {}


def test_forecast_summary():
    forecaster = CashFlowForecaster()
    result = forecaster.forecast(
        historical=[{"month": "2024-01", "revenue": 100000, "expenses": 80000}],
        periods=12,
        growth_rate=0.05,
    )
    assert result["summary"]["periods"] == 12
    assert result["summary"]["growth_rate"] == 0.05
    assert result["summary"]["total_revenue"] > 0
    assert result["summary"]["total_expenses"] > 0
    assert result["summary"]["total_net_cash_flow"] > 0
