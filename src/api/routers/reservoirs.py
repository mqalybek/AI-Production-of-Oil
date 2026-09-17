"""Объекты/горизонты и их плотность нефти — справочное значение, которое
инженер задаёт вручную и может поменять (см. scripts/set_reservoir_density.py
для того же самого из консоли)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.reservoirs import ReservoirDensityUpdate, ReservoirOut
from src.domain.master_data import Reservoir

router = APIRouter(prefix="/api/reservoirs", tags=["reservoirs"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ReservoirOut])
def list_reservoirs(
    field_id: int | None = Query(None, alias="field"),
    db: Session = Depends(get_db),
) -> list[Reservoir]:
    q = select(Reservoir)
    if field_id is not None:
        q = q.where(Reservoir.field_id == field_id)
    q = q.order_by(Reservoir.field_id, Reservoir.name)
    return db.execute(q).scalars().all()


@router.patch("/{reservoir_id}", response_model=ReservoirOut)
def update_reservoir_density(
    reservoir_id: int,
    body: ReservoirDensityUpdate,
    db: Session = Depends(get_db),
) -> Reservoir:
    reservoir = db.get(Reservoir, reservoir_id)
    if reservoir is None:
        raise HTTPException(status_code=404, detail=f"объект/горизонт {reservoir_id} не найден")
    reservoir.oil_density_t_m3 = body.oil_density_t_m3
    db.flush()
    return reservoir
