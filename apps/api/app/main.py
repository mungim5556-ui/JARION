import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .allocator import tick
from .config import Settings, get_settings
from .db import Database, utcnow
from .power import Prober, RelayWaker, TcpProber, Waker
from .routers import admin, agent, auth, student

log = logging.getLogger("jarion")


def run_tick(app: FastAPI) -> None:
    st = app.state
    db = st.db.SessionLocal()
    try:
        tick(db, st.settings, st.prober, st.waker, utcnow())
    finally:
        db.close()


async def scheduler_loop(app: FastAPI) -> None:
    interval = app.state.settings.probe_interval_seconds
    while True:
        try:
            await asyncio.to_thread(run_tick, app)
        except Exception:  # 한 번 실패해도 루프는 계속
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)


def create_app(
    settings: Settings | None = None,
    waker: Waker | None = None,
    prober: Prober | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db.create_all()
        task = asyncio.create_task(scheduler_loop(app)) if settings.scheduler_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()

    app = FastAPI(title="JARION API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.waker = waker or RelayWaker(settings.relay_token)
    app.state.prober = prober or TcpProber(settings.probe_timeout_seconds, settings.probe_workers)

    app.include_router(auth.router)
    app.include_router(student.router)
    app.include_router(admin.router)
    app.include_router(agent.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    return create_app()
