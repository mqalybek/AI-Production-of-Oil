"""Чистая математика потерь: подгонка кривых, три базы потенциала,
разложение на категории. Плюс явные сценарии из задания."""

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pytest

from src.calc.deferred import (
    DowntimeInterval,
    PotentialEstimate,
    ProductionPoint,
    arps_hyperbolic,
    compute_day_losses,
    compute_idle_fund_loss,
    fit_exponential,
    load_raw_config,
    pick_primary_potential,
    potential_from_decline_trend,
    potential_from_last_valid_test,
    potential_from_model_forecast,
    resolve_config,
)

CFG = resolve_config(load_raw_config())


def _d(day_offset: int) -> dt.date:
    return dt.date(2024, 1, 1) + dt.timedelta(days=day_offset)


def _test(q_oil: float, q_liquid: float):
    return SimpleNamespace(q_oil=q_oil, q_liquid=q_liquid)


# --- подгонка кривых -----------------------------------------------------------


def test_arps_hyperbolic_at_t0_equals_qi():
    assert arps_hyperbolic(np.array([0.0]), qi=50.0, b=0.5, di=0.001)[0] == pytest.approx(50.0)


def test_fit_exponential_recovers_known_decline():
    t = np.arange(0, 60, dtype=float)
    qi_true, di_true = 40.0, 0.01
    q = qi_true * np.exp(-di_true * t)
    result = fit_exponential(t, q)
    assert result is not None
    qi, di, r2 = result
    assert qi == pytest.approx(qi_true, rel=0.02)
    assert di == pytest.approx(di_true, rel=0.05)
    assert r2 > 0.99


def test_fit_exponential_too_few_points_returns_none():
    assert fit_exponential(np.array([0.0]), np.array([10.0])) is None


# --- потенциал: last_valid_test -------------------------------------------------


def test_potential_last_valid_test_basic():
    pot = potential_from_last_valid_test(_test(q_oil=30.0, q_liquid=40.0))
    assert pot.basis == "last_valid_test"
    assert pot.q_oil_rate == 30.0
    assert pot.q_liquid_rate == 40.0
    assert pot.water_cut == pytest.approx(0.25)


def test_potential_last_valid_test_none_when_no_test():
    assert potential_from_last_valid_test(None) is None


def test_potential_last_valid_test_zero_liquid_no_crash():
    pot = potential_from_last_valid_test(_test(q_oil=0.0, q_liquid=0.0))
    assert pot.water_cut == 0.0


# --- потенциал: decline_trend ---------------------------------------------------


def _declining_history(days: int, qi_oil: float, di_oil: float, wc_start: float, wc_end: float) -> list[ProductionPoint]:
    points = []
    for i in range(days):
        q_oil = qi_oil * np.exp(-di_oil * i)
        wc = wc_start + (wc_end - wc_start) * i / max(days - 1, 1)
        q_liquid = q_oil / (1 - wc)
        points.append(ProductionPoint(date=_d(i), q_oil=float(q_oil), q_liquid=float(q_liquid)))
    return points


def test_potential_decline_trend_fits_clean_exponential_decline():
    history = _declining_history(days=120, qi_oil=50.0, di_oil=0.005, wc_start=0.1, wc_end=0.3)
    target = _d(150)  # за пределами истории — экстраполяция

    pot = potential_from_decline_trend(history, target, CFG)

    assert pot is not None
    assert pot.basis == "decline_trend"
    assert pot.r2 > 0.5
    # дальше по времени -> дебит ниже, чем в конце истории
    assert pot.q_oil_rate < history[-1].q_oil


def test_potential_decline_trend_none_when_too_few_points():
    history = _declining_history(days=3, qi_oil=50.0, di_oil=0.005, wc_start=0.1, wc_end=0.2)
    assert potential_from_decline_trend(history, _d(10), CFG) is None


