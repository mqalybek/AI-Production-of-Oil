"""Скелет источника OPC UA — только структура и интерфейс, реализация отложена.

TODO при реальной интеграции:
  - зависимость: `asyncua` (или `opcua` для sync-клиента) — намеренно НЕ добавлена
    в pyproject.toml, пока нет реального сервера для проверки.
  - конфиг подключения: адрес endpoint, сертификаты/логин для защищённого
    соединения (промысловый OPC UA почти всегда за периметром с авторизацией).
  - маппинг node-id -> (well_id через well_alias, tag code) — по аналогии с
    ColumnMapping в csv_source.py, но ключ не имя колонки, а NodeId.
  - read(period) для OPC UA обычно не "период из файла", а диапазон дат для
    HistoryRead (если сервер держит историю) — либо, для реал-тайма, отдельный
    режим подписки (subscribe), который в этот интерфейс не укладывается
    один в один — решить при реализации, возможно отдельный метод/источник
    для стриминга, а DataSource.read() оставить для батч-догрузки истории.
  - система категорически ТОЛЬКО ЧИТАЕТ — никаких Write-запросов к OPC UA
    серверу, это счётчик для мониторинга, не средство управления.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from src.ingestion.base import DataSource, Period, RawRecord, SourceMetadata, SourceValidationError


class OpcUaSource(DataSource):
    """Заглушка. Подключать реальный OPC UA клиент — отдельная задача."""

    def __init__(self, endpoint: str, mapping_path: str | Path):
        self.endpoint = endpoint
        self.mapping_path = Path(mapping_path)

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source="opcua",
            external_system="scada",  # TODO: брать из конфига маппинга, когда он появится
            description=f"OPC UA: {self.endpoint} (не реализовано)",
            path=self.endpoint,
        )

    def validate_schema(self) -> None:
        raise SourceValidationError(
            "OpcUaSource — заглушка, реализация отложена (см. TODO в src/ingestion/opcua_source.py)"
        )

    def read(self, period: Period) -> Iterator[RawRecord]:
        raise NotImplementedError("OpcUaSource.read — TODO, см. docstring модуля")
        yield  # pragma: no cover — делает функцию генератором, тело недостижимо
