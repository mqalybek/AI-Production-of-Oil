"""8 правиловых детекторов аномалий. Каждый — класс с check(session, period)
-> list[AlertCandidate]. ML сознательно не используется — данных мало (см.
задачу): пороги считаются напрямую из телеметрии/замеров/фактов.

Кандидаты ещё не решение о создании алерта — дедупликацию, каскад и
жизненный цикл делает src/alerts/lifecycle.py.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.alerts.base import AlertCandidate, load_raw_config, resolve_config
from src.calc.deferred import (
    load_raw_config as load_deferred_raw_config,
    pick_primary_potential,
    potential_from_decline_trend,
    potential_from_last_valid_test,
    ProductionPoint,
)
from src.calc.deferred import resolve_config as resolve_deferred_config
from src.domain.master_data import Equipment, Well
from src.domain.reference import MeasurementTag
from src.domain.timeseries import DailyProduction, Measurement, WellTest
from src.ingestion.base import Period


def _active_producer_wells(session: Session) -> list[tuple[int, int]]:
    """(well_id, field_id) для всех скважин status='active', well_type='producer'."""
    return list(
        session.execute(
            select(Well.id, Well.field_id).where(Well.well_type == "producer", Well.status == "active")
        ).all()
    )


def _last_valid_test(session: Session, well_id: int, on_date: dt.date) -> WellTest | None:
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    return session.execute(
        select(WellTest)
        .where(WellTest.well_id == well_id, WellTest.is_valid.is_(True), WellTest.ts_start <= upper)
        .order_by(WellTest.ts_start.desc())
    ).scalars().first()


def _tag_id(session: Session, code: str) -> int | None:
    return session.execute(select(MeasurementTag.id).where(MeasurementTag.code == code)).scalar_one_or_none()


class WellStoppedDetector:
    """Ток ЭЦН ниже порога непрерывно >= min_duration_hours, при status='active'."""

    type = "well_stopped"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        as_of = dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc)
        current_tag_id = _tag_id(session, "esp_current_a")
        if current_tag_id is None:
            return []

        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["well_stopped"]
            # запас x3 на случай редкой телеметрии — важна не точная граница
            # окна, а то, что показания реально покрывают min_duration_hours
            lookback_start = as_of - dt.timedelta(hours=cfg["min_duration_hours"] * 3)
            readings = session.execute(
                select(Measurement.ts, Measurement.value)
                .where(
                    Measurement.well_id == well_id,
                    Measurement.tag_id == current_tag_id,
                    Measurement.ts >= lookback_start,
                    Measurement.ts <= as_of,
                )
                .order_by(Measurement.ts)
            ).all()
            if not readings:
                continue

            covers_window = (as_of - readings[0].ts).total_seconds() / 3600 >= cfg["min_duration_hours"]
            if covers_window and all(v < cfg["current_threshold_a"] for _, v in readings):
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=as_of,
                        well_id=well_id,
                        value=float(readings[-1].value),
                        threshold=cfg["current_threshold_a"],
                        message=(
                            f"Скважина не качает: ток ЭЦН < {cfg['current_threshold_a']} А "
                            f"не менее {cfg['min_duration_hours']} ч"
                        ),
                    )
                )
        return candidates


class WaterCutRiseDetector:
    """Рост обводнённости > max_jump_pp за window_days."""

    type = "water_cut_rise"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["water_cut_rise"]

            latest = _last_valid_test(session, well_id, period.end)
            if latest is None or latest.water_cut is None:
                continue

            baseline_cutoff = latest.ts_start - dt.timedelta(days=cfg["window_days"])
            baseline = session.execute(
                select(WellTest)
                .where(WellTest.well_id == well_id, WellTest.is_valid.is_(True), WellTest.ts_start <= baseline_cutoff)
                .order_by(WellTest.ts_start.desc())
            ).scalars().first()
            if baseline is None or baseline.water_cut is None:
                continue

            jump = latest.water_cut - baseline.water_cut
            if jump > cfg["max_jump_pp"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=latest.ts_start,
                        well_id=well_id,
                        value=round(jump, 1),
                        threshold=cfg["max_jump_pp"],
                        message=(
                            f"Обводнённость выросла на {jump:.1f} п.п. за {cfg['window_days']} сут "
                            f"({baseline.water_cut:.1f}% -> {latest.water_cut:.1f}%)"
                        ),
                    )
                )
        return candidates


class GorRiseDetector:
    """Рост ГФ > max_jump_pct за window_days — признак срыва подачи/конуса газа."""

    type = "gor_rise"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["gor_rise"]

            latest = _last_valid_test(session, well_id, period.end)
            if latest is None or latest.gor is None:
                continue

            baseline_cutoff = latest.ts_start - dt.timedelta(days=cfg["window_days"])
            baseline = session.execute(
                select(WellTest)
                .where(WellTest.well_id == well_id, WellTest.is_valid.is_(True), WellTest.ts_start <= baseline_cutoff)
                .order_by(WellTest.ts_start.desc())
            ).scalars().first()
            if baseline is None or not baseline.gor:
                continue

            jump_pct = (latest.gor - baseline.gor) / baseline.gor * 100
            if jump_pct > cfg["max_jump_pct"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=latest.ts_start,
                        well_id=well_id,
                        value=round(jump_pct, 1),
                        threshold=cfg["max_jump_pct"],
                        message=(
                            f"ГФ вырос на {jump_pct:.0f}% за {cfg['window_days']} сут "
                            f"({baseline.gor:.0f} -> {latest.gor:.0f} м3/т)"
                        ),
                    )
                )
        return candidates


class PressureAnomalyDetector:
    """Рбуф/Рзатр вышли за коридор (скользящее среднее ± Nσ за window_days).

    Если аномальны обе — берём худшую по |z-score|, чтобы не плодить два
    кандидата одного типа на одну скважину за один проход (dedup работает
    по (well_id, type), не по тегу внутри него)."""

    type = "pressure_anomaly"
    TAGS = ("p_buf", "p_zatr")

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        as_of = dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc)
        tag_ids = {
            code: tid
            for code, tid in session.execute(
                select(MeasurementTag.code, MeasurementTag.id).where(MeasurementTag.code.in_(self.TAGS))
            ).all()
        }
        if not tag_ids:
            return []

        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["pressure_anomaly"]
            window_start = as_of - dt.timedelta(days=cfg["window_days"])

            best: tuple[str, float, float, float] | None = None  # tag, latest, mean, z
            for tag_name, tag_id in tag_ids.items():
                values = session.execute(
                    select(Measurement.value)
                    .where(
                        Measurement.well_id == well_id,
                        Measurement.tag_id == tag_id,
                        Measurement.ts.between(window_start, as_of),
                    )
                    .order_by(Measurement.ts)
                ).scalars().all()
                if len(values) < cfg["min_points"]:
                    continue

                arr = np.array(values)
                mean, std = float(arr.mean()), float(arr.std())
                if std == 0:
                    continue
                latest = float(arr[-1])
                z = abs(latest - mean) / std
                if z > cfg["sigma_multiplier"] and (best is None or z > best[3]):
                    best = (tag_name, latest, mean, z)

            if best is not None:
                tag_name, latest, mean, z = best
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=as_of,
                        well_id=well_id,
                        value=round(latest, 2),
                        threshold=round(mean, 2),
                        message=(
                            f"{tag_name}: {latest:.1f} вне коридора {mean:.1f}±"
                            f"{cfg['sigma_multiplier']}σ за {cfg['window_days']} сут"
                        ),
                        details={"tag": tag_name, "z_score": round(z, 2)},
                    )
                )
        return candidates


class StaleTestDetector:
    """Нет валидного замера > max_days_since_last_valid суток."""

    type = "stale_test"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["stale_test"]

            latest = _last_valid_test(session, well_id, period.end)
            if latest is None:
                continue  # валидных замеров не было вообще — не "устарел", другая история

            gap_days = (period.end - latest.ts_end.date()).days
            if gap_days > cfg["max_days_since_last_valid"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc),
                        well_id=well_id,
                        value=gap_days,
                        threshold=cfg["max_days_since_last_valid"],
                        message=f"Нет валидного замера {gap_days} сут (> {cfg['max_days_since_last_valid']})",
                    )
                )
        return candidates


class MtbfApproachDetector:
    """Наработка текущего ЭЦН приближается к ожидаемому МРП (>= warn_fraction)."""

    type = "mtbf_approach"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["mtbf_approach"]

            equip = session.execute(
                select(Equipment)
                .where(Equipment.well_id == well_id, Equipment.equipment_type == "esp", Equipment.pull_date.is_(None))
                .order_by(Equipment.install_date.desc())
            ).scalars().first()
            if equip is None:
                continue

            running_days = (period.end - equip.install_date).days
            fraction = running_days / cfg["expected_mtbf_days"]
            if fraction >= cfg["warn_fraction"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc),
                        well_id=well_id,
                        value=round(fraction * 100, 1),
                        threshold=round(cfg["warn_fraction"] * 100, 1),
                        message=(
                            f"Наработка ЭЦН {running_days} сут = {fraction * 100:.0f}% от ожидаемого МРП "
                            f"({cfg['expected_mtbf_days']} сут)"
                        ),
                    )
                )
        return candidates


class ProductionDropDetector:
    """Суточная добыча нефти ниже потенциала (last_valid_test/decline_trend,
    та же логика, что в src/calc/deferred.py) больше чем на max_deviation_pct."""

    type = "production_drop"

    def __init__(self, raw_config: dict | None = None, deferred_raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()
        self.deferred_raw_config = deferred_raw_config or load_deferred_raw_config()

    def _history(self, session: Session, well_id: int, on_date: dt.date, months: int) -> list[ProductionPoint]:
        lower = on_date - dt.timedelta(days=months * 30)
        rows = session.execute(
            select(DailyProduction.date, DailyProduction.q_oil_t, DailyProduction.q_liquid_t)
            .where(DailyProduction.well_id == well_id, DailyProduction.date >= lower, DailyProduction.date < on_date)
            .order_by(DailyProduction.date)
        ).all()
        return [ProductionPoint(date=r.date, q_oil=r.q_oil_t, q_liquid=r.q_liquid_t) for r in rows]

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["production_drop"]
            deferred_cfg = resolve_deferred_config(self.deferred_raw_config, field_id, well_id)

            last_test = _last_valid_test(session, well_id, period.end)
            pot_last = potential_from_last_valid_test(last_test)
            history = self._history(session, well_id, period.end, deferred_cfg["decline_trend"]["history_months"])
            pot_decline = potential_from_decline_trend(history, period.end, deferred_cfg)
            potential = pick_primary_potential(None, pot_decline, pot_last)
            if potential is None or potential.q_oil_rate <= 0:
                continue

            dp = session.execute(
                select(DailyProduction).where(DailyProduction.well_id == well_id, DailyProduction.date == period.end)
            ).scalar_one_or_none()
            if dp is None:
                continue

            deviation_pct = (potential.q_oil_rate - dp.q_oil_t) / potential.q_oil_rate * 100
            if deviation_pct > cfg["max_deviation_pct"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc),
                        well_id=well_id,
                        value=round(deviation_pct, 1),
                        threshold=cfg["max_deviation_pct"],
                        message=(
                            f"Добыча {dp.q_oil_t:.1f} т/сут ниже потенциала {potential.q_oil_rate:.1f} т/сут "
                            f"на {deviation_pct:.0f}% (база: {potential.basis})"
                        ),
                    )
                )
        return candidates


class DataGapDetector:
    """Обрыв телеметрии тока ЭЦН > max_gap_hours."""

    type = "data_gap"

    def __init__(self, raw_config: dict | None = None):
        self.raw_config = raw_config or load_raw_config()

    def check(self, session: Session, period: Period) -> list[AlertCandidate]:
        as_of = dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc)
        current_tag_id = _tag_id(session, "esp_current_a")
        if current_tag_id is None:
            return []

        candidates: list[AlertCandidate] = []
        for well_id, field_id in _active_producer_wells(session):
            cfg = resolve_config(self.raw_config, field_id, well_id)["data_gap"]

            latest_ts = session.execute(
                select(func.max(Measurement.ts)).where(
                    Measurement.well_id == well_id, Measurement.tag_id == current_tag_id, Measurement.ts <= as_of
                )
            ).scalar_one_or_none()
            if latest_ts is None:
                continue  # телеметрии не было никогда — не "обрыв"

            gap_hours = (as_of - latest_ts).total_seconds() / 3600
            if gap_hours > cfg["max_gap_hours"]:
                candidates.append(
                    AlertCandidate(
                        type=self.type,
                        severity=cfg["severity"],
                        ts_detected=as_of,
                        well_id=well_id,
                        value=round(gap_hours, 1),
                        threshold=cfg["max_gap_hours"],
                        message=f"Обрыв телеметрии: последние данные {gap_hours:.1f} ч назад",
                    )
                )
        return candidates


ALL_DETECTORS = [
    WellStoppedDetector,
    WaterCutRiseDetector,
    GorRiseDetector,
    PressureAnomalyDetector,
    StaleTestDetector,
    MtbfApproachDetector,
    ProductionDropDetector,
    DataGapDetector,
]
