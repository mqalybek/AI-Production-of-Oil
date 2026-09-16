"""Запись в карантин: то, что не удалось разобрать/сопоставить, не теряется
молча, а сохраняется с причиной для последующего разбора."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.domain.ingestion_log import IngestionQuarantine

REASONS = (
    "unknown_well",
    "parse_error",
    "unit_conversion_error",
    "schema_mismatch",
    "invalid_value",
)


def quarantine(
    session: Session,
    run_id: int,
    source: str,
    raw_data: dict,
    reason: str,
    reason_detail: str | None = None,
) -> None:
    if reason not in REASONS:
        raise ValueError(f"неизвестная причина карантина: {reason!r}")
    session.add(
        IngestionQuarantine(
            run_id=run_id,
            source=source,
            raw_data=raw_data,
            reason=reason,
            reason_detail=reason_detail,
        )
    )
