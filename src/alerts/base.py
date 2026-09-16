"""Общие типы и конфиг для детекторов алертов (src/alerts/detectors.py)."""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "alerts_rules.yaml"


def load_raw_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config(raw_config: dict, field_id: int | None = None, well_id: int | None = None) -> dict:
    cfg = deepcopy(raw_config["default"])
    overrides = raw_config.get("overrides", {})

    field_override = overrides.get("field", {}).get(str(field_id)) if field_id is not None else None
    if field_override:
        cfg = _deep_merge(cfg, field_override)

    well_override = overrides.get("well", {}).get(str(well_id)) if well_id is not None else None
    if well_override:
        cfg = _deep_merge(cfg, well_override)

    return cfg


def in_quiet_hours(now: dt.datetime, cfg: dict) -> bool:
    """cfg — резолвленный конфиг (с ключом 'lifecycle'). Тихие часы могут
    переходить через полночь (например, 22:00-07:00)."""
    lc = cfg["lifecycle"]
    start = dt.datetime.strptime(lc["quiet_hours_start"], "%H:%M").time()
    end = dt.datetime.strptime(lc["quiet_hours_end"], "%H:%M").time()
    t = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


@dataclass
class AlertCandidate:
    """То, что отдаёт детектор — ещё не запись в БД. lifecycle.py решает,
    создавать ли новый Alert, обновлять существующий активный или подавить
    (дедупликация/каскад)."""

    type: str
    severity: str
    ts_detected: dt.datetime
    message: str
    well_id: int | None = None
    node_id: int | None = None
    value: float | None = None
    threshold: float | None = None
    details: dict = field(default_factory=dict)  # для каскада: список well_id, вошедших в группу
