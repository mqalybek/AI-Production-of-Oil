"""CLI слоя загрузки.

Использование:
    python -m src.ingestion.run --source csv --path report.xlsx --period 2024-01
    python -m src.ingestion.run --source csv --path report.csv --period 2024-01 \\
        --mapping src/ingestion/mappings/example_daily_report.yaml
    python -m src.ingestion.run --source synthetic --path data/synthetic --period 2024-01
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.domain.base import SessionLocal
from src.ingestion.base import DataSource, Period
from src.ingestion.csv_source import CsvSource
from src.ingestion.loader import load
from src.ingestion.synthetic_source import SyntheticSource

_DEFAULT_MAPPING = Path(__file__).parent / "mappings" / "example_daily_report.yaml"


def _build_source(args: argparse.Namespace) -> DataSource:
    if args.source == "csv":
        if not args.path:
            raise SystemExit("--path обязателен для --source csv")
        mapping = args.mapping or str(_DEFAULT_MAPPING)
        return CsvSource(args.path, mapping)

    if args.source == "synthetic":
        return SyntheticSource(args.path or "data/synthetic", external_system=args.external_system)

    if args.source == "opcua":
        from src.ingestion.opcua_source import OpcUaSource

        if not args.path or not args.mapping:
            raise SystemExit("--path (endpoint) и --mapping обязательны для --source opcua")
        return OpcUaSource(args.path, args.mapping)

    raise SystemExit(f"неизвестный источник: {args.source}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка данных в measurement")
    parser.add_argument("--source", required=True, choices=["csv", "synthetic", "opcua"])
    parser.add_argument("--path", help="файл (csv) / директория (synthetic) / endpoint (opcua)")
    parser.add_argument("--mapping", help="путь к YAML-маппингу колонок (csv/opcua)")
    parser.add_argument("--period", required=True, help="YYYY-MM или YYYY-MM-DD")
    parser.add_argument(
        "--external-system",
        default="scada",
        help="для synthetic: какой well_alias.external_system использовать (по умолчанию scada)",
    )
    args = parser.parse_args()

    period = Period.parse(args.period)
    source = _build_source(args)

    session = SessionLocal()
    try:
        result = load(session, source, period)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(
        f"[{result.status}] run_id={result.run_id} период={period} "
        f"прочитано={result.records_read} загружено={result.records_loaded} "
        f"в карантине={result.records_quarantined}"
    )
    if result.error_message:
        print(f"ошибка: {result.error_message}", file=sys.stderr)
    if result.status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
