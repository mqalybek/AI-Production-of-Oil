"""Точка входа FastAPI-приложения. Запуск: uvicorn src.api.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import alerts, auth, data_quality, deferred, fields, monthly_production, production, wells

app = FastAPI(title="Мониторинг добычи — API", version="0.1.0")

# TODO: сузить origin, когда появится адрес дашборда (сейчас открыт для
# локальной разработки — сервис on-premise, наружу не смотрит).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(fields.router)
app.include_router(wells.router)
app.include_router(production.router)
app.include_router(deferred.router)
app.include_router(monthly_production.router)
app.include_router(alerts.router)
app.include_router(data_quality.router)
