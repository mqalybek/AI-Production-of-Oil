"""Приведение единиц измерения к внутреннему стандарту (как хранится в
measurement_tag.unit): атм, т/сут, м3/сут, ч, %, А, Гц.
"""

from __future__ import annotations

import re


class UnitConversionError(Exception):
    pass


# алиас единицы (как её может назвать источник) -> канонический код
_UNIT_ALIASES: dict[str, str] = {
    "атм": "atm", "ата": "atm", "atm": "atm",
    "бар": "bar", "bar": "bar",
    "psi": "psi", "фунт/кв.дюйм": "psi",
    "т/сут": "t_d", "тонн/сут": "t_d", "t/d": "t_d", "t/day": "t_d",
    "м3/сут": "m3_d", "куб.м/сут": "m3_d", "m3/d": "m3_d", "m3/day": "m3_d",
    "%": "pct", "pct": "pct", "проценты": "pct",
    "ч": "h", "час": "h", "h": "h", "hour": "h",
    "а": "a", "a": "a", "ампер": "a",
    "гц": "hz", "hz": "hz",
}

# единица measurement_tag.unit (как хранится в БД) -> канонический код
_TAG_UNIT_CANONICAL: dict[str, str] = {
    "атм": "atm",
    "т/сут": "t_d",
    "м3/сут": "m3_d",
    "ч": "h",
    "%": "pct",
    "а": "a",
    "гц": "hz",
}

# конвертация в атмосферы — единственное семейство, где источники реально
# расходятся (давление часто приходит в барах/psi)
_TO_ATM: dict[str, float] = {
    "atm": 1.0,
    "bar": 0.986923,
    "psi": 0.0680459,
}


def _normalize(unit: str) -> str:
    return re.sub(r"\s+", "", unit.strip().lower())


def to_canonical(unit: str) -> str | None:
    return _UNIT_ALIASES.get(_normalize(unit))


def convert(value: float, from_unit: str, tag_unit: str) -> float:
    """Приводит value из from_unit (как задано в маппинге источника) к
    tag_unit — единице, в которой тег хранится в measurement_tag.

    Бросает UnitConversionError, если не знаем, как привести одно к другому.
    """
    from_canon = to_canonical(from_unit)
    tag_canon = _TAG_UNIT_CANONICAL.get(_normalize(tag_unit))

    if from_canon is None:
        raise UnitConversionError(f"неизвестная единица измерения: {from_unit!r}")
    if tag_canon is None:
        raise UnitConversionError(f"неизвестная целевая единица тега: {tag_unit!r}")

    if from_canon == tag_canon:
        return value

    if tag_canon == "atm" and from_canon in _TO_ATM:
        return value * _TO_ATM[from_canon]

    raise UnitConversionError(f"нет правила конвертации {from_unit!r} -> {tag_unit!r}")
