"""Симуляция суточной добычи, замеров АГЗУ и телеметрии ЭЦН по скважинам.

Здесь физика (decline.py) и события (events.py) соединяются в конкретные
временные ряды: daily_production, well_test, node_production, measurement.
Заодно дозаполняет deferred_oil_t в downtime и effect_fact_t/effect_plan_t
в gtm_event — их нельзя было посчитать раньше, они зависят от дебита в
момент события.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from scripts.synthetic.catalogs import ReferenceIds
from scripts.synthetic.config import SyntheticConfig
from scripts.synthetic.decline import arps_hyperbolic_rate, logistic_curve, sample_lognormal_range
from scripts.synthetic.events import EventsResult
from scripts.synthetic.master_data import MasterData


def _history_start_dt(cfg: SyntheticConfig) -> dt.datetime:
    return dt.datetime.combine(cfg.history.start_date, dt.time(0, 0), tzinfo=dt.timezone.utc)


def simulate(
    cfg: SyntheticConfig,
    rng: np.random.Generator,
    master: MasterData,
    events: EventsResult,
    ref: ReferenceIds,
) -> dict[str, pd.DataFrame]:
    prod = cfg.production
    n = len(master.producer_wells)
    history_days = cfg.history.days
    history_start_dt = _history_start_dt(cfg)
    days_idx = np.arange(history_days)

    # --- индивидуальные параметры скважин, по одному сэмплу на скважину ---
    qi = sample_lognormal_range(rng, prod.qo_initial_t_d.min, prod.qo_initial_t_d.max, n)
    b_arr = rng.uniform(prod.arps_b.min, prod.arps_b.max, n)
    di_annual = rng.uniform(prod.initial_annual_decline.min, prod.initial_annual_decline.max, n)

    wc_start = rng.uniform(prod.water_cut.start.min, prod.water_cut.start.max, n)
    is_high_wc = rng.random(n) < prod.water_cut.fraction_high_wc_wells
    wc_end = np.where(
        is_high_wc,
        rng.uniform(prod.water_cut.end_high.min, prod.water_cut.end_high.max, n),
        rng.uniform(prod.water_cut.start.max, prod.water_cut.end_high.min, n),
    )
    wc_t_mid = rng.uniform(history_days * 0.2, history_days * 0.8, n)
    wc_k = rng.uniform(3.0, 6.0, n) / (history_days * 0.4)

    gor_base = rng.uniform(prod.gor.base_range_m3_t.min, prod.gor.base_range_m3_t.max, n)
    days_to_bubble = rng.uniform(
        prod.gor.days_to_bubble_point.min, prod.gor.days_to_bubble_point.max, n
    )
    gor_k = 4.0 / 150.0  # ГФ выходит на новое плато примерно за 150 суток после Pb

    interval_min = cfg.esp_telemetry.measurement_interval_minutes
    telemetry_ts = pd.date_range(
        history_start_dt,
        periods=history_days * 24 * 60 // interval_min,
        freq=f"{interval_min}min",
    )
    telemetry_day_idx = np.clip(
        ((telemetry_ts - history_start_dt) / pd.Timedelta(days=1)).values.astype(int),
        0,
        history_days - 1,
    )
    telemetry_hour = (telemetry_ts.hour + telemetry_ts.minute / 60.0).values

    dates = pd.date_range(cfg.history.start_date, periods=history_days, freq="D")

    daily_rows: list[dict] = []
    well_test_rows: list[dict] = []
    measurement_frames: list[pd.DataFrame] = []

    for i, well in enumerate(master.producer_wells):
        well_id = well["id"]

        # --- регимы Арпса: базовый + по одному на каждое ГТМ на этой скважине ---
        regimes = [{"start_day": 0, "qi": qi[i], "b": b_arr[i], "di": di_annual[i]}]
        for gtm in sorted(events.gtm_instructions.get(well_id, []), key=lambda g: g.day):
            active = regimes[-1]
            t_rel = gtm.day - active["start_day"]
            rate_before = float(
                arps_hyperbolic_rate(np.array([t_rel]), active["qi"], active["b"], active["di"])[0]
            )
            new_qi = rate_before * (1 + gtm.uplift_fraction)
            new_di = min(active["di"] * gtm.decline_acceleration, 0.6)
            regimes.append({"start_day": gtm.day, "qi": new_qi, "b": active["b"], "di": new_di})

            effect = gtm.uplift_fraction * rate_before * 30.0  # накопленный эффект за 30 суток
            gtm.row["effect_fact_t"] = round(effect, 1)
            gtm.row["effect_plan_t"] = round(effect * rng.uniform(0.8, 1.2), 1)

        oil_potential = np.zeros(history_days)
        for r_idx, regime in enumerate(regimes):
            end_day = regimes[r_idx + 1]["start_day"] if r_idx + 1 < len(regimes) else history_days
            t_rel = days_idx[regime["start_day"]:end_day] - regime["start_day"]
            oil_potential[regime["start_day"]:end_day] = arps_hyperbolic_rate(
                t_rel, regime["qi"], regime["b"], regime["di"]
            )

        water_cut = np.clip(
            logistic_curve(days_idx, wc_start[i], wc_end[i], wc_t_mid[i], wc_k[i]), 0.0, 0.97
        )
        gor = logistic_curve(
            days_idx, gor_base[i], gor_base[i] * prod.gor.ramp_up_factor, days_to_bubble[i], gor_k
        )

        liquid_potential = oil_potential / np.clip(1 - water_cut, 0.03, 1.0)
        water_potential = liquid_potential - oil_potential
        gas_potential = oil_potential * gor

        # --- простои: часы простоя по суткам, deferred_oil_t на каждое событие ---
        hours_down = np.zeros(history_days)
        for downtime in events.well_downtime_intervals.get(well_id, []):
            day_start = max((downtime["ts_start"] - history_start_dt).total_seconds() / 86400, 0.0)
            day_end = min((downtime["ts_end"] - history_start_dt).total_seconds() / 86400, history_days)
            if day_end <= day_start:
                continue
            first_day, last_day = int(np.floor(day_start)), int(np.ceil(day_end)) - 1
            for d in range(first_day, last_day + 1):
                overlap_hours = (min(day_end, d + 1) - max(day_start, d)) * 24
                if overlap_hours > 0:
                    hours_down[d] += overlap_hours
            ref_day = min(int(day_start), history_days - 1)
            duration_days = (downtime["ts_end"] - downtime["ts_start"]).total_seconds() / 86400
            downtime["deferred_oil_t"] = round(float(oil_potential[ref_day]) * duration_days, 2)
        hours_down = np.clip(hours_down, 0, 24)
        hours_on = 24 - hours_down
        ke = hours_on / 24

        oil_actual = oil_potential * ke
        liquid_actual = liquid_potential * ke
        water_actual = water_potential * ke
        gas_actual = gas_potential * ke

        for d in range(history_days):
            daily_rows.append(
                {
                    "well_id": well_id,
                    "date": dates[d].date(),
                    "q_oil_t": round(float(oil_actual[d]), 3),
                    "q_liquid_t": round(float(liquid_actual[d]), 3),
                    "q_water_m3": round(float(water_actual[d]), 3),
                    "q_gas_m3": round(float(gas_actual[d]), 1),
                    "hours_on": round(float(hours_on[d]), 2),
                    "ke": round(float(ke[d]), 4),
                    "allocation_factor": 1.0,
                    "source": "synthetic",
                }
            )

        # --- давления: базовый уровень на скважину + шум ---
        p_buf_base = rng.uniform(cfg.pressures.p_buf_atm.min, cfg.pressures.p_buf_atm.max)
        p_zatr_base = rng.uniform(cfg.pressures.p_zatr_base_atm.min, cfg.pressures.p_zatr_base_atm.max)
        run_depth = well["run_depth"] or cfg.esp_telemetry.esp_run_depth_m.min

        # --- замеры АГЗУ ---
        test_interval = rng.uniform(
            prod.well_test_interval_days.min, prod.well_test_interval_days.max
        )
        t = rng.uniform(0, test_interval)
        while t < history_days:
            day = int(t)
            if hours_down[day] < 12:  # не тестируем скважину, простоявшую почти весь день
                duration_h = rng.uniform(2, 8)
                ts_start = history_start_dt + dt.timedelta(days=t)
                well_test_rows.append(
                    {
                        "well_id": well_id,
                        "ts_start": ts_start,
                        "ts_end": ts_start + dt.timedelta(hours=duration_h),
                        "duration_h": round(duration_h, 2),
                        "q_liquid": round(float(liquid_actual[day] * rng.normal(1, 0.03)), 2),
                        "q_oil": round(float(oil_actual[day] * rng.normal(1, 0.03)), 2),
                        "q_water": round(float(water_actual[day] * rng.normal(1, 0.03)), 2),
                        "q_gas": round(float(gas_actual[day] * rng.normal(1, 0.05)), 1),
                        "water_cut": round(float(water_cut[day] * 100 * rng.normal(1, 0.02)), 2),
                        "gor": round(float(gor[day] * rng.normal(1, 0.03)), 2),
                        "p_buf": round(
                            float(p_buf_base + rng.normal(0, cfg.pressures.p_buf_noise_std)), 2
                        ),
                        "p_zatr": round(
                            float(
                                p_zatr_base
                                + cfg.pressures.p_zatr_depth_coef * run_depth
                                + rng.normal(0, cfg.pressures.p_zatr_noise_std)
                            ),
                            2,
                        ),
                        "temperature": round(float(rng.uniform(35, 55)), 1),
                        "method": "agzu",
                        "is_valid": True,
                        "validation_flags": None,
                        "operator": "synthetic",
                    }
                )
            t += test_interval

        # --- телеметрия ЭЦН на сетке measurement_interval_minutes ---
        n_pts = len(telemetry_ts)
        up_mask = np.ones(n_pts, dtype=bool)
        for downtime in events.well_downtime_intervals.get(well_id, []):
            mask = (telemetry_ts >= downtime["ts_start"]) & (telemetry_ts < downtime["ts_end"])
            up_mask &= ~mask

        q_liquid_at_t = liquid_actual[telemetry_day_idx]
        liquid_ref = max(float(np.percentile(liquid_potential, 75)), 1.0)
        load_frac = np.clip(q_liquid_at_t / liquid_ref, 0.05, 1.2)
        daily_cycle = 1 + cfg.esp_telemetry.daily_cycle_amplitude_pct / 100.0 * np.sin(
            2 * np.pi * telemetry_hour / 24.0
        )

        def _with_noise(values: np.ndarray) -> np.ndarray:
            return values * daily_cycle * rng.normal(1, cfg.esp_telemetry.noise_std_pct / 100.0, n_pts)

        current_a = np.where(
            up_mask,
            _with_noise(
                np.interp(
                    load_frac, [0, 1], [cfg.esp_telemetry.current_a.min, cfg.esp_telemetry.current_a.max]
                )
            ),
            0.0,
        )
        load_pct = np.where(
            up_mask,
            _with_noise(
                np.interp(
                    load_frac, [0, 1], [cfg.esp_telemetry.load_pct.min, cfg.esp_telemetry.load_pct.max]
                )
            ),
            0.0,
        )
        freq_hz = np.where(
            up_mask,
            rng.uniform(cfg.esp_telemetry.freq_hz.min, cfg.esp_telemetry.freq_hz.max)
            * rng.normal(1, 0.01, n_pts),
            0.0,
        )
        p_buf = p_buf_base + rng.normal(0, cfg.pressures.p_buf_noise_std, n_pts)
        p_zatr = (
            p_zatr_base
            + cfg.pressures.p_zatr_depth_coef * run_depth
            + rng.normal(0, cfg.pressures.p_zatr_noise_std, n_pts)
        )
        drawdown_span = cfg.esp_telemetry.intake_pressure_atm.max - cfg.esp_telemetry.intake_pressure_atm.min
        intake_pressure = np.where(
            up_mask,
            np.clip(p_zatr - drawdown_span * load_frac, cfg.esp_telemetry.intake_pressure_atm.min * 0.5, None),
            p_zatr,
        )

        wide = pd.DataFrame(
            {
                "well_id": well_id,
                "ts": telemetry_ts,
                "p_buf": p_buf,
                "p_zatr": p_zatr,
                "esp_current_a": current_a,
                "esp_load_pct": load_pct,
                "esp_freq_hz": freq_hz,
                "esp_intake_pressure": intake_pressure,
            }
        )
        long = wide.melt(id_vars=["well_id", "ts"], var_name="tag_code", value_name="value")
        long["tag_id"] = long["tag_code"].map(ref.measurement_tag).astype(int)
        long["quality"] = "good"
        long["source"] = "synthetic"
        measurement_frames.append(long.drop(columns="tag_code"))

    daily_production_df = pd.DataFrame(daily_rows)
    well_test_df = pd.DataFrame(well_test_rows)
    measurement_df = pd.concat(measurement_frames, ignore_index=True)

    # --- пьезометрические скважины: периодическое пластовое давление ---
    piezo_frames = []
    piezo_tag_id = ref.measurement_tag["reservoir_pressure"]
    for well in master.piezometric_wells:
        base_p = rng.uniform(150, 250)
        decline_per_year = rng.uniform(5, 15)
        n_readings = history_days // 7
        ts = pd.date_range(history_start_dt, periods=n_readings, freq="7D")
        t_years = (np.arange(n_readings) * 7) / 365.0
        values = base_p - decline_per_year * t_years + rng.normal(0, 2, n_readings)
        piezo_frames.append(
            pd.DataFrame(
                {
                    "well_id": well["id"],
                    "ts": ts,
                    "tag_id": piezo_tag_id,
                    "value": np.round(values, 2),
                    "quality": "good",
                    "source": "synthetic",
                }
            )
        )
    if piezo_frames:
        measurement_df = pd.concat([measurement_df, *piezo_frames], ignore_index=True)

    measurement_df = measurement_df[["well_id", "ts", "tag_id", "value", "quality", "source"]]

    # --- факт по узлу сбора = сумма скважин ± расхождение аллокации ---
    node_map = {w["id"]: w["node_id"] for w in master.producer_wells}
    dp = daily_production_df.copy()
    dp["node_id"] = dp["well_id"].map(node_map)
    node_production_df = dp.groupby(["node_id", "date"], as_index=False)[
        ["q_oil_t", "q_liquid_t", "q_water_m3", "q_gas_m3"]
    ].sum()

    mismatch = cfg.dirty_data.node_vs_wells_mismatch_pct
    n_rows = len(node_production_df)
    signs = rng.choice([-1.0, 1.0], size=n_rows)
    factors = 1 + signs * rng.uniform(mismatch.min, mismatch.max, n_rows) / 100.0
    for col in ["q_oil_t", "q_liquid_t", "q_water_m3", "q_gas_m3"]:
        node_production_df[col] = (node_production_df[col] * factors).round(3)

    return {
        "daily_production": daily_production_df,
        "well_test": well_test_df,
        "node_production": node_production_df,
        "measurement": measurement_df,
    }
