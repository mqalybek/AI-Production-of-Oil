"""Хеширование паролей и выпуск/проверка JWT для локальных пользователей
api_user. LDAP/SSO — на будущее, сейчас нужен только рабочий логин."""

from __future__ import annotations

import datetime as dt

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(username: str, role: str) -> str:
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.jwt_expires_minutes)
    payload = {"sub": username, "role": role, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class TokenPayload:
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role


def decode_access_token(token: str) -> TokenPayload | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    username = payload.get("sub")
    role = payload.get("role")
    if username is None or role is None:
        return None
    return TokenPayload(username=username, role=role)