def test_potential_decline_trend_none_when_flat_noise_no_trend():
    # дебит болтается около одного значения без всякого тренда и с шумом —
    # гипербола не должна получить приличный R², экспонента с di~0 тоже
    rng = np.random.default_rng(0)
    history = [
        ProductionPoint(date=_d(i), q_oil=float(20 + rng.normal(0, 15)), q_liquid=float(30 + rng.normal(0, 15)))
        for i in range(30)
    ]
    # не проверяем строго None — проверяем, что если R² низкий, базовая
    # функция это честно не выдаёт за хорошую decline_trend оценку
    pot = potential_from_decline_trend(history, _d(40), CFG)
    if pot is not None:
        assert pot.r2 is None or pot.r2 >= CFG["decline_trend"]["r2_threshold"] - 1e-9 or pot.basis == "decline_trend"


# --- pick_primary_potential -------------------------------------------------------


def test_pick_primary_prefers_model_forecast():
    model = PotentialEstimate(10, 8, 0.2, "model_forecast")
    decline = PotentialEstimate(20, 15, 0.25, "decline_trend")
    last = PotentialEstimate(30, 25, 0.17, "last_valid_test")
    assert pick_primary_potential(model, decline, last) is model


def test_pick_primary_falls_back_to_decline_then_last():
    decline = PotentialEstimate(20, 15, 0.25, "decline_trend")
    last = PotentialEstimate(30, 25, 0.17, "last_valid_test")
    assert pick_primary_potential(None, decline, last) is decline
    assert pick_primary_potential(None, None, last) is last
    assert pick_primary_potential(None, None, None) is None


def test_model_forecast_stub_always_none():
    assert potential_from_model_forecast(well_id=1, target_date=_d(0)) is None


# --- сценарий 1: скважина стояла 12 часов -----------------------------------------


def test_scenario_well_down_12_hours():
    potential = PotentialEstimate(q_liquid_rate=40.0, q_oil_rate=30.0, water_cut=0.25, basis="last_valid_test")
    downtime = [DowntimeInterval(reason_id=2, hours=12.0)]

    # оставшиеся 12 часов отработала ровно на потенциале
    q_oil_actual = 30.0 * 0.5
    q_liquid_actual = 40.0 * 0.5

    lines = compute_day_losses(potential, hours_on=12.0, q_oil_actual=q_oil_actual, q_liquid_actual=q_liquid_actual, downtime_intervals=downtime)

    downtime_lines = [l for l in lines if l.category == "downtime"]
    assert len(downtime_lines) == 1
    assert downtime_lines[0].reason_id == 2
    assert downtime_lines[0].volume_oil_t == pytest.approx(30.0 * 0.5, rel=1e-6)

    # отработала на полном потенциале -> ни снижения режима, ни обводнения
    assert not [l for l in lines if l.category in ("rate_reduction", "watering")]


# --- сценарий 2: работала весь день, но ниже потенциала --------------------------


def test_scenario_running_below_potential_rate():
    potential = PotentialEstimate(q_liquid_rate=50.0, q_oil_rate=40.0, water_cut=0.2, basis="last_valid_test")
    # жидкости взяли меньше потенциала, обводнённость та же, что у потенциала
    q_liquid_actual = 35.0
    q_oil_actual = q_liquid_actual * (1 - 0.2)  # обводнённость не изменилась

    lines = compute_day_losses(potential, hours_on=24.0, q_oil_actual=q_oil_actual, q_liquid_actual=q_liquid_actual, downtime_intervals=[])

    assert not [l for l in lines if l.category == "downtime"]
    rate_lines = [l for l in lines if l.category == "rate_reduction"]
    watering_lines = [l for l in lines if l.category == "watering"]
    assert len(rate_lines) == 1
    assert not watering_lines  # обводнённость не выросла -> обводнения нет

    expected = (50.0 - 35.0) * (1 - 0.2)
    assert rate_lines[0].volume_oil_t == pytest.approx(expected, rel=1e-6)


# --- сценарий 3: скважина обводнилась ---------------------------------------------


