from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.alerts.lifecycle import acknowledge
from src.api.deps import get_current_user, get_db
from src.api.schemas.alerts import AcknowledgeRequest, AlertOut
from src.api.schemas.common import Page
from src.api.security import TokenPayload
from src.api.utils import paginate
from src.domain.alerts import Alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=Page[AlertOut])
def list_alerts(
    status: str | None = Query(None, description="active|resolved"),
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[AlertOut]:
    q = select(Alert)
    if status == "active":
        q = q.where(Alert.ts_resolved.is_(None))
    elif status == "resolved":
        q = q.where(Alert.ts_resolved.is_not(None))
    if severity is not None:
        q = q.where(Alert.severity == severity)
    q = q.order_by(Alert.ts_detected.desc())

    rows = db.execute(q).scalars().all()
    return Page(items=paginate(rows, limit, offset), total=len(rows), limit=limit, offset=offset)


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    body: AcknowledgeRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
) -> Alert:
    try:
        return acknowledge(db, alert_id, acknowledged_by=user.username, comment=body.comment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
