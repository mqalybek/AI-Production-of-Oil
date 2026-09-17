"""Расчёт суточной добычи по скважине из суточного рапорта — чистая логика,
без БД (оркестрация — src/ingestion/daily_report_loader.py, тот же принцип,
что и в остальных src/calc/*).

Ключевое разделение (см. CLAUDE.md): "дебит" (т/сут, м3/сут) — нормированная
на 24ч интенсивность потока, "добыча за сутки" — фактический объём/масса за
календарные сутки. Как одно превращается в другое, зависит от source_type:

- "rate" (периодический замер/дебитометрия, экстраполировано на 24ч):
  добыча = дебит * (часы_работы / 24)
- "accumulated" (ГЗУ/АГЗУ/Спутник — накопительный счётчик):
  добыча = значение из источника как есть, без умножения на часы/24

Если source_type не указан — НЕ угадываем: добыча не считается (все объёмы
None), строка помечается need_confirmation.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

SOURCE_TYPES = ("rate", "accumulated")


@dataclass
class WellDayInput:
    well_id: int
    date: dt.date
    source_type: str | None  # "rate" | "accumulated" | None
    hours_on: float
    q_liquid_m3: float  # дебит жидкости по рапорту, м3/сут (или объём за сутки — см. source_type)
    water_cut_pct: float  # обводнённость, 0-100
    q_gas_thousand_m3: float | None  # дебит газа, тыс.м3/сут
    comment: str | None
    oil_density_t_m3: float
    water_density_t_m3: float
    density_confirmed: bool


@dataclass
class WellDayResult:
    well_id: int
    date: dt.date
    validation_status: str  # "OK" или список ошибок через "; "
    errors: list[str]
    need_confirmation: bool
    need_confirmation_reasons: list[str]
    hours_on: float
    ke: float | None  # часы_работы / 24, None если часы вне диапазона
    # None у всех объёмов = добыча не посчитана (ошибка валидации или нет source_type)
    q_oil_t: float | None = None
    q_liquid_t: float | None = None
    q_water_m3: float | None = None
    q_gas_m3: float | None = None
    q_liquid_m3: float | None = None  # добыча жидкости в объёме — только для отчёта (взвешенная обводнённость)
    gor_m3_t: float | None = None  # газовый фактор — только для отчёта, в daily_production не хранится
    allocation_method: str | None = None  # 'measured' (accumulated) | 'extrapolated' (rate)
    confidence: str = "low"  # 'high' если всё ОК и плотность подтверждена, иначе 'low'


def compute_well_day(inp: WellDayInput) -> WellDayResult:
    errors: list[str] = []

    if not (0 <= inp.hours_on <= 24):
        errors.append(f"часы работы вне диапазона [0,24]: {inp.hours_on}")
    if inp.q_liquid_m3 < 0:
        errors.append(f"отрицательный дебит жидкости: {inp.q_liquid_m3}")
    if not (0 <= inp.water_cut_pct <= 100):
        errors.append(f"обводнённость вне диапазона [0,100]%: {inp.water_cut_pct}")
    if inp.q_gas_thousand_m3 is not None and inp.q_gas_thousand_m3 < 0:
        errors.append(f"отрицательный дебит газа: {inp.q_gas_thousand_m3}")

    # доп. проверки, завязанные на часы работы, — только если базовые диапазоны в порядке
    if not errors:
        if inp.hours_on == 0 and inp.q_liquid_m3 != 0:
            errors.append("часы работы = 0, но дебит жидкости не равен нулю")
        if 0 < inp.hours_on < 24 and not (inp.comment and inp.comment.strip()):
            errors.append("часы работы неполные, но примечание (причина простоя/недоработки) не заполнено")

    ke = round(inp.hours_on / 24, 4) if 0 <= inp.hours_on <= 24 else None

    reasons: list[str] = []
    if inp.source_type not in SOURCE_TYPES:
        reasons.append(f"не указан source_type (ожидался один из {SOURCE_TYPES})")
    if not inp.density_confirmed:
        reasons.append("плотность не подтверждена по ФХИ — использован дефолт/незаверенное значение")
    need_confirmation = bool(reasons)

    if errors or inp.source_type not in SOURCE_TYPES:
        return WellDayResult(
            well_id=inp.well_id,
            date=inp.date,
            validation_status="; ".join(errors) if errors else "OK",
            errors=errors,
            need_confirmation=True,
            need_confirmation_reasons=reasons,
            hours_on=inp.hours_on,
            ke=ke,
        )

    water_frac = inp.water_cut_pct / 100
    oil_mass_rate_t = inp.q_liquid_m3 * (1 - water_frac) * inp.oil_density_t_m3
    water_mass_rate_t = inp.q_liquid_m3 * water_frac * inp.water_density_t_m3
    liquid_mass_rate_t = oil_mass_rate_t + water_mass_rate_t
    water_vol_rate_m3 = inp.q_liquid_m3 * water_frac
    gas_vol_rate_m3 = (inp.q_gas_thousand_m3 or 0.0) * 1000

    scale = (inp.hours_on / 24) if inp.source_type == "rate" else 1.0

    q_oil_t = round(oil_mass_rate_t * scale, 3)
    gor_m3_t = round(gas_vol_rate_m3 / q_oil_t, 2) if q_oil_t > 0 else None

    return WellDayResult(
        well_id=inp.well_id,
        date=inp.date,
        validation_status="OK",
        errors=[],
        need_confirmation=need_confirmation,
        need_confirmation_reasons=reasons,
        hours_on=inp.hours_on,
        ke=ke,
        q_oil_t=q_oil_t,
        q_liquid_t=round(liquid_mass_rate_t * scale, 3),
        q_water_m3=round(water_vol_rate_m3 * scale, 3),
        q_gas_m3=round(gas_vol_rate_m3 * scale, 3),
        q_liquid_m3=round(inp.q_liquid_m3 * scale, 3),
        gor_m3_t=gor_m3_t,
        allocation_method="measured" if inp.source_type == "accumulated" else "extrapolated",
        confidence="low" if need_confirmation else "high",
    )


@dataclass
class FieldDaySummary:
    date: dt.date
    wells_total: int
    wells_active: int
    wells_idle: int
    wells_need_confirmation: int
    q_oil_t: float
    q_liquid_t: float
    q_water_m3: float
    q_gas_m3: float
    weighted_water_cut_pct: float | None


def summarize_field_day(date: dt.date, results: list[WellDayResult]) -> FieldDaySummary:
    computed = [r for r in results if r.q_liquid_t is not None]
    total_liquid_m3 = sum(r.q_liquid_m3 or 0.0 for r in computed)
    total_water_m3 = sum(r.q_water_m3 or 0.0 for r in computed)

    return FieldDaySummary(
        date=date,
        wells_total=len(results),
        wells_active=sum(1 for r in results if r.hours_on and r.hours_on > 0),
        wells_idle=sum(1 for r in results if r.hours_on == 0),
        wells_need_confirmation=sum(1 for r in results if r.need_confirmation),
        q_oil_t=round(sum(r.q_oil_t or 0.0 for r in computed), 2),
        q_liquid_t=round(sum(r.q_liquid_t or 0.0 for r in computed), 2),
        q_water_m3=round(total_water_m3, 2),
        q_gas_m3=round(sum(r.q_gas_m3 or 0.0 for r in computed), 2),
        weighted_water_cut_pct=round(100 * total_water_m3 / total_liquid_m3, 2) if total_liquid_m3 > 0 else None,
    )


def attention_rows(results: list[WellDayResult]) -> list[WellDayResult]:
    """Строки, требующие внимания: ошибки валидации или неподтверждённые
    допущения (плотность, source_type)."""
    return [r for r in results if r.need_confirmation or r.errors]
