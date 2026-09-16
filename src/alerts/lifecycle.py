"""Жизненный цикл алертов: дедупликация, подавление каскада, автозакрытие
при возврате в норму, квитирование/отложить. Работает поверх кандидатов от
детекторов (src/alerts/detectors.py) — сама решает, что реально писать в БД.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.alerts.base import AlertCandidate, load_raw_config
from src.alerts.detectors import ALL_DETECTORS
from src.domain.alerts import Alert
from src.domain.master_data import WellGatheringNodeHistory
from src.ingestion.base import Period


@dataclass
class LifecycleReport:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    suppressed_by_cascade: int = 0
    cascades_created: int = 0


def _active_alert(session: Session, well_id: int | None, node_id: int | None, type_: str) -> Alert | None:
    q = select(Alert).where(Alert.type == type_, Alert.ts_resolved.is_(None))
    q = q.where(Alert.well_id == well_id) if well_id is not None else q.where(Alert.well_id.is_(None))
    q = q.where(Alert.node_id == node_id) if node_id is not None else q.where(Alert.node_id.is_(None))
    return session.execute(q).scalars().first()


def _suppress_cascades(
    session: Session, candidates: list[AlertCandidate], cfg: dict, report: LifecycleReport
) -> list[AlertCandidate]:
    """Группирует well_stopped кандидатов по узлу; если на одном узле "встало"
    одновременно (в окне cascade.window_hours) >= cascade.min_wells скважин —
    заменяет их одним групповым алертом (node_id, well_id=None), а не N
    отдельными по каждой скважине."""
    cascade_cfg = cfg["default"]["cascade"]
    stopped = [c for c in candidates if c.type == "well_stopped"]
    if not stopped:
        return candidates
    other = [c for c in candidates if c.type != "well_stopped"]

    well_ids = [c.well_id for c in stopped]
    node_map = {
        row.well_id: row.node_id
        for row in session.execute(
            select(WellGatheringNodeHistory.well_id, WellGatheringNodeHistory.node_id).where(
                WellGatheringNodeHistory.well_id.in_(well_ids), WellGatheringNodeHistory.valid_to.is_(None)
            )
        ).all()
    }

    by_node: dict[int, list[AlertCandidate]] = defaultdict(list)
    unassigned: list[AlertCandidate] = []
    for c in stopped:
        node_id = node_map.get(c.well_id)
        (unassigned if node_id is None else by_node[node_id]).append(c)

    result = other + unassigned
    window = dt.timedelta(hours=cascade_cfg["window_hours"])
    for node_id, group in by_node.items():
        group_sorted = sorted(group, key=lambda c: c.ts_detected)
        spread = group_sorted[-1].ts_detected - group_sorted[0].ts_detected
        if len(group) >= cascade_cfg["min_wells"] and spread <= window:
            report.suppressed_by_cascade += len(group)
            report.cascades_created += 1
            result.append(
                AlertCandidate(
                    type="node_stopped_cascade",
                    severity=cascade_cfg["severity"],
                    ts_detected=group_sorted[-1].ts_detected,
                    node_id=node_id,
                    value=len(group),
                    threshold=cascade_cfg["min_wells"],
                    message=(
                        f"{len(group)} скважин на узле встали одновременно — "
                        "похоже на отключение электроэнергии по кусту"
                    ),
                    details={"well_ids": [c.well_id for c in group]},
                )
            )
        else:
            result.extend(group)
    return result


def process_period(
    session: Session,
    period: Period,
    raw_config: dict | None = None,
    detector_classes: list = ALL_DETECTORS,
) -> LifecycleReport:
    """Прогоняет все детекторы, подавляет каскад, дедуплицирует активные
    алерты и автозакрывает те, что вернулись в норму."""
    raw_config = raw_config or load_raw_config()
    report = LifecycleReport()

    candidates: list[AlertCandidate] = []
    for detector_cls in detector_classes:
        detector = detector_cls(raw_config)
        candidates.extend(detector.check(session, period))

    candidates = _suppress_cascades(session, candidates, raw_config, report)

    seen_keys: set[tuple[int | None, int | None, str]] = set()
    for c in candidates:
        key = (c.well_id, c.node_id, c.type)
        seen_keys.add(key)
        existing = _active_alert(session, c.well_id, c.node_id, c.type)
        if existing is None:
            session.add(
                Alert(
                    well_id=c.well_id,
                    node_id=c.node_id,
                    type=c.type,
                    severity=c.severity,
                    ts_detected=c.ts_detected,
                    value=c.value,
                    threshold=c.threshold,
                    message=c.message,
                    is_acknowledged=False,
                )
            )
            report.created += 1
        else:
            # алерт уже активен — не плодим дубль, просто обновляем актуальные цифры
            existing.value = c.value
            existing.message = c.message
            report.updated += 1

    # автозакрытие: активный алерт типа, который этот прогон проверял, но
    # кандидат для него больше не пришёл — значит вернулись в норму
    checked_types = {d.type for d in detector_classes} | {"node_stopped_cascade"}
    active_alerts = session.execute(
        select(Alert).where(Alert.type.in_(checked_types), Alert.ts_resolved.is_(None))
    ).scalars().all()
    now = dt.datetime.now(dt.timezone.utc)
    for alert in active_alerts:
        if (alert.well_id, alert.node_id, alert.type) not in seen_keys:
            alert.ts_resolved = now
            report.resolved += 1

    session.flush()
    return report


def acknowledge(session: Session, alert_id: int, acknowledged_by: str, comment: str | None = None) -> Alert:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError(f"алерт {alert_id} не найден")
    alert.is_acknowledged = True
    alert.acknowledged_by = acknowledged_by
    alert.acknowledged_at = dt.datetime.now(dt.timezone.utc)
    if comment:
        alert.comment = comment
    session.flush()
    return alert


def snooze(session: Session, alert_id: int, hours: int | None = None, raw_config: dict | None = None) -> Alert:
    raw_config = raw_config or load_raw_config()
    hours = hours if hours is not None else raw_config["default"]["lifecycle"]["snooze_hours"]
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ValueError(f"алерт {alert_id} не найден")
    alert.snoozed_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    session.flush()
    return alert
