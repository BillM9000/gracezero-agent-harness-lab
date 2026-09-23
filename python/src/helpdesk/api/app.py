"""Builds the web app around a database connection it is given, not one it opens."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from helpdesk.api.routes import router
from helpdesk.services.errors import Conflict, Invalid, NotFound, ServiceError

STATUS_FOR = {NotFound: 404, Invalid: 422, Conflict: 409}


def create_app(conn: sqlite3.Connection, on_shutdown: Callable[[], None] | None = None) -> FastAPI:
    """on_shutdown lets whoever opened the connection close it when the app stops."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if on_shutdown is not None:
            on_shutdown()

    app = FastAPI(title="Helpdesk", version="0.1.0", lifespan=lifespan)
    app.state.conn = conn
    app.include_router(router)

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=STATUS_FOR.get(type(exc), 400), content={"error": str(exc)})

    return app
