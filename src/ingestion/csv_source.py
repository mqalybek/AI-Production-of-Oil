"""Источник CSV/Excel суточных рапортов. Формат рапорта у каждого промысла
свой — маппинг колонок задаётся YAML-конфигом (см. src/ingestion/mappings/),
а не зашит в код.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd
import yaml
from pydantic import BaseModel

from src.ingestion.base import DataSource, Period, RawRecord, SourceMetadata, SourceValidationError


class ColumnMapping(BaseModel):
    tag: str
    unit: str
    aliases: list[str]


class ReportMapping(BaseModel):
    external_system: str
    well_id_aliases: list[str]
    date_column_aliases: list[str]
    header_rows: int = 1
    columns: list[ColumnMapping]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ReportMapping":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)


@dataclass
class _ResolvedColumns:
    well_id_col: str | None
    date_col: str | None
    tag_cols: list[tuple[ColumnMapping, str]]


def _normalize_header(s: object) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _parse_date(value: object) -> pd.Timestamp | None:
    if _is_empty(value):
        return None
    text = str(value).strip()
    # сначала однозначный ISO (YYYY-MM-DD) — dayfirst иногда путает день/месяц
    # даже на нём, если довериться общей эвристике сразу
    iso = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    if not pd.isna(iso):
        return iso
    # иначе — типичный для рапортов формат ДД.ММ.ГГГГ и подобные
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def _parse_float(value: object) -> float | None:
    if _is_empty(value):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


class CsvSource(DataSource):
    """Суточный рапорт в CSV или Excel. Для Excel понимает многострочную шапку
    (header_rows в конфиге) и объединённые ячейки в ней."""

    def __init__(self, path: str | Path, mapping_path: str | Path):
        self.path = Path(path)
        self.mapping = ReportMapping.from_yaml(mapping_path)
        self._df_cache: pd.DataFrame | None = None

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source="csv",
            external_system=self.mapping.external_system,
            description=f"Суточный рапорт: {self.path.name}",
            path=str(self.path),
        )

    def validate_schema(self) -> None:
        if not self.path.exists():
            raise SourceValidationError(f"файл не найден: {self.path}")
        try:
            df = self._load_dataframe()
        except Exception as exc:
            raise SourceValidationError(f"не удалось прочитать файл: {exc}") from exc

        resolved = self._resolve_columns(list(df.columns))
        if resolved.well_id_col is None:
            raise SourceValidationError(
                "не найдена колонка с идентификатором скважины "
                f"(ожидались заголовки: {self.mapping.well_id_aliases})"
            )
        if resolved.date_col is None:
            raise SourceValidationError(
                f"не найдена колонка с датой (ожидались заголовки: {self.mapping.date_column_aliases})"
            )
        if not resolved.tag_cols:
            raise SourceValidationError(
                "ни одна колонка файла не сопоставлена ни с одним тегом из конфига маппинга"
            )

    def read(self, period: Period) -> Iterator[RawRecord]:
        df = self._load_dataframe()
        resolved = self._resolve_columns(list(df.columns))

        for _, row in df.iterrows():
            raw_row = row.to_dict()

            well_raw = row.get(resolved.well_id_col) if resolved.well_id_col else None
            if _is_empty(well_raw):
                yield RawRecord(raw=raw_row, parse_error="пустой идентификатор скважины")
                continue

            date_raw = row.get(resolved.date_col) if resolved.date_col else None
            ts = _parse_date(date_raw)
            if ts is None:
                yield RawRecord(raw=raw_row, parse_error=f"не удалось разобрать дату: {date_raw!r}")
                continue
            if not period.contains(ts.date()):
                continue

            for col_def, col_name in resolved.tag_cols:
                value_raw = row.get(col_name)
                if _is_empty(value_raw):
                    continue  # колонка пустая для этой строки — это не ошибка, просто нет тега
                value = _parse_float(value_raw)
                if value is None:
                    yield RawRecord(
                        raw=raw_row, parse_error=f"не удалось разобрать значение {col_name}={value_raw!r}"
                    )
                    continue
                yield RawRecord(
                    external_well_id=str(well_raw).strip(),
                    ts=ts.to_pydatetime(),
                    tag=col_def.tag,
                    value=value,
                    unit=col_def.unit,
                    raw=raw_row,
                )

    # --- внутреннее ---

    def _load_dataframe(self) -> pd.DataFrame:
        if self._df_cache is None:
            if self.path.suffix.lower() in (".xlsx", ".xlsm"):
                self._df_cache = self._load_excel()
            else:
                self._df_cache = pd.read_csv(self.path, dtype=str, keep_default_na=False)
        return self._df_cache

    def _load_excel(self) -> pd.DataFrame:
        import openpyxl

        wb = openpyxl.load_workbook(self.path, data_only=True)
        ws = wb.active
        header_rows = self.mapping.header_rows

        # снимок значений листа — на не-якорных ячейках объединения openpyxl
        # отдаёт None, писать в них нельзя (MergedCell), поэтому работаем с копией
        grid = [
            [ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(1, ws.max_row + 1)
        ]

        # разворачиваем объединения внутри шапки: копируем значение якоря
        for rng in ws.merged_cells.ranges:
            if rng.max_row > header_rows:
                continue
            anchor = grid[rng.min_row - 1][rng.min_col - 1]
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    grid[r - 1][c - 1] = anchor

        columns = []
        for c in range(len(grid[0]) if grid else 0):
            parts = [str(grid[r][c]).strip() for r in range(header_rows) if not _is_empty(grid[r][c])]
            columns.append(" ".join(dict.fromkeys(parts)))  # без соседних дублей (общий заголовок сверху)

        data_rows = [row for row in grid[header_rows:] if any(not _is_empty(v) for v in row)]
        return pd.DataFrame(data_rows, columns=columns)

    def _resolve_columns(self, header: list[str]) -> _ResolvedColumns:
        normalized = {_normalize_header(h): h for h in header}

        def _find(aliases: list[str]) -> str | None:
            for alias in aliases:
                match = normalized.get(_normalize_header(alias))
                if match is not None:
                    return match
            return None

        well_id_col = _find(self.mapping.well_id_aliases)
        date_col = _find(self.mapping.date_column_aliases)

        tag_cols = []
        for col_def in self.mapping.columns:
            match = _find(col_def.aliases)
            if match is not None:
                tag_cols.append((col_def, match))

        return _ResolvedColumns(well_id_col, date_col, tag_cols)