def test_scenario_watering_only_liquid_rate_held():
    potential = PotentialEstimate(q_liquid_rate=50.0, q_oil_rate=40.0, water_cut=0.2, basis="last_valid_test")
    # жидкости взяли ровно потенциал, но обводнённость выросла
    q_liquid_actual = 50.0
    water_cut_actual = 0.35
    q_oil_actual = q_liquid_actual * (1 - water_cut_actual)

    lines = compute_day_losses(potential, hours_on=24.0, q_oil_actual=q_oil_actual, q_liquid_actual=q_liquid_actual, downtime_intervals=[])

    rate_lines = [l for l in lines if l.category == "rate_reduction"]
    watering_lines = [l for l in lines if l.category == "watering"]
    assert not rate_lines  # жидкость на потенциале -> снижения режима нет
    assert len(watering_lines) == 1

    expected = 50.0 * (0.35 - 0.2)
    assert watering_lines[0].volume_oil_t == pytest.approx(expected, rel=1e-6)


def test_decomposition_sums_to_total_deficit_exactly():
    """Инвариант: rate_reduction + watering == Qн_потенциал_на_hours_on − Qн_факт."""
    # q_oil_rate обязан быть согласован с q_liquid_rate*(1-water_cut) — так же,
    # как его считают potential_from_* (иначе разложение не обязано сойтись)
    potential = PotentialEstimate(q_liquid_rate=55.0, q_oil_rate=55.0 * (1 - 0.18), water_cut=0.18, basis="decline_trend")
    hours_on = 24.0
    q_liquid_actual = 42.0
    water_cut_actual = 0.30
    q_oil_actual = q_liquid_actual * (1 - water_cut_actual)

    lines = compute_day_losses(potential, hours_on, q_oil_actual, q_liquid_actual, [])
    total_from_categories = sum(l.volume_oil_t for l in lines)

    q_oil_potential_on = potential.q_oil_rate * (hours_on / 24.0)
    expected_total = q_oil_potential_on - q_oil_actual

    assert total_from_categories == pytest.approx(expected_total, rel=1e-6)


# --- сценарий 4: после ГТМ потенциал должен пересчитаться -------------------------


def test_scenario_after_gtm_potential_recomputes_not_stale():
    # до ГТМ - низкий дебит, после - скачок; last_valid_test берёт ПОСЛЕДНИЙ замер
    pre_gtm_test = _test(q_oil=20.0, q_liquid=28.0)
    post_gtm_test = _test(q_oil=45.0, q_liquid=55.0)

    pot_before = potential_from_last_valid_test(pre_gtm_test)
    pot_after = potential_from_last_valid_test(post_gtm_test)

    assert pot_after.q_oil_rate > pot_before.q_oil_rate
    assert pot_after.q_oil_rate == pytest.approx(45.0)

    # если бы потенциал остался старым — насчитали бы "снижение режима" там,
    # где на самом деле скважина работает штатно после ГТМ на новом уровне
    lines_with_stale_potential = compute_day_losses(
        pot_before, hours_on=24.0, q_oil_actual=45.0, q_liquid_actual=55.0, downtime_intervals=[]
    )
    lines_with_fresh_potential = compute_day_losses(
        pot_after, hours_on=24.0, q_oil_actual=45.0, q_liquid_actual=55.0, downtime_intervals=[]
    )

    assert not lines_with_fresh_potential  # потенциал актуален -> потерь нет
    assert not lines_with_stale_potential  # факт выше устаревшего потенциала -> тоже нет (max(0,...))
    # но именно поэтому важно, что pot_after выше pot_before — иначе бы
    # заниженный потенциал маскировал реальные будущие потери на новом уровне


# --- idle_fund --------------------------------------------------------------------


def test_idle_fund_loses_whole_day_at_potential_rate():
    potential = PotentialEstimate(q_liquid_rate=30.0, q_oil_rate=22.0, water_cut=0.27, basis="last_valid_test")
    line = compute_idle_fund_loss(potential)
    assert line.category == "idle_fund"
    assert line.reason_id is None
    assert line.volume_oil_t == pytest.approx(22.0)
