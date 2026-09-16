import pytest

from src.ingestion.units import UnitConversionError, convert


def test_bar_to_atm():
    assert convert(1.0, "bar", "атм") == pytest.approx(0.986923)


def test_psi_to_atm():
    assert convert(100.0, "psi", "атм") == pytest.approx(6.80459)


def test_identity_when_already_target_unit():
    assert convert(18.4, "т/сут", "т/сут") == 18.4
    assert convert(15.0, "atm", "атм") == 15.0


def test_unknown_unit_raises():
    with pytest.raises(UnitConversionError):
        convert(1.0, "бочки/сут", "т/сут")


def test_no_conversion_rule_between_families_raises():
    with pytest.raises(UnitConversionError):
        convert(1.0, "т/сут", "атм")
