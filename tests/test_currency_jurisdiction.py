"""Tests for multi-currency and multi-jurisdiction handling."""

from src.core.constants import Currency, Jurisdiction, get_jurisdiction_regulations


def test_currency_enum():
    assert Currency.HKD.value == "HKD"
    assert Currency.USD.value == "USD"
    assert Currency.CNY.value == "CNY"


def test_jurisdiction_regulations():
    regs = get_jurisdiction_regulations(Jurisdiction.HONG_KONG)
    assert "SFC" in regs
    assert "AMLO" in regs
    assert "HKMA" in regs


def test_singapore_regulations():
    regs = get_jurisdiction_regulations(Jurisdiction.SINGAPORE)
    assert "MAS" in regs


def test_currency_symbols():
    assert Currency.HKD.symbol == "HK$"
    assert Currency.USD.symbol == "$"
    assert Currency.CNY.symbol == "¥"
