from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from .config import Settings


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_waker(request: Request):
    return request.app.state.waker
