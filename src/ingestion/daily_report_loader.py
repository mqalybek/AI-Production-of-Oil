"""Оркестрация загрузки суточного рапорта: read -> резолюция скважины/объекта
-> плотность по горизонту (с явным предупреждением, если не подтверждена
или вовсе не задана) -> расчёт (src/calc/daily_report.py) -> upsert в
daily_production -> отчёты (детальный лог / суточная сводка / "требует
внимания"), как того требует бизнес-логика.

Параллельно src/ingestion/monthly_production_loader.py — тот же принцип
(карантин вместо молчаливого пропуска, IngestionRun), другая целевая
таблица и другая расчётная логика.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.calc.daily_report import (
    FieldDaySummary,
    WellDayInput,
    WellDayResult,
    attention_rows,
    compute_well_day,
    summarize_field_day,
)
from src.domain.ingestion_log import IngestionRun
from src.domain.master_data import Completion, Reservoir, Well
from src.domain.timeseries import DailyProduction
from src.ingestion.base import SourceValidationError
from src.ingestion.daily_report_source import DailyReportSource, RawDailyRecord
from src.ingestion.matching import resolve_well_id
from src.ingestion.quarantine import quarantine

logger = logging.getLogger(__name__)

DEFAULT_OIL_DENSITY_T_M3 = 0.86
DEFAULT_WATER_DENSITY_T_M3 = 1.0


def _json_safe(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if isinstance(v, float) and math.isnan(v):
            result[k] = None
        elif hasattr(v, "item"):
            result[k] = v.item()
        elif hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@dataclass
class DailyReportLoadResult:
    run_id: int
    status: str
    records_read: int
    records_loaded: int
    records_quarantined: int
    error_message: str | None
    detailed_log: list[WellDayResult]
    field_summaries: list[FieldDaySummary]
    attention: list[WellDayResult]


def _resolve_density(session: Session, well_id: int) -> tuple[float, float, bool]:
    """Плотность нефти/воды по горизонту скважины (через текущую перфорацию).
    Нет записи объекта или плотность не подтверждена по ФХИ — явный warning
    в лог, не тихий дефолт (хотя дефолт всё равно используется, чтобы не
    блокировать расчёт целиком)."""
    reservoir_id = session.execute(
        select(Completion.reservoir_id).where(Completion.well_id == well_id).limit(1)
    ).scalar_one_or_none()

    if reservoir_id is None:
        logger.warning("скважина %s: объект/горизонт не определён — плотность по умолчанию, не подтверждена", well_id)
        return DEFAULT_OIL_DENSITY_T_M3, DEFAULT_WATER_DENSITY_T_M3, False

    reservoir = session.get(Reservoir, reservoir_id)
    oil_density = reservoir.oil_density_t_m3 if reservoir.oil_density_t_m3 is not None else DEFAULT_OIL_DENSITY_T_M3
    water_density = (
        reservoir.water_density_t_m3 if reservoir.water_density_t_m3 is not None else DEFAULT_WATER_DENSITY_T_M3
    )
    if not reservoir.density_confirmed:
        logger.warning(
            "скважина %s: плотность объекта %r не подтверждена по ФХИ (нефть=%s, вода=%s)",
            well_id, reservoir.name, oil_density, water_density,
        )
    return oil_density, water_density, reservoir.density_confirmed


def _upsert_daily_production(session: Session, well_id: int, result: WellDayResult, source: str) -> None:
    values = dict(
        q_oil_t=result.q_oil_t,
        q_liquid_t=result.q_liquid_t,
        q_water_m3=result.q_water_m3,
        q_gas_m3=result.q_gas_m3,
        hours_on=result.hours_on,
        ke=result.ke,
        allocation_method=result.allocation_method,
        confidence=result.confidence,
        source=source,
    )
    stmt = pg_insert(DailyProduction).values(well_id=well_id, date=result.date, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyProduction.well_id, DailyProduction.date], set_=values
    )
    session.execute(stmt)


def load(session: Session, source: DailyReportSource) -> DailyReportLoadResult:
    meta = source.get_metadata()

    run = IngestionRun(
        source="csv",  # физически тот же CSV/Excel-рапорт, что и остальные источники
        period_label=meta["description"],
        source_path=meta["path"],
        started_at=dt.datetime.now(dt.timezone.utc),
        status="running",
        records_read=0,
        records_loaded=0,
        records_quarantined=0,
    )
    session.add(run)
    session.flush()

    def _finish(status: str, error_message: str | None = None) -> DailyReportLoadResult:
        run.status = status
        run.error_message = error_message
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return DailyReportLoadResult(
            run.id, run.status, run.records_read, run.records_loaded, run.records_quarantined,
            error_message, [], [], [],
        )

    try:
        source.validate_schema()
    except SourceValidationError as exc:
        return _finish("failed", str(exc))

    external_system = meta["external_system"]
    detailed_log: list[WellDayResult] = []

    try:
        for raw in source.read():
            run.records_read += 1
            result = _process_record(session, run, external_system, raw)
            if result is not None:
                detailed_log.append(result)
    except Exception as exc:
        return _finish("failed", f"ошибка чтения источника: {exc}")

    run.status = "success" if run.records_quarantined == 0 else "partial"
    run.finished_at = dt.datetime.now(dt.timezone.utc)
    session.flush()

    by_date: dict[dt.date, list[WellDayResult]] = defaultdict(list)
    for r in detailed_log:
        by_date[r.date].append(r)
    field_summaries = [summarize_field_day(d, rows) for d, rows in sorted(by_date.items())]

    return DailyReportLoadResult(
        run.id, run.status, run.records_read, run.records_loaded, run.records_quarantined,
        None, detailed_log, field_summaries, attention_rows(detailed_log),
    )


def _process_record(
    session: Session, run: IngestionRun, external_system: str, raw: RawDailyRecord
) -> WellDayResult | None:
    def _reject(reason: str, detail: str) -> None:
        quarantine(session, run.id, "daily_csv", _json_safe(raw.raw), reason, detail)
        run.records_quarantined += 1

    if raw.parse_error:
        _reject("parse_error", raw.parse_error)
        return None

    well_id = resolve_well_id(session, external_system, raw.external_well_id)
    if well_id is None:
        _reject("unknown_well", f"скважина не найдена для {external_system}:{raw.external_well_id}")
        return None

    oil_density, water_density, density_confirmed = _resolve_density(session, well_id)

    well_input = WellDayInput(
        well_id=well_id,
        date=raw.date,
        source_type=raw.source_type,
        hours_on=raw.values["hours_on"],
        q_liquid_m3=raw.values["q_liquid_m3"],
        water_cut_pct=raw.values["water_cut_pct"],
        q_gas_thousand_m3=raw.values.get("q_gas_thousand_m3"),
        comment=raw.comment,
        oil_density_t_m3=oil_density,
        water_density_t_m3=water_density,
        density_confirmed=density_confirmed,
    )
    result = compute_well_day(well_input)

    if result.errors:
        quarantine(session, run.id, "daily_csv", _json_safe(raw.raw), "invalid_value", result.validation_status)
        run.records_quarantined += 1
        return result

    if result.q_liquid_t is None:
        # валидные диапазоны, но source_type не указан/неизвестен — добыча
        # сознательно не посчитана, запись не пишем в daily_production
        quarantine(
            session, run.id, "daily_csv", _json_safe(raw.raw), "invalid_value",
            "; ".join(result.need_confirmation_reasons),
        )
        run.records_quarantined += 1
        return result

    _upsert_daily_production(session, well_id, result, source="daily_csv")
    run.records_loaded += 1
    return result
