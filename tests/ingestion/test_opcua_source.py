"""OpcUaSource — только структура, реализация отложена. Тест фиксирует, что
скелет действительно ведёт себя как заглушка, а не притворяется рабочим."""

import pytest

from src.ingestion.base import Period, SourceValidationError
from src.ingestion.opcua_source import OpcUaSource


def test_opcua_source_reports_not_implemented():
    source = OpcUaSource(endpoint="opc.tcp://example:4840", mapping_path="unused.yaml")

    with pytest.raises(SourceValidationError):
        source.validate_schema()

    with pytest.raises(NotImplementedError):
        next(source.read(Period.parse("2024-01")))
