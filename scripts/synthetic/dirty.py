"""Внесение "грязи" в уже сгенерированные данные — без этого валидацию
(src/calc) не на чем тестировать.

Работает поверх готовых DataFrame'ов well_test/measurement, мутирует их
на месте (или подменяет ссылку в переданном словаре таблиц).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from scripts.synthetic.config import SyntheticConfig


def apply_dirty_data(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    well_test_df: pd.DataFrame,
    measurement_df: pd.DataFrame,
    producer_well_ids: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dd = cfg.dirty_data
    well_test_df = well_test_df.copy()
    measurement_df = measurement_df.copy()

    n_tests = len(well_test_df)

    # --- 1. замеры с некорректной длительностью (< 2 часов) ---
    short_fraction = rng.uniform(
        dd.well_test_short_duration_fraction.min, dd.well_test_short_duration_fraction.max
    )
    short_idx = rng.choice(well_test_df.index, size=int(n_tests * short_fraction), replace=False)
    new_duration = rng.uniform(0.1, 1.9, size=len(short_idx))
    well_test_df.loc[short_idx, "duration_h"] = new_duration.round(2)
    new_ts_end = well_test_df.loc[short_idx, "ts_start"] + pd.to_timedelta(new_duration, unit="h")
    well_test_df.loc[short_idx, "ts_end"] = new_ts_end.astype(well_test_df["ts_end"].dtype)
    well_test_df.loc[short_idx, "is_valid"] = False
    _add_flag(well_test_df, short_idx, "short_duration")

    # --- 2. выбросы: дебит в 3-5 раз выше/ниже соседних замеров ---
    outlier_fraction = rng.uniform(
        dd.well_test_outlier_fraction.min, dd.well_test_outlier_fraction.max
    )
    remaining = well_test_df.index.difference(short_idx)
    outlier_idx = rng.choice(remaining, size=int(n_tests * outlier_fraction), replace=False)
    factors = rng.choice([1, -1], size=len(outlier_idx))
    magnitude = rng.uniform(3.0, 5.0, size=len(outlier_idx))
    multiplier = np.where(factors > 0, magnitude, 1.0 / magnitude)
    for col in ("q_liquid", "q_oil", "q_water", "q_gas"):
        well_test_df.loc[outlier_idx, col] = (well_test_df.loc[outlier_idx, col] * multiplier).round(2)
    well_test_df.loc[outlier_idx, "is_valid"] = False
    _add_flag(well_test_df, outlier_idx, "rate_outlier")

    # --- 3. единичные физически невозможные значения ---
    remaining = well_test_df.index.difference(short_idx).difference(outlier_idx)
    impossible_idx = rng.choice(
        remaining, size=min(dd.impossible_value_count, len(remaining)), replace=False
    )
    for pos in impossible_idx:
        kind = rng.choice(["water_cut_over_100", "negative_rate"])
        if kind == "water_cut_over_100":
            well_test_df.at[pos, "water_cut"] = round(float(rng.uniform(101, 115)), 1)
        else:
            col = rng.choice(["q_oil", "q_liquid", "q_water"])
            well_test_df.at[pos, col] = -abs(round(float(well_test_df.at[pos, col]), 2)) or -1.0
        well_test_df.at[pos, "is_valid"] = False
        _add_flag(well_test_df, [pos], kind)

    # --- 4. скважины без замеров по 20-40 суток (вырезаем окно тестов) ---
    n_long_gap_wells = min(dd.wells_with_long_gaps_count, len(producer_well_ids))
    gap_well_ids = rng.choice(producer_well_ids, size=n_long_gap_wells, replace=False)
    for well_id in gap_well_ids:
        well_rows = well_test_df.index[well_test_df["well_id"] == well_id]
        if len(well_rows) < 3:
            continue
        gap_days = rng.uniform(dd.long_gap_duration_days.min, dd.long_gap_duration_days.max)
        anchor_ts = well_test_df.loc[well_rows, "ts_start"].sample(1, random_state=int(rng.integers(0, 1_000_000))).iloc[0]
        gap_end = anchor_ts + dt.timedelta(days=gap_days)
        in_gap = well_rows[
            (well_test_df.loc[well_rows, "ts_start"] >= anchor_ts)
            & (well_test_df.loc[well_rows, "ts_start"] < gap_end)
        ]
        well_test_df = well_test_df.drop(index=in_gap)

    well_test_df = well_test_df.reset_index(drop=True)

    # --- 5. пропуски в телеметрии (обрывы связи по несколько часов) ---
    months = max(int(cfg.history.days / 30), 1)
    for well_id in producer_well_ids:
        n_gaps = rng.binomial(months, dd.telemetry_gap_probability_per_well_per_month)
        well_mask = measurement_df["well_id"] == well_id
        well_ts = measurement_df.loc[well_mask, "ts"]
        if well_ts.empty:
            continue
        ts_min, ts_max = well_ts.min(), well_ts.max()
        for _ in range(n_gaps):
            span_days = (ts_max - ts_min).days or 1
            gap_start = ts_min + pd.to_timedelta(rng.uniform(0, span_days), unit="D")
            gap_hours = rng.uniform(
                dd.telemetry_gap_duration_hours.min, dd.telemetry_gap_duration_hours.max
            )
            gap_end = gap_start + pd.to_timedelta(gap_hours, unit="h")
            drop_mask = well_mask & (measurement_df["ts"] >= gap_start) & (measurement_df["ts"] < gap_end)
            measurement_df = measurement_df.loc[~drop_mask]

    measurement_df = measurement_df.reset_index(drop=True)

    return well_test_df, measurement_df


def _add_flag(df: pd.DataFrame, idx, flag: str) -> None:
    if "validation_flags" not in df.columns:
        return
    for pos in idx:
        current = df.at[pos, "validation_flags"]
        flags = dict(current) if isinstance(current, dict) else {"errors": []}
        flags.setdefault("errors", [])
        flags["errors"].append(flag)
        df.at[pos, "validation_flags"] = flags
