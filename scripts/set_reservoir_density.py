"""Задать/поменять плотность нефти и воды для объекта/горизонта, подтвердить
её по ФХИ.

Плотность — справочное свойство пласта (одно значение на горизонт, не на
скважину и не на сутки), используется загрузчиками источников, которые
дают объёмный дебит без своей плотности, чтобы перевести м3 в тонны.
density_confirmed=False по умолчанию (в т.ч. если стоит дефолт 0.86/1.0,
не введённый вручную) — загрузчик суточных данных обязан предупреждать,
пока не подтверждено явно (--confirm).

Примеры:
    python scripts/set_reservoir_density.py --field "Синтетическое" --reservoir "I" --oil-density 0.86 --water-density 1.0 --confirm
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
    parser.add_argument("--oil-density", type=float, help="плотность нефти, т/м3")
    parser.add_argument("--water-density", type=float, help="плотность воды, т/м3")
    parser.add_argument("--confirm", action="store_true", help="пометить плотность как подтверждённую по ФХИ")
    parser.add_argument("--list", action="store_true", help="показать текущие значения и выйти")
    args = parser.parse_args()

    with SessionLocal() as session:
        field = session.execute(select(Field).where(Field.name == args.field)).scalar_one_or_none()
        if field is None:
            raise SystemExit(f"месторождение {args.field!r} не найдено")

        if args.list:
            reservoirs = session.execute(select(Reservoir).where(Reservoir.field_id == field.id)).scalars().all()
            for r in reservoirs:
                confirmed = "подтверждена" if r.density_confirmed else "НЕ подтверждена"
                print(f"{r.name!r} (горизонт {r.horizon_code!r}): нефть={r.oil_density_t_m3}, вода={r.water_density_t_m3} — {confirmed}")
            return

        if not args.reservoir or (args.oil_density is None and args.water_density is None and not args.confirm):
            raise SystemExit(
                "для установки плотности нужны --reservoir и хотя бы одно из "
                "--oil-density/--water-density/--confirm (или используйте --list)"
            )

        reservoir = session.execute(
            select(Reservoir).where(Reservoir.field_id == field.id, Reservoir.name == args.reservoir)
        ).scalar_one_or_none()
        if reservoir is None:
            raise SystemExit(f"объект/горизонт {args.reservoir!r} не найден на месторождении {args.field!r}")

        if args.oil_density is not None:
            reservoir.oil_density_t_m3 = args.oil_density
        if args.water_density is not None:
            reservoir.water_density_t_m3 = args.water_density
        if args.confirm:
            reservoir.density_confirmed = True

        session.commit()
        confirmed = "подтверждена" if reservoir.density_confirmed else "не подтверждена"
        print(
            f"{args.reservoir!r} на {args.field!r}: "
            f"нефть={reservoir.oil_density_t_m3}, вода={reservoir.water_density_t_m3} ({confirmed})"
        )


if __name__ == "__main__":
    main()
