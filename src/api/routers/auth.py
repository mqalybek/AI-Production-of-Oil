"""Логин по паре username/password из локальной таблицы api_user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas.auth import LoginRequest, TokenResponse
from src.api.security import create_access_token, verify_password
from src.domain.api_access import ApiUser

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.execute(select(ApiUser).where(ApiUser.username == body.username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    token = create_access_token(username=user.username, role=user.role)
    return TokenResponse(access_token=token)
