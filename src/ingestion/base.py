"""Базовый интерфейс источника данных и общие типы слоя загрузки.

Все источники (CsvSource, SyntheticSource, OpcUaSource, ...) реализуют
DataSource и отдают одинаковый RawRecord — дальше по пайплайну (matching,
units, upsert) источник уже не важен.
"""

from __future__ import annotations

import datetime as dt
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field


class SourceValidationError(Exception):
    """Источник в принципе не готов к чтению (файла нет, конфиг маппинга битый,
    обязательные колонки не найдены и т.п.) — обнаруживается ДО попытки читать
    записи, приводит к ingestion_run.status = 'failed'.
    """


@dataclass(frozen=True)
class Period:
    """Период загрузки. 'YYYY-MM' -> весь месяц, 'YYYY-MM-DD' -> один день."""

    start: dt.date
    end: dt.date  # включительно

    @classmethod
    def parse(cls, text: str) -> "Period":
        text = text.strip()
        if re.fullmatch(r"\d{4}-\d{2}", text):
            year, month = int(text[:4]), int(text[5:7])
            start = dt.date(year, month, 1)
            end_month = start.replace(day=28) + dt.timedelta(days=4)
            end = end_month - dt.timedelta(days=end_month.day)
            return cls(start, end)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            d = dt.date.fromisoformat(text)
            return cls(d, d)
        raise ValueError(f"не понимаю период: {text!r} (ожидался формат YYYY-MM или YYYY-MM-DD)")

    def contains(self, d: dt.date) -> bool:
        return self.start <= d <= self.end

    def __str__(self) -> str:
        if self.start == self.end:
            return self.start.isoformat()
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


@dataclass
class SourceMetadata:
    source: str                 # 'csv' | 'synthetic' | 'opcua' — совпадает с ingestion_run.source
    external_system: str        # ключ в well_alias.external_system для резолюции скважин
    description: str
    path: str | None = None


class RawRecord(BaseModel):
    """Запись, как её отдал источник — ДО резолюции скважины и приведения единиц.

    Если источник не смог разобрать строку (нечитаемое значение, нет
    обязательной колонки и т.п.), он всё равно должен вернуть RawRecord с
    заполненным parse_error и максимумом того, что удалось прочитать в raw —
    иначе запись просто исчезнет вместо того, чтобы попасть в карантин.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    external_well_id: str | None = None
    ts: dt.datetime | None = None
    tag: str | None = None
    value: float | None = None
    unit: str | None = None
    raw: dict = Field(default_factory=dict)
    parse_error: str | None = None


class NormalizedRecord(BaseModel):
    """Запись после резолюции скважины и приведения единиц — готова к upsert в measurement."""

    well_id: int
    ts: dt.datetime
    tag: str
    value: float
    quality: str = "good"
    source: str


class DataSource(ABC):
    """Общий интерфейс источника данных для слоя загрузки."""

    @abstractmethod
    def read(self, period: Period) -> Iterator[RawRecord]:
        """Отдаёт записи за период. Не должен молча пропускать нечитаемые строки —
        для них возвращается RawRecord с parse_error вместо исключения."""

    @abstractmethod
    def validate_schema(self) -> None:
        """Проверяет, что источник в принципе готов к чтению. Бросает
        SourceValidationError с понятной причиной, если нет."""

    @abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """Имя источника, период не при чём — просто откуда и что это за источник."""
