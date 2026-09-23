"""Оценка потерь добычи от простоя по помесячным данным — единственное, что
можно посчитать без замеров АГЗУ и поскважинных простоев (см.
src/calc/deferred.py — та модель требует well_test/downtime, которых в
помесячных отчётах нет).

Формула: потери = дебит (т/сут, средний за отработанные дни) × число суток
простоя в месяце (calendar_days − working_days). Одна категория —
"downtime" (простой), без деления по причинам: причина простоя на уровне
месячного отчёта не фиксируется, разложение как в deferred.py тут
невозможно и не нужно.

Если working_days == 0 (скважина простояла весь месяц) — дебита посчитать
не из чего, потери не оцениваем (не гадаем на пустом месте), строка просто
не попадает в отчёт.

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


@dataclass
class MonthlyLossLine:
    well_id: int
    period_month: dt.date
    idle_days: int
    volume_oil_t: float


def compute_month_loss(row: MonthlyLossInput) -> MonthlyLossLine | None:
    idle_days = row.calendar_days - row.working_days
    if idle_days <= 0 or row.q_oil_rate_t_d is None:
        return None
    return MonthlyLossLine(
        well_id=row.well_id,
        period_month=row.period_month,
        idle_days=idle_days,
        volume_oil_t=round(row.q_oil_rate_t_d * idle_days, 2),
    )
