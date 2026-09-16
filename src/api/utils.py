"""Общие мелкие утилиты API: разбивка по времени и пагинация списков."""

from __future__ import annotations

import datetime as dt


def bucket_date(d: dt.date, granularity: str | None) -> dt.date:
    if granularity is None or granularity == "day":
        return d
    if granularity == "week":
        return d - dt.timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    if granularity == "ytd":
        return dt.date(d.year, 1, 1)
    raise ValueError(f"неизвестная granularity: {granularity!r} (day/week/month/ytd)")


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset : offset + limit]
