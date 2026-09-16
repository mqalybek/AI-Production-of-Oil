"""Фиксированные справочники (downtime_reason, gtm_type, measurement_tag).

Это не случайные данные — реальный промысел заводит такие каталоги один раз
и почти не меняет. Здесь они захардкожены по глоссарию из CLAUDE.md, а не
сгенерированы, чтобы id и code были предсказуемы для остального генератора.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReferenceIds:
    downtime_reason: dict[str, int]   # code -> id
    gtm_type: dict[str, int]          # code -> id
    measurement_tag: dict[str, int]   # code -> id


# (code, name, parent_code | None)
DOWNTIME_REASONS: list[tuple[str, str, str | None]] = [
    ("equipment_failure", "Отказ оборудования", None),
    ("esp_failure", "Отказ ЭЦН", "equipment_failure"),
    ("srp_failure", "Отказ ШГН", "equipment_failure"),
    ("planned_repair", "Плановый ремонт", None),
    ("workover_trs", "ТРС", "planned_repair"),
    ("workover_krs", "КРС", "planned_repair"),
    ("external", "Внешние причины", None),
    ("power_outage", "Отключение электроэнергии", "external"),
    ("weather", "Погодные условия", "external"),
    ("technological", "Технологические причины", None),
    ("high_water_cut", "Высокая обводнённость", "technological"),
    ("no_inflow", "Отсутствие притока", "technological"),
    ("organizational", "Организационные причины", None),
    ("waiting_crew", "Ожидание бригады", "organizational"),
    ("gtm", "ГТМ", None),
    ("mothball", "Консервация", None),
]

# (code, name)
GTM_TYPES: list[tuple[str, str]] = [
    ("frac", "ГРП"),
    ("acid_treatment", "ОПЗ"),
    ("horizon_switch", "Перевод на другой горизонт"),
    ("additional_perforation", "Дострел"),
    ("pump_change", "Смена насоса"),
    ("water_shutoff", "Изоляция водопритока"),
    ("sidetrack", "Зарезка бокового ствола"),
]

# (code, name, unit, min_value, max_value)
MEASUREMENT_TAGS: list[tuple[str, str, str, float, float]] = [
    ("p_buf", "Давление буферное", "атм", 0.0, 40.0),
    ("p_zatr", "Давление затрубное", "атм", 0.0, 40.0),
    ("esp_current_a", "Ток ЭЦН", "А", 0.0, 100.0),
    ("esp_load_pct", "Загрузка ЭЦН", "%", 0.0, 120.0),
    ("esp_freq_hz", "Частота ЭЦН", "Гц", 0.0, 60.0),
    ("esp_intake_pressure", "Давление на приёме ЭЦН", "атм", 0.0, 40.0),
    ("reservoir_pressure", "Пластовое давление (пьезометр)", "атм", 0.0, 300.0),
]


def build_reference_tables() -> tuple[dict[str, list[dict]], ReferenceIds]:
    """Возвращает {table_name: [row, ...]} и словари code -> id для FK."""

    tables: dict[str, list[dict]] = {
        "downtime_reason": [],
        "gtm_type": [],
        "measurement_tag": [],
    }

    reason_ids: dict[str, int] = {}
    next_id = 1
    for code, name, parent_code in DOWNTIME_REASONS:
        reason_ids[code] = next_id
        tables["downtime_reason"].append(
            {
                "id": next_id,
                "parent_id": reason_ids.get(parent_code) if parent_code else None,
                "code": code,
                "name": name,
            }
        )
        next_id += 1

    gtm_ids: dict[str, int] = {}
    for i, (code, name) in enumerate(GTM_TYPES, start=1):
        gtm_ids[code] = i
        tables["gtm_type"].append({"id": i, "code": code, "name": name})

    tag_ids: dict[str, int] = {}
    for i, (code, name, unit, min_v, max_v) in enumerate(MEASUREMENT_TAGS, start=1):
        tag_ids[code] = i
        tables["measurement_tag"].append(
            {
                "id": i,
                "code": code,
                "name": name,
                "unit": unit,
                "min_value": min_v,
                "max_value": max_v,
            }
        )

    return tables, ReferenceIds(
        downtime_reason=reason_ids, gtm_type=gtm_ids, measurement_tag=tag_ids
    )
