"""Доставка алертов в Telegram.

Подписки по ролям (AlertSubscriber): геолог видит обводнённость/ГФ/замеры/
потери, механик — телеметрию ЭЦН/МРП/остановки, руководитель — только
critical (плюс суточная сводка, см. format_daily_digest).

Реальная отправка — через python-telegram-bot (опциональная зависимость,
`pip install -e ".[telegram]"`), включается только когда задан
TELEGRAM_BOT_TOKEN (.env / переменная окружения). Без токена
send_pending_alerts() ничего не отправляет и не падает — форматирование
сообщений, роутинг по ролям и кнопки работают и тестируются уже сейчас,
без сети. Когда появится свой бот — просто добавь токен и запусти.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.alerts.base import in_quiet_hours, load_raw_config
from src.domain.alerts import Alert, AlertSubscriber
from src.domain.master_data import Well

# какие типы алертов видит каждая роль (кроме руководителя — у него отдельное правило)
ROLE_ALERT_TYPES: dict[str, set[str]] = {
    "geologist": {"water_cut_rise", "gor_rise", "stale_test", "production_drop"},
    "mechanic": {"well_stopped", "mtbf_approach", "data_gap", "pressure_anomaly", "node_stopped_cascade"},
}

ACK_CALLBACK_PREFIX = "ack:"
SNOOZE_CALLBACK_PREFIX = "snooze:"

_SEVERITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}


def routes_for(alert: Alert, subscribers: list[AlertSubscriber]) -> list[AlertSubscriber]:
    """Кому из подписчиков должен уйти этот алерт."""
    result = []
    for sub in subscribers:
        if not sub.is_active:
            continue
        if sub.role == "manager":
            if alert.severity == "critical":
                result.append(sub)
            continue
        if alert.type in ROLE_ALERT_TYPES.get(sub.role, set()):
            result.append(sub)
    return result


def format_alert_message(alert: Alert, well: Well | None, base_url: str = "") -> str:
    """Скважина, суть, цифры, ссылка на карточку скважины."""
    label = f"Скважина {well.name or well.uwi}" if well is not None else "Узел сбора"
    lines = [f"{_SEVERITY_EMOJI.get(alert.severity, '')} {label}", alert.message]
    if alert.value is not None and alert.threshold is not None:
        lines.append(f"Значение: {alert.value} (порог: {alert.threshold})")
    if base_url and well is not None:
        lines.append(f"{base_url}/wells/{well.id}")
    return "\n".join(lines)


def format_daily_digest(alerts: list[Alert]) -> str:
    """Для руководителя: суточная сводка утром — не каждый алерт отдельно."""
    critical = [a for a in alerts if a.severity == "critical"]
    lines = [f"Суточная сводка: {len(alerts)} активных алертов, из них critical: {len(critical)}"]
    for a in critical[:10]:
        lines.append(f"- {a.message}")
    return "\n".join(lines)


def build_alert_keyboard(alert_id: int):
    """Кнопки "Квитировать"/"Отложить на 24ч". Формат python-telegram-bot,
    если библиотека установлена — иначе простой словарь того же смысла
    (для форматирования/тестов без опциональной зависимости)."""
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        return {
            "buttons": [
                {"text": "Квитировать", "callback_data": f"{ACK_CALLBACK_PREFIX}{alert_id}"},
                {"text": "Отложить на 24ч", "callback_data": f"{SNOOZE_CALLBACK_PREFIX}{alert_id}"},
            ]
        }
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Квитировать", callback_data=f"{ACK_CALLBACK_PREFIX}{alert_id}"),
                InlineKeyboardButton("Отложить на 24ч", callback_data=f"{SNOOZE_CALLBACK_PREFIX}{alert_id}"),
            ]
        ]
    )


class TelegramSender:
    """Тонкая обёртка над python-telegram-bot. is_configured=False (нет
    TELEGRAM_BOT_TOKEN) — send() ничего не делает и возвращает False,
    безопасно вызывать в любой среде."""

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    async def send(self, chat_id: str, text: str, reply_markup=None) -> bool:
        if not self.is_configured:
            return False
        from telegram import Bot  # опциональная зависимость, см. docstring модуля

        bot = Bot(token=self.token)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return True


def send_pending_alerts(
    session: Session, sender: TelegramSender, raw_config: dict | None = None, base_url: str = ""
) -> int:
    """Рассылает активные алерты, которые ещё не отправлялись
    (notified_at IS NULL) и не отложены (snoozed_until). Несрочные — не в
    тихие часы, попробуем на следующем прогоне. Возвращает число реально
    отправленных сообщений (0 без токена — это ожидаемо, не ошибка)."""
    raw_config = raw_config or load_raw_config()
    cfg = raw_config["default"]
    now = dt.datetime.now(dt.timezone.utc)

    pending = session.execute(
        select(Alert).where(
            Alert.ts_resolved.is_(None),
            Alert.notified_at.is_(None),
            (Alert.snoozed_until.is_(None)) | (Alert.snoozed_until <= now),
        )
    ).scalars().all()
    if not pending:
        return 0

    subscribers = session.execute(
        select(AlertSubscriber).where(AlertSubscriber.is_active.is_(True))
    ).scalars().all()

    sent = 0
    for alert in pending:
        if alert.severity != "critical" and in_quiet_hours(now, cfg):
            continue

        recipients = routes_for(alert, subscribers)
        if not recipients:
            alert.notified_at = now  # некому слать — считаем обработанным, не зависаем на нём
            continue

        if not sender.is_configured:
            continue  # нечем слать — оставляем notified_at=None, отправим когда появится токен

        well = session.get(Well, alert.well_id) if alert.well_id else None
        text = format_alert_message(alert, well, base_url)
        keyboard = build_alert_keyboard(alert.id)

        delivered = any(asyncio.run(sender.send(sub.chat_id, text, keyboard)) for sub in recipients)
        if delivered:
            alert.notified_at = now
            sent += 1

    session.flush()
    return sent
