"""Загрузка суточного рапорта через API — то же самое, что и
src/ingestion/daily_report_loader.py, но по HTTP: инженер загружает
файл прямо из дашборда, а не гоняет скрипт руками."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.ingestion import DailyReportUploadResult, FieldDaySummaryOut, WellDayResultOut
from src.domain.master_data import Well
from src.ingestion.daily_report_loader import load
from src.ingestion.daily_report_source import DailyReportSource

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"], dependencies=[Depends(get_current_user)])

MAPPINGS_DIR = Path(__file__).resolve().parents[2] / "ingestion" / "mappings" / "daily_report"


@router.get("/daily-report/mappings", response_model=list[str])
def list_daily_report_mappings() -> list[str]:
    """Доступные форматы (маппинги колонок) — под разные компании."""
    return sorted(p.stem for p in MAPPINGS_DIR.glob("*.yaml"))


@router.post("/daily-report", response_model=DailyReportUploadResult)
def upload_daily_report(
    file: UploadFile = File(...),
    mapping: str = "standard_ru",
    db: Session = Depends(get_db),
) -> DailyReportUploadResult:
    mapping_path = MAPPINGS_DIR / f"{mapping}.yaml"
    if not mapping_path.exists():
        raise HTTPException(status_code=400, detail=f"неизвестный формат маппинга: {mapping!r}")

    suffix = Path(file.filename or "upload.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        source = DailyReportSource(tmp_path, mapping_path)
        result = load(db, source)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"не удалось разобрать файл: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    well_ids = {r.well_id for r in result.attention}
    uwi_by_id = (
        {w.id: w.uwi for w in db.execute(select(Well).where(Well.id.in_(well_ids))).scalars().all()}
        if well_ids
        else {}
    )

    return DailyReportUploadResult(
        run_id=result.run_id,
        status=result.status,
        records_read=result.records_read,
        records_loaded=result.records_loaded,
        records_quarantined=result.records_quarantined,
        error_message=result.error_message,
        field_summaries=[FieldDaySummaryOut(**s.__dict__) for s in result.field_summaries],
        attention=[
            WellDayResultOut(uwi=uwi_by_id.get(r.well_id), **r.__dict__) for r in result.attention
        ],
    )
