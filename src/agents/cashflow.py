"""Cash flow forecasting for SME financial workflow.

SME FIs frequently need working capital / cash flow visibility,
not just deal-stage document analysis.
"""

from __future__ import annotations


class CashFlowForecaster:
    """Project cash flow based on historical data and growth assumptions."""

    def forecast(
        self,
        historical: list[dict],
        periods: int = 12,
        growth_rate: float = 0.05,
        expense_growth: float | None = None,
    ) -> dict:
        """Project future cash flow from historical data.

        Args:
            historical: List of dicts with month, revenue, expenses.
            periods: Number of future periods to project.
            growth_rate: Revenue growth rate per period (e.g., 0.05 = 5%).
            expense_growth: Expense growth rate (defaults to revenue growth).

        Returns:
            Dict with projections list and summary.
        """
        if not historical:
            return {"projections": [], "summary": {}}

        if expense_growth is None:
            expense_growth = growth_rate

        last = historical[-1]
        projections = []

        for i in range(1, periods + 1):
            revenue = last["revenue"] * (1 + growth_rate) ** i
            expenses = last["expenses"] * (1 + expense_growth) ** i
            net_cash_flow = revenue - expenses
            projections.append({
                "period": i,
                "revenue": round(revenue, 2),
                "expenses": round(expenses, 2),
                "net_cash_flow": round(net_cash_flow, 2),
            })

        total_revenue = sum(p["revenue"] for p in projections)
        total_expenses = sum(p["expenses"] for p in projections)
        total_net = sum(p["net_cash_flow"] for p in projections)

        return {
            "projections": projections,
            "summary": {
                "total_revenue": round(total_revenue, 2),
                "total_expenses": round(total_expenses, 2),
                "total_net_cash_flow": round(total_net, 2),
                "periods": periods,
                "growth_rate": growth_rate,
            },
        }
