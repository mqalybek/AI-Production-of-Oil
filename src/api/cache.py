"""Простой TTL-кэш в памяти процесса для тяжёлых агрегатов (deferred/summary).
Без Redis — проект работает on-premise одним процессом uvicorn."""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

from src.config import settings

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: int | None = None):
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, object]] = {}

    def get_or_set(self, key: str, compute_fn: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]  # type: ignore[return-value]
        value = compute_fn()
        with self._lock:
            self._store[key] = (now + self._ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


cache = TTLCache()
