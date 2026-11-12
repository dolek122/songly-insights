"""FastAPI application: wires routers and error handlers together."""

from fastapi import FastAPI

from app.errors import register_error_handlers
from app.metrics import API_PREFIX, install_middleware
from app.routers import catalog, events, health, listeners, metrics, stats


def create_app() -> FastAPI:
    app = FastAPI(
        title="Songly Insights",
        description="Music listening analytics API",
        version="0.1.0",
    )
    register_error_handlers(app)
    install_middleware(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    for module in (catalog, listeners, events, stats):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
