"""Tests for covenant/ratio monitoring."""

from src.agents.covenant import CovenantMonitor


def test_check_compliant():
    monitor = CovenantMonitor()
    result = monitor.check_covenants(
        company="Acme Corp",
        ratios={"debt_ebitda": 2.5, "current_ratio": 1.8},
        covenants={"debt_ebitda": {"max": 3.0}, "current_ratio": {"min": 1.2}},
    )
    assert result["compliant"] is True
    assert len(result["breaches"]) == 0


def test_check_breach():
    monitor = CovenantMonitor()
    result = monitor.check_covenants(
        company="Acme Corp",
        ratios={"debt_ebitda": 4.5, "current_ratio": 0.8},
        covenants={"debt_ebitda": {"max": 3.0}, "current_ratio": {"min": 1.2}},
    )
    assert result["compliant"] is False
    assert len(result["breaches"]) == 2


def test_breach_risk_level():
    monitor = CovenantMonitor()
    result = monitor.check_covenants(
        company="Acme Corp",
        ratios={"debt_ebitda": 2.8},  # Close to 3.0 max
        covenants={"debt_ebitda": {"max": 3.0}},
    )
    assert result["compliant"] is True
    assert len(result["warnings"]) > 0  # Within 10% of threshold


def test_empty_covenants():
    monitor = CovenantMonitor()
    result = monitor.check_covenants(
        company="Acme Corp",
        ratios={"debt_ebitda": 5.0},
        covenants={},
    )
    assert result["compliant"] is True
