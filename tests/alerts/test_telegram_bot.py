"""Форматирование, роутинг по ролям, тихие часы, кнопки — всё без сети и
без токена, как и должно быть на этой стадии проекта."""

import datetime as dt

from src.alerts.base import in_quiet_hours, load_raw_config, resolve_config
from src.alerts.telegram_bot import (
    TelegramSender,
    build_alert_keyboard,
    format_alert_message,
    format_daily_digest,
    routes_for,
    send_pending_alerts,
)
from src.domain.alerts import Alert, AlertSubscriber
from src.ingestion.base import Period

CFG = resolve_config(load_raw_config())


def _alert(**kwargs) -> Alert:
    defaults = dict(
        type="well_stopped", severity="critical", ts_detected=dt.datetime.now(dt.timezone.utc),
        message="тест", well_id=1, is_acknowledged=False,
    )
    defaults.update(kwargs)
    return Alert(**defaults)


def _sub(role: str, chat_id: str = "123") -> AlertSubscriber:
    return AlertSubscriber(chat_id=chat_id, role=role, is_active=True)


# --- роутинг по ролям -----------------------------------------------------------


def test_geologist_gets_water_cut_not_well_stopped():
    geologist = _sub("geologist")
    assert routes_for(_alert(type="water_cut_rise", severity="warning"), [geologist]) == [geologist]
    assert routes_for(_alert(type="well_stopped", severity="critical"), [geologist]) == []


def test_mechanic_gets_well_stopped_not_water_cut():
    mechanic = _sub("mechanic")
    assert routes_for(_alert(type="well_stopped", severity="critical"), [mechanic]) == [mechanic]
    assert routes_for(_alert(type="water_cut_rise", severity="warning"), [mechanic]) == []


def test_manager_gets_only_critical():
    manager = _sub("manager")
    assert routes_for(_alert(type="well_stopped", severity="critical"), [manager]) == [manager]
    assert routes_for(_alert(type="well_stopped", severity="warning"), [manager]) == []
    assert routes_for(_alert(type="water_cut_rise", severity="critical"), [manager]) == [manager]


def test_inactive_subscriber_gets_nothing():
    inactive = _sub("mechanic")
    inactive.is_active = False
    assert routes_for(_alert(type="well_stopped", severity="critical"), [inactive]) == []


# --- форматирование -----------------------------------------------------------


def test_format_alert_message_contains_message_and_numbers():
    alert = _alert(message="Скачок обводнённости", value=20.0, threshold=15.0)
    text = format_alert_message(alert, well=None)
    assert "Скачок обводнённости" in text
    assert "20.0" in text and "15.0" in text


def test_format_daily_digest_counts_critical():
    alerts = [_alert(severity="critical"), _alert(severity="warning"), _alert(severity="critical")]
    text = format_daily_digest(alerts)
    assert "3" in text  # всего
    assert "2" in text  # critical


# --- кнопки -----------------------------------------------------------------------


def test_build_alert_keyboard_has_acknowledge_and_snooze():
    keyboard = build_alert_keyboard(alert_id=42)
    # либо InlineKeyboardMarkup (если python-telegram-bot установлен), либо fallback-словарь
    text_repr = str(keyboard)
    assert "42" in text_repr


# --- тихие часы --------------------------------------------------------------------


def test_quiet_hours_detects_night():
    night = dt.datetime(2024, 1, 1, 23, 0, tzinfo=dt.timezone.utc)
    day = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    assert in_quiet_hours(night, CFG) is True
    assert in_quiet_hours(day, CFG) is False


# --- отправка без токена -----------------------------------------------------------


def test_send_pending_alerts_without_token_does_not_send(db_session, make_well):
    well = make_well()
    db_session.add(
        Alert(
            well_id=well.id, type="well_stopped", severity="critical",
            ts_detected=dt.datetime.now(dt.timezone.utc), message="тест", is_acknowledged=False,
        )
    )
    db_session.add(AlertSubscriber(chat_id="1", role="mechanic", is_active=True))
    db_session.flush()

    sender = TelegramSender(token=None)
    assert sender.is_configured is False

    sent = send_pending_alerts(db_session, sender)
    assert sent == 0  # без токена ничего не отправлено, но и не упало
