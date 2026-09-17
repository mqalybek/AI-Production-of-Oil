from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReservoirOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_id: int
    name: str
    horizon_code: str | None
    oil_density_t_m3: float | None
    water_density_t_m3: float | None
    density_confirmed: bool


class ReservoirDensityUpdate(BaseModel):
    oil_density_t_m3: float | None = None
    water_density_t_m3: float | None = None
    density_confirmed: bool | None = None
