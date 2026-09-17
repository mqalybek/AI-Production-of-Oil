"""Оркестрация загрузки помесячной добычи: read -> резолюция скважины/объекта
-> деривация недостающих полей арифметикой -> upsert в monthly_production.

Параллельно src/ingestion/loader.py (тот пишет в measurement по tag=value),
здесь целевая таблица другая и смысл строки другой — общий только
принцип (карантин вместо молчаливого пропуска, лог в ingestion_run).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.domain.ingestion_log import IngestionRun
from src.domain.master_data import Reservoir, Well
from src.domain.monthly_production import MonthlyProduction
from src.ingestion.base import SourceValidationError
from src.ingestion.matching import resolve_well_id
from src.ingestion.monthly_production_source import MonthlyProductionSource, RawMonthlyRecord
from src.ingestion.quarantine import quarantine


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
class MonthlyLoadResult:
    run_id: int
    status: str
    records_read: int
    records_loaded: int
    records_quarantined: int
    error_message: str | None = None


def _resolve_reservoir_id(
    session: Session, field_id: int, reservoir_name: str | None, horizon_code: str | None
) -> int | None:
    if reservoir_name is None and horizon_code is None:
        return None
    q = select(Reservoir.id).where(Reservoir.field_id == field_id)
    if reservoir_name is not None:
        q = q.where(Reservoir.name == reservoir_name)
    if horizon_code is not None:
        q = q.where(Reservoir.horizon_code == horizon_code)
    return session.execute(q).scalars().first()


def _derive_values(values: dict[str, float], working_days_fallback: int) -> dict[str, float | None]:
    """Довычисляет то, что не пришло из файла напрямую — только очевидная
    арифметика (не выдумываем модель), иначе NULL. Если поле пришло из
    файла — оно в приоритете, не пересчитываем поверх источника."""
    q_oil_t = values.get("q_oil_t", 0.0)
    q_liquid_t = values["q_liquid_t"]
    calendar_days = int(values["calendar_days"])
    working_days = int(values.get("working_days", working_days_fallback))

    q_water_t = values.get("q_water_t")
    if q_water_t is None:
        q_water_t = max(0.0, q_liquid_t - q_oil_t)

    water_cut_pct = values.get("water_cut_pct")
    if water_cut_pct is None and q_liquid_t > 0:
        water_cut_pct = 100 * q_water_t / q_liquid_t

    q_oil_rate_t_d = values.get("q_oil_rate_t_d")
    if q_oil_rate_t_d is None and working_days > 0:
        q_oil_rate_t_d = q_oil_t / working_days

    return {
        "calendar_days": calendar_days,
        "working_days": working_days,
        "q_oil_t": q_oil_t,
        "q_water_t": q_water_t,
        "q_gas_m3": values.get("q_gas_m3"),
        "gor": values.get("gor"),
        "q_liquid_t": q_liquid_t,
        "water_cut_pct": water_cut_pct,
        "q_oil_rate_t_d": q_oil_rate_t_d,
    }


def _upsert(session: Session, well_id: int, reservoir_id: int | None, period_month: dt.date, fields: dict, source: str) -> None:
    stmt = pg_insert(MonthlyProduction).values(
        well_id=well_id, reservoir_id=reservoir_id, period_month=period_month, source=source, **fields
    )
    update_cols = {**fields, "reservoir_id": stmt.excluded.reservoir_id, "source": stmt.excluded.source}
    stmt = stmt.on_conflict_do_update(
        index_elements=[MonthlyProduction.well_id, MonthlyProduction.period_month],
        set_=update_cols,
    )
    session.execute(stmt)


def load(session: Session, source: MonthlyProductionSource) -> MonthlyLoadResult:
    meta = source.get_metadata()

    run = IngestionRun(
        source="csv",  # тот же физический тип файла, что и суточные рапорты
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

    def _finish(status: str, error_message: str | None = None) -> MonthlyLoadResult:
        run.status = status
        run.error_message = error_message
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return MonthlyLoadResult(
            run.id, run.status, run.records_read, run.records_loaded, run.records_quarantined, error_message
        )

    try:
        source.validate_schema()
    except SourceValidationError as exc:
        return _finish("failed", str(exc))

    external_system = meta["external_system"]

    try:
        for raw in source.read():
            run.records_read += 1
            _process_record(session, run, external_system, raw)
    except Exception as exc:
        return _finish("failed", f"ошибка чтения источника: {exc}")

    return _finish("success" if run.records_quarantined == 0 else "partial")


def _process_record(session: Session, run: IngestionRun, external_system: str, raw: RawMonthlyRecord) -> None:
    def _reject(reason: str, detail: str) -> None:
        quarantine(session, run.id, "monthly_csv", _json_safe(raw.raw), reason, detail)
        run.records_quarantined += 1

    if raw.parse_error:
        _reject("parse_error", raw.parse_error)
        return

    well_id = resolve_well_id(session, external_system, raw.external_well_id)
    if well_id is None:
        _reject("unknown_well", f"скважина не найдена для {external_system}:{raw.external_well_id}")
        return

    field_id = session.execute(select(Well.field_id).where(Well.id == well_id)).scalar_one()
    reservoir_id = _resolve_reservoir_id(
        session, field_id, raw.external_reservoir_name, raw.external_horizon_code
    )

    calendar_days = int(raw.values.get("calendar_days", 0))
    fields = _derive_values(raw.values, working_days_fallback=calendar_days)

    _upsert(session, well_id, reservoir_id, raw.period_month, fields, source="monthly_csv")
    run.records_loaded += 1
