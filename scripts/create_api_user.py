"""Создать (или обновить пароль/роль) локального пользователя API.

Пример:
    python scripts/create_api_user.py --username ivanov --password secret --role manager
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from src.api.security import hash_password
from src.domain.api_access import API_USER_ROLES, ApiUser
from src.domain.base import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", required=True, choices=API_USER_ROLES)
    args = parser.parse_args()

    with SessionLocal() as session:
        user = session.execute(select(ApiUser).where(ApiUser.username == args.username)).scalar_one_or_none()
        if user is None:
            user = ApiUser(username=args.username, role=args.role, password_hash=hash_password(args.password))
            session.add(user)
            print(f"создан пользователь {args.username!r} с ролью {args.role!r}")
        else:
            user.password_hash = hash_password(args.password)
            user.role = args.role
            user.is_active = True
            print(f"обновлён пользователь {args.username!r} (роль {args.role!r})")
        session.commit()


if __name__ == "__main__":
    main()
