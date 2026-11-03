from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import Settings
from ..db import utcnow
from ..deps import get_db, get_settings_dep
from ..models import AuditLog, User
from ..schemas import LoginIn, UserOut
from ..security import COOKIE_NAME, client_ip, current_user, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 10
FAILURE_WINDOW = timedelta(minutes=15)


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    ip = client_ip(request)
    since = utcnow() - FAILURE_WINDOW
    failures = db.scalar(
        select(func.count()).where(
            AuditLog.action == "login_failed",
            AuditLog.username == body.username,
            AuditLog.at >= since,
        )
    )
    if failures >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "로그인 실패가 많습니다. 15분 후 다시 시도하세요")

    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        db.add(AuditLog(action="login_failed", username=body.username, ip=ip))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 올바르지 않습니다")

    audit(db, "login", user, ip=ip)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user, settings),
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
