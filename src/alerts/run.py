"""CLI слоя алертов.

Использование:
    python -m src.alerts.run --period 2024-01-15
    python -m src.alerts.run --period 2024-01-15 --send   # + рассылка в Telegram
                                                            # (нужен TELEGRAM_BOT_TOKEN)
"""

from __future__ import annotations

import argparse

from src.alerts.lifecycle import process_period
from src.alerts.telegram_bot import TelegramSender, send_pending_alerts
from src.domain.base import SessionLocal
from src.ingestion.base import Period


def main() -> None:
    parser = argparse.ArgumentParser(description="Прогон детекторов алертов + рассылка")
    parser.add_argument("--period", required=True, help="YYYY-MM-DD или YYYY-MM")
    parser.add_argument("--send", action="store_true", help="разослать активные алерты в Telegram")
    parser.add_argument("--base-url", default="", help="базовый URL карточки скважины для ссылок в сообщениях")
    args = parser.parse_args()

    period = Period.parse(args.period)
    session = SessionLocal()
    try:
        report = process_period(session, period)
        print(
            f"детекторы: создано={report.created} обновлено={report.updated} "
            f"закрыто={report.resolved} подавлено каскадом={report.suppressed_by_cascade} "
            f"групповых алертов={report.cascades_created}"
        )

        if args.send:
            sender = TelegramSender()
            if not sender.is_configured:
                print("TELEGRAM_BOT_TOKEN не задан — рассылка пропущена (это ожидаемо без бота)")
            sent = send_pending_alerts(session, sender, base_url=args.base_url)
            print(f"отправлено сообщений: {sent}")

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
