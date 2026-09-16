#!/usr/bin/env python3
"""Генератор синтетического промысла для разработки без доступа к реальным данным.

Использование:
    python scripts/generate_synthetic_field.py
    python scripts/generate_synthetic_field.py --config scripts/synthetic_config.yaml
    python scripts/generate_synthetic_field.py --no-db      # только CSV, без записи в БД

Пишет мастер-данные, справочники, таймсерии добычи и телеметрию ЭЦН
одновременно в data/synthetic/*.csv и (если не указано --no-db) в БД —
структура задана src/domain, физика и параметры — scripts/synthetic/ и
scripts/synthetic_config.yaml.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.synthetic import dirty, events, master_data, simulate, writer  # noqa: E402
from scripts.synthetic.config import SyntheticConfig, load_config  # noqa: E402
from src.domain.base import engine  # noqa: E402
from src.domain.catalogs import build_reference_tables  # noqa: E402


def build_tables(cfg: SyntheticConfig, rng: np.random.Generator) -> dict[str, object]:
    """Собирает все таблицы синтетического промысла в памяти (без записи куда-либо).

    Вынесено отдельно от main(), чтобы тесты могли сгенерировать данные и
    проверить их, не проходя через CLI и не трогая диск/БД.
    """
    ref_tables, ref = build_reference_tables()
    master = master_data.build_master_data(cfg, rng)
    ev = events.build_events(cfg, rng, master, ref)

    # переносим замены оборудования и обновлённые pull_date в мастер-таблицу
    master.tables["equipment"].extend(ev.equipment_rows)
    for row in master.tables["equipment"]:
        if row["id"] in ev.equipment_pull_date_updates:
            row["pull_date"] = ev.equipment_pull_date_updates[row["id"]]

    sim = simulate.simulate(cfg, rng, master, ev, ref)

    producer_well_ids = [w["id"] for w in master.producer_wells]
    well_test_df, measurement_df = dirty.apply_dirty_data(
        cfg, rng, sim["well_test"], sim["measurement"], producer_well_ids
    )

    return {
        **ref_tables,
        **master.tables,
        "daily_production": sim["daily_production"],
        "well_test": well_test_df,
        "node_production": sim["node_production"],
        "downtime": ev.downtime_rows,
        "gtm_event": ev.gtm_event_rows,
        "measurement": measurement_df,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default=str(REPO_ROOT / "scripts" / "synthetic_config.yaml"), help="путь к YAML-конфигу"
    )
    parser.add_argument("--no-db", action="store_true", help="не писать в БД, только CSV")
    args = parser.parse_args()

    cfg = load_config(args.config)
    rng = np.random.default_rng(cfg.seed)

    t0 = time.monotonic()
    print(f"Генерирую синтетический промысел: {cfg.field.name}, seed={cfg.seed}")

    print("  мастер-данные, события, добыча, замеры, телеметрия, \"грязь\"...")
    tables = build_tables(cfg, rng)

    print(f"  пишу CSV в {cfg.output.csv_dir}...")
    writer.write_csv(tables, cfg.output.csv_dir)

    if cfg.output.write_to_db and not args.no_db:
        print("  пишу в БД...")
        writer.write_db(tables, engine, truncate=cfg.output.truncate_before_write)

    elapsed = time.monotonic() - t0
    print(f"\nГотово за {elapsed:.1f} с. Строк по таблицам:")
    for name in writer.TABLE_ORDER:
        if name in tables:
            print(f"  {name:<28} {len(tables[name]):>10,}")


if __name__ == "__main__":
    main()
