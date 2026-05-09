import uuid

from fastapi import FastAPI, Request

from src.db import init_db
from src.logging import correlation_id_var, setup_logging
from src.routes import router


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(title="Document Processing Agent", version="0.1.0")

    # Accept caller-provided correlation ID or generate one — enables end-to-end tracing
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        correlation_id_var.set(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response

    app.include_router(router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    return app


app = create_app()
