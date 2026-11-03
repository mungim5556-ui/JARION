import json

from sqlalchemy.orm import Session

from .models import AuditLog, User


def audit(db: Session, action: str, user: User | None = None, ip: str = "", **detail) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=user.id if user else None,
            username=user.username if user else "",
            ip=ip,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else "",
        )
    )
