from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from services.operator_workbench import build_operator_workbench
from storage.database import get_session


router = APIRouter(prefix="/operator/api", tags=["operator"])
SessionDep = Annotated[Session, Depends(get_session)]


def _require_operator_token(
    authorization: Annotated[str | None, Header()] = None,
    x_ops_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("OPS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator API is not configured",
        )
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else None
    provided = bearer or x_ops_token or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


OperatorAuth = Annotated[None, Depends(_require_operator_token)]


@router.get("/workbench")
def get_operator_workbench(session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    return build_operator_workbench(session)
