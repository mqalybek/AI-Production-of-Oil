"""Задать/поменять плотность нефти для объекта/горизонта.

Плотность — справочное свойство пласта (одно значение на горизонт, не на
скважину и не на сутки), используется загрузчиками источников, которые
дают объёмный дебит без своей плотности, чтобы перевести м3 в тонны.

Примеры:
    python scripts/set_reservoir_density.py --field "Синтетическое" --reservoir "I" --density 0.86
    python scripts/set_reservoir_density.py --list --field "Синтетическое"
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from src.domain.master_data import Field, Reservoir
from src.domain.base import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", required=True, help="название месторождения")
    parser.add_argument("--reservoir", help="название объекта/горизонта (reservoir.name)")
    parser.add_argument("--density", type=float, help="плотность нефти, т/м3")
    parser.add_argument("--list", action="store_true", help="показать текущие значения и выйти")
    args = parser.parse_args()

    with SessionLocal() as session:
        field = session.execute(select(Field).where(Field.name == args.field)).scalar_one_or_none()
        if field is None:
            raise SystemExit(f"месторождение {args.field!r} не найдено")

        if args.list:
            reservoirs = session.execute(select(Reservoir).where(Reservoir.field_id == field.id)).scalars().all()
            for r in reservoirs:
                print(f"{r.name!r} (горизонт {r.horizon_code!r}): {r.oil_density_t_m3}")
            return

        if not args.reservoir or args.density is None:
            raise SystemExit("для установки плотности нужны --reservoir и --density (или используйте --list)")

        reservoir = session.execute(
            select(Reservoir).where(Reservoir.field_id == field.id, Reservoir.name == args.reservoir)
        ).scalar_one_or_none()
        if reservoir is None:
            raise SystemExit(f"объект/горизонт {args.reservoir!r} не найден на месторождении {args.field!r}")

        reservoir.oil_density_t_m3 = args.density
        session.commit()
        print(f"плотность {args.reservoir!r} на {args.field!r} установлена: {args.density} т/м3")


if __name__ == "__main__":
    main()
