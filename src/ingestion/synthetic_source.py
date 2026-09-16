"""Источник, читающий CSV, сгенерированные scripts/generate_synthetic_field.py,
как будто это внешний фид — подставная замена реальному источнику на время,
пока нет доступа к промысловым данным.

Специально "разрешает" уже нормализованный measurement.csv обратно во внешний
вид (well_id -> внешний код через well_alias, tag_id -> код тега) — так через
loader проходит тот же путь резолюции/карантина, что и для настоящего источника.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

from src.ingestion.base import DataSource, Period, RawRecord, SourceMetadata, SourceValidationError

_REQUIRED_FILES = ("measurement.csv", "well_alias.csv", "measurement_tag.csv")


class SyntheticSource(DataSource):
    def __init__(self, data_dir: str | Path, external_system: str = "scada"):
        self.data_dir = Path(data_dir)
        self.external_system = external_system

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source="synthetic",
            external_system=self.external_system,
            description="Синтетические данные (для разработки без доступа к реальным)",
            path=str(self.data_dir),
        )

    def validate_schema(self) -> None:
        missing = [f for f in _REQUIRED_FILES if not (self.data_dir / f).exists()]
        if missing:
            raise SourceValidationError(
                f"в {self.data_dir} не найдены файлы {missing} — сначала запусти "
                "scripts/generate_synthetic_field.py"
            )

    def read(self, period: Period) -> Iterator[RawRecord]:
        alias_df = pd.read_csv(self.data_dir / "well_alias.csv")
        alias_df = alias_df[alias_df["external_system"] == self.external_system]
        well_to_external = dict(zip(alias_df["well_id"], alias_df["external_id"]))

        tag_df = pd.read_csv(self.data_dir / "measurement_tag.csv")
        tag_id_to_code = dict(zip(tag_df["id"], tag_df["code"]))
        tag_code_to_unit = dict(zip(tag_df["code"], tag_df["unit"]))

        meas_df = pd.read_csv(self.data_dir / "measurement.csv", parse_dates=["ts"])

        for _, row in meas_df.iterrows():
            ts = row["ts"]
            if not period.contains(ts.date()):
                continue

            raw_row = row.to_dict()
            external_id = well_to_external.get(row["well_id"])
            tag_code = tag_id_to_code.get(row["tag_id"])
            if external_id is None or tag_code is None:
                yield RawRecord(
                    raw=raw_row,
                    parse_error=f"скважина well_id={row['well_id']} или тег tag_id={row['tag_id']} "
                    "не найдены в синтетических справочниках",
                )
                continue

            yield RawRecord(
                external_well_id=str(external_id),
                ts=ts.to_pydatetime(),
                tag=tag_code,
                value=float(row["value"]),
                unit=tag_code_to_unit.get(tag_code, ""),
                raw=raw_row,
            )
