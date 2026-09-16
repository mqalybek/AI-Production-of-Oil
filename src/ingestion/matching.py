"""Резолюция внешнего идентификатора скважины в well_id через well_alias."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.master_data import WellAlias


def resolve_well_id(session: Session, external_system: str, external_id: str) -> int | None:
    """None, если алиас не найден — вызывающий код обязан отправить запись в карантин,
    а не молча её пропустить (см. src/ingestion/loader.py)."""
    return session.execute(
        select(WellAlias.well_id).where(
            WellAlias.external_system == external_system,
            WellAlias.external_id == external_id,
        )
    ).scalars().first()
