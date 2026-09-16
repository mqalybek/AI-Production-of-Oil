"""Оркестрация загрузки: read -> резолюция скважины -> приведение единиц ->
upsert в measurement -> ingestion_run. Не зависит от конкретного источника —
работает с любым DataSource.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.domain.ingestion_log import IngestionRun
from src.domain.reference import MeasurementTag
from src.domain.timeseries import Measurement
from src.ingestion.base import DataSource, Period, RawRecord, SourceValidationError
from src.ingestion.matching import resolve_well_id
from src.ingestion.quarantine import quarantine
from src.ingestion.units import UnitConversionError, convert


def _json_safe(data: dict) -> dict:
    """raw-словарь может содержать numpy/pandas скаляры и NaN — приводим к
    тому, что реально сериализуется в JSONB."""
    result = {}
    for k, v in data.items():
        if isinstance(v, float) and math.isnan(v):
            result[k] = None
        elif hasattr(v, "item"):  # numpy-скаляр (int64, float64, ...)
            result[k] = v.item()
        elif hasattr(v, "isoformat"):  # datetime/Timestamp
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@dataclass
class LoadResult:
    run_id: int
    status: str
    records_read: int
    records_loaded: int
    records_quarantined: int
    error_message: str | None = None


def _tag_catalog(session: Session) -> dict[str, tuple[int, str]]:
    """code -> (id, unit) для всех тегов сразу — не гонять запрос на каждую запись."""
    rows = session.execute(select(MeasurementTag.code, MeasurementTag.id, MeasurementTag.unit)).all()
    return {code: (tag_id, unit) for code, tag_id, unit in rows}


def _upsert_measurement(
    session: Session, well_id: int, ts: dt.datetime, tag_id: int, value: float, quality: str, source: str
) -> None:
    stmt = pg_insert(Measurement).values(
        well_id=well_id, ts=ts, tag_id=tag_id, value=value, quality=quality, source=source
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Measurement.well_id, Measurement.ts, Measurement.tag_id],
        set_={"value": stmt.excluded.value, "quality": stmt.excluded.quality, "source": stmt.excluded.source},
    )
    session.execute(stmt)


def load(session: Session, source: DataSource, period: Period) -> LoadResult:
    meta = source.get_metadata()

    run = IngestionRun(
        source=meta.source,
        period_label=str(period),
        source_path=meta.path,
        started_at=dt.datetime.now(dt.timezone.utc),
        status="running",
        records_read=0,
        records_loaded=0,
        records_quarantined=0,
    )
    session.add(run)
    session.flush()  # нужен run.id для карантина

    def _finish(status: str, error_message: str | None = None) -> LoadResult:
        run.status = status
        run.error_message = error_message
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return LoadResult(
            run.id, run.status, run.records_read, run.records_loaded, run.records_quarantined, error_message
        )

    try:
        source.validate_schema()
    except SourceValidationError as exc:
        return _finish("failed", str(exc))

    tag_catalog = _tag_catalog(session)

    try:
        for raw in source.read(period):
            run.records_read += 1
            _process_record(session, run, meta.source, meta.external_system, raw, tag_catalog)
    except Exception as exc:  # источник упал целиком (битый файл целиком) — не отдельная запись
        return _finish("failed", f"ошибка чтения источника: {exc}")

    return _finish("success" if run.records_quarantined == 0 else "partial")


def _process_record(
    session: Session,
    run: IngestionRun,
    source_name: str,
    external_system: str,
    raw: RawRecord,
    tag_catalog: dict[str, tuple[int, str]],
) -> None:
    def _reject(reason: str, detail: str) -> None:
        # raw.raw — исходная строка источника (для отладки/переразбора), не вся
        # обёртка RawRecord с служебными полями
        quarantine(session, run.id, source_name, _json_safe(raw.raw), reason, detail)
        run.records_quarantined += 1

    if raw.parse_error:
        _reject("parse_error", raw.parse_error)
        return

    if not raw.external_well_id or raw.ts is None or not raw.tag or raw.value is None:
        _reject("schema_mismatch", "не заполнены обязательные поля (скважина/дата/тег/значение)")
        return

    well_id = resolve_well_id(session, external_system, raw.external_well_id)
    if well_id is None:
        _reject("unknown_well", f"UWI не найден для {external_system}:{raw.external_well_id}")
        return

    tag_info = tag_catalog.get(raw.tag)
    if tag_info is None:
        _reject("schema_mismatch", f"неизвестный тег: {raw.tag}")
        return
    tag_id, tag_unit = tag_info

    try:
        value = convert(raw.value, raw.unit or tag_unit, tag_unit)
    except UnitConversionError as exc:
        _reject("unit_conversion_error", str(exc))
        return

    _upsert_measurement(session, well_id, raw.ts, tag_id, value, quality="good", source=source_name)
    run.records_loaded += 1
