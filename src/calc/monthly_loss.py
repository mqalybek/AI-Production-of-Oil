"""Оценка потерь добычи от простоя по помесячным данным — единственное, что
можно посчитать без замеров АГЗУ и поскважинных простоев (см.
src/calc/deferred.py — та модель требует well_test/downtime, которых в
помесячных отчётах нет).

Формула: потери = дебит (т/сут, средний за отработанные дни) × число суток
простоя в месяце (calendar_days − working_days). Одна категория —
"downtime" (простой), без деления по причинам: причина простоя на уровне
месячного отчёта не фиксируется, разложение как в deferred.py тут
невозможно и не нужно.

Если working_days == 0 (скважина простояла весь месяц), своего дебита у
месяца нет — берём дебит последнего рабочего месяца (fallback_rate_t_d,
его подбирает раннер с ограничением по давности). Нет и его — потери не
оцениваем, а не гадаем на пустом месте.

Чистая математика — без обращения к БД (тестируется без сессии). Сборку
входных данных из БД делает src/calc/monthly_loss_runner.py.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class MonthlyLossInput:
    well_id: int
    period_month: dt.date
    calendar_days: int
    working_days: int
    q_oil_rate_t_d: float | None
    fallback_rate_t_d: float | None = None  # дебит последнего рабочего месяца


@dataclass
class MonthlyLossLine:
    well_id: int
    period_month: dt.date
    idle_days: int
    volume_oil_t: float


def compute_month_loss(row: MonthlyLossInput) -> MonthlyLossLine | None:
    idle_days = row.calendar_days - row.working_days
    if idle_days <= 0:
        return None
    own_rate = row.q_oil_rate_t_d if row.working_days > 0 else None
    rate = own_rate if own_rate is not None else row.fallback_rate_t_d
    if rate is None:
        return None
    return MonthlyLossLine(
        well_id=row.well_id,
        period_month=row.period_month,
        idle_days=idle_days,
        volume_oil_t=round(rate * idle_days, 2),
    )
