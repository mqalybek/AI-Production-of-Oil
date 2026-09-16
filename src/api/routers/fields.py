from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.wells import FieldOut
from src.domain.master_data import Field

router = APIRouter(prefix="/api/fields", tags=["fields"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[FieldOut])
def list_fields(db: Session = Depends(get_db)) -> list[Field]:
    return db.execute(select(Field).order_by(Field.name)).scalars().all()
