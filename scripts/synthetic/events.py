"""События: отказы ЭЦН, плановые ТРС, отключения электроэнергии (по узлу),
ГТМ. Отдаёт как строки для БД (downtime, gtm_event, доп. equipment), так и
"расписание" простоев/ГТМ по скважинам — для использования в simulate.py при
расчёте суточной добычи (потенциал vs факт).
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass

import numpy as np

from scripts.synthetic.config import SyntheticConfig
from scripts.synthetic.master_data import MasterData
from src.domain.catalogs import GTM_TYPES, ReferenceIds

_GTM_TYPE_NAMES = {code: name for code, name in GTM_TYPES}


@dataclass
class GtmInstruction:
    well_id: int
    day: int  # сутки от начала истории мониторинга
    gtm_type_code: str
    uplift_fraction: float
    decline_acceleration: float
    row: dict  # ссылка на строку gtm_event, чтобы simulate.py дозаполнил effect_fact_t/effect_plan_t


@dataclass
class EventsResult:
    downtime_rows: list[dict]
    well_downtime_intervals: dict[int, list[dict]]
    gtm_instructions: dict[int, list[GtmInstruction]]
    gtm_event_rows: list[dict]
    equipment_rows: list[dict]
    equipment_pull_date_updates: dict[int, dt.date]  # equipment_id -> pull_date


def _day_to_ts(history_start: dt.date, day: float, hour: float = 0.0) -> dt.datetime:
    return dt.datetime.combine(history_start, dt.time(0, 0), tzinfo=dt.timezone.utc) + dt.timedelta(
        days=day, hours=hour
    )


def build_events(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    master: MasterData,
    ref: ReferenceIds,
) -> EventsResult:
    history_start = cfg.history.start_date
    history_days = cfg.history.days

    downtime_id = itertools.count(1)
    gtm_event_id = itertools.count(1)
    equipment_id = itertools.count(
        max((r["id"] for r in master.tables["equipment"]), default=0) + 1
    )

    downtime_rows: list[dict] = []
    well_downtime_intervals: dict[int, list[dict]] = {
        w["id"]: [] for w in master.producer_wells
    }
    equipment_rows: list[dict] = []
    equipment_pull_date_updates: dict[int, dt.date] = {}

    ev = cfg.events

    # --- отказы ЭЦН (по скважине, экспоненциальное распределение наработки) ---
    for well in master.producer_wells:
        mtbf = rng.uniform(ev.esp_mtbf_days.min, ev.esp_mtbf_days.max)
        t = rng.exponential(mtbf)
        current_equipment_id = well["equipment_id"]
        while t < history_days:
            repair_days = rng.uniform(ev.workover_duration_days.min, ev.workover_duration_days.max)
            ts_start = _day_to_ts(history_start, t)
            ts_end = _day_to_ts(history_start, t + repair_days)

            downtime_row = {
                "id": next(downtime_id),
                "well_id": well["id"],
                "ts_start": ts_start,
                "ts_end": ts_end,
                "reason_id": ref.downtime_reason["esp_failure"],
                "comment": "Отказ ЭЦН, замена насоса",
                "deferred_oil_t": None,  # дозаполняется в simulate.py
                "is_planned": False,
            }
            downtime_rows.append(downtime_row)
            well_downtime_intervals[well["id"]].append(downtime_row)

            # после ремонта старое оборудование демонтировано, спущено новое
            equipment_pull_date_updates[current_equipment_id] = ts_start.date()
            new_run_depth = float(
                np.clip(
                    well["run_depth"] + rng.normal(0, 50),
                    cfg.esp_telemetry.esp_run_depth_m.min,
                    cfg.esp_telemetry.esp_run_depth_m.max,
                )
            )
            new_id = next(equipment_id)
            equipment_rows.append(
                {
                    "id": new_id,
                    "well_id": well["id"],
                    "equipment_type": "esp",
                    "type_size": f"ЭЦН5-{int(rng.choice([45, 60, 80, 125]))}",
                    "run_depth": new_run_depth,
                    "install_date": ts_end.date(),
                    "pull_date": None,
                }
            )
            current_equipment_id = new_id
            well["run_depth"] = new_run_depth
            well["equipment_id"] = new_id

            t += repair_days + rng.exponential(mtbf)

    # --- плановые ТРС ---
    for well in master.producer_wells:
        n_events = rng.poisson(ev.workover_events_per_well_per_year * history_days / 365.0)
        for _ in range(n_events):
            day = float(rng.uniform(0, history_days))
            duration = rng.uniform(ev.workover_duration_days.min, ev.workover_duration_days.max)
            ts_start = _day_to_ts(history_start, day)
            ts_end = _day_to_ts(history_start, day + duration)
            downtime_row = {
                "id": next(downtime_id),
                "well_id": well["id"],
                "ts_start": ts_start,
                "ts_end": ts_end,
                "reason_id": ref.downtime_reason["workover_trs"],
                "comment": "Плановый текущий ремонт скважины",
                "deferred_oil_t": None,
                "is_planned": True,
            }
            downtime_rows.append(downtime_row)
            well_downtime_intervals[well["id"]].append(downtime_row)

    # --- отключения электроэнергии, коррелированные по узлу (кусту) ---
    n_outages = rng.poisson(ev.power_outage.events_per_year * history_days / 365.0)
    for _ in range(n_outages):
        day = float(rng.uniform(0, history_days))
        duration_h = rng.uniform(ev.power_outage.duration_hours.min, ev.power_outage.duration_hours.max)
        node = master.agzu_nodes[int(rng.integers(0, len(master.agzu_nodes)))]
        affected_wells = [w for w in master.producer_wells if w["node_id"] == node["id"]]
        ts_start = _day_to_ts(history_start, day)
        ts_end = ts_start + dt.timedelta(hours=duration_h)
        for well in affected_wells:
            downtime_row = {
                "id": next(downtime_id),
                "well_id": well["id"],
                "ts_start": ts_start,
                "ts_end": ts_end,
                "reason_id": ref.downtime_reason["power_outage"],
                "comment": f"Отключение электроэнергии по узлу {node['name']}",
                "deferred_oil_t": None,
                "is_planned": False,
            }
            downtime_rows.append(downtime_row)
            well_downtime_intervals[well["id"]].append(downtime_row)

    # --- ГТМ: 2-5 в год на всё месторождение ---
    gtm_instructions: dict[int, list[GtmInstruction]] = {w["id"]: [] for w in master.producer_wells}
    gtm_event_rows: list[dict] = []
    gtm_type_codes = list(ref.gtm_type.keys())
    n_gtm = int(round(rng.uniform(ev.gtm.events_per_year.min, ev.gtm.events_per_year.max) * history_days / 365.0))
    for _ in range(n_gtm):
        well = master.producer_wells[int(rng.integers(0, len(master.producer_wells)))]
        day = float(rng.uniform(60, history_days - 30))  # не в первый/последний месяц истории
        gtm_type_code = gtm_type_codes[int(rng.integers(0, len(gtm_type_codes)))]
        uplift = float(rng.uniform(ev.gtm.oil_uplift_fraction.min, ev.gtm.oil_uplift_fraction.max))
        accel = float(
            rng.uniform(ev.gtm.decline_acceleration_factor.min, ev.gtm.decline_acceleration_factor.max)
        )
        event_date = history_start + dt.timedelta(days=day)
        row = {
            "id": next(gtm_event_id),
            "well_id": well["id"],
            "event_date": event_date,
            "gtm_type_id": ref.gtm_type[gtm_type_code],
            "description": _GTM_TYPE_NAMES[gtm_type_code],
            "effect_fact_t": None,
            "effect_plan_t": None,
        }
        gtm_event_rows.append(row)
        gtm_instructions[well["id"]].append(
            GtmInstruction(
                well_id=well["id"],
                day=int(day),
                gtm_type_code=gtm_type_code,
                uplift_fraction=uplift,
                decline_acceleration=accel,
                row=row,
            )
        )

    return EventsResult(
        downtime_rows=downtime_rows,
        well_downtime_intervals=well_downtime_intervals,
        gtm_instructions=gtm_instructions,
        gtm_event_rows=gtm_event_rows,
        equipment_rows=equipment_rows,
        equipment_pull_date_updates=equipment_pull_date_updates,
    )
