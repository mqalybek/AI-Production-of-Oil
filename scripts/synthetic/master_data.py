"""Генерация мастер-данных: месторождение, объекты, узлы сбора, скважины,
интервалы перфорации, начальное оборудование, алиасы, привязка к узлам сбора.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field as dc_field

import numpy as np

from scripts.synthetic.config import SyntheticConfig


@dataclass
class MasterData:
    tables: dict[str, list[dict]]
    producer_wells: list[dict] = dc_field(default_factory=list)
    injector_wells: list[dict] = dc_field(default_factory=list)
    piezometric_wells: list[dict] = dc_field(default_factory=list)
    agzu_nodes: list[dict] = dc_field(default_factory=list)


def build_master_data(cfg: SyntheticConfig, rng: np.random.Generator) -> MasterData:
    tables: dict[str, list[dict]] = {
        "field": [],
        "reservoir": [],
        "gathering_node": [],
        "well": [],
        "well_alias": [],
        "completion": [],
        "equipment": [],
        "well_gathering_node_history": [],
    }

    field_id = 1
    tables["field"].append({"id": field_id, "name": cfg.field.name, "field_type": "oil"})

    reservoir_ids = []
    for i, name in enumerate(cfg.field.reservoirs, start=1):
        tables["reservoir"].append(
            {"id": i, "field_id": field_id, "name": name, "horizon_code": name.split()[-1]}
        )
        reservoir_ids.append(i)

    node_id = 1
    agzu_nodes = []
    for i in range(1, cfg.gathering.n_agzu + 1):
        row = {"id": node_id, "field_id": field_id, "name": f"АГЗУ-{i}", "node_type": "agzu"}
        tables["gathering_node"].append(row)
        agzu_nodes.append(row)
        node_id += 1
    for i in range(1, cfg.gathering.n_dns + 1):
        tables["gathering_node"].append(
            {"id": node_id, "field_id": field_id, "name": f"ДНС-{i}", "node_type": "dns"}
        )
        node_id += 1

    history_start = cfg.history.start_date
    well_id = 1
    completion_id = 1
    equipment_id = 1
    alias_id = 1
    history_id = 1

    producer_wells: list[dict] = []
    injector_wells: list[dict] = []
    piezometric_wells: list[dict] = []

    well_specs = (
        [("producer", "active")] * cfg.wells.n_producers
        + [("injector", "active")] * cfg.wells.n_injectors
        + [("piezometric", "active")] * cfg.wells.n_piezometric
    )

    for idx, (well_type, status) in enumerate(well_specs, start=1):
        # скважина уже работала до начала истории мониторинга (от 1 до 10 лет)
        spud_date = history_start - dt.timedelta(days=int(rng.integers(365, 3650)))
        well_row = {
            "id": well_id,
            "uwi": f"SYN-{well_id:04d}",
            "gos_number": f"ГН-{1000 + well_id}",
            "name": f"Скв. {well_id}",
            "field_id": field_id,
            "well_type": well_type,
            "status": status,
            "spud_date": spud_date,
            "wellhead_x": float(500_000 + rng.uniform(0, 20_000)),
            "wellhead_y": float(5_000_000 + rng.uniform(0, 20_000)),
            "altitude": float(rng.uniform(100, 250)),
        }
        tables["well"].append(well_row)

        for system, prefix in (("scada", "SC"), ("1c", "1C")):
            tables["well_alias"].append(
                {
                    "id": alias_id,
                    "well_id": well_id,
                    "external_system": system,
                    "external_id": f"{prefix}-{well_id:05d}",
                }
            )
            alias_id += 1

        reservoir_id = int(rng.choice(reservoir_ids))
        top_md = float(rng.uniform(2000, 2800))
        tables["completion"].append(
            {
                "id": completion_id,
                "well_id": well_id,
                "reservoir_id": reservoir_id,
                "top_md": top_md,
                "bottom_md": top_md + float(rng.uniform(10, 30)),
                "perf_date": spud_date,
                "status": "open",
            }
        )
        completion_id += 1

        run_depth = None
        if well_type == "producer":
            run_depth = float(
                rng.uniform(cfg.esp_telemetry.esp_run_depth_m.min, cfg.esp_telemetry.esp_run_depth_m.max)
            )
            tables["equipment"].append(
                {
                    "id": equipment_id,
                    "well_id": well_id,
                    "equipment_type": "esp",
                    "type_size": f"ЭЦН5-{int(rng.choice([45, 60, 80, 125]))}",
                    "run_depth": run_depth,
                    "install_date": spud_date,
                    "pull_date": None,
                }
            )
            equipment_id += 1

        if well_type == "producer":
            node = agzu_nodes[len(producer_wells) % len(agzu_nodes)]
            tables["well_gathering_node_history"].append(
                {
                    "id": history_id,
                    "well_id": well_id,
                    "node_id": node["id"],
                    "valid_from": spud_date,
                    "valid_to": None,
                }
            )
            history_id += 1
            producer_wells.append(
                {
                    **well_row,
                    "reservoir_id": reservoir_id,
                    "node_id": node["id"],
                    "run_depth": run_depth,
                    "equipment_id": equipment_id - 1,
                }
            )
        elif well_type == "injector":
            injector_wells.append({**well_row, "reservoir_id": reservoir_id})
        else:
            piezometric_wells.append({**well_row, "reservoir_id": reservoir_id})

        well_id += 1

    return MasterData(
        tables=tables,
        producer_wells=producer_wells,
        injector_wells=injector_wells,
        piezometric_wells=piezometric_wells,
        agzu_nodes=agzu_nodes,
    )
