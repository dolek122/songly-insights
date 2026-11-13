"""FastAPI application: wires routers and error handlers together."""

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.logging_config import configure_logging
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


settings = get_settings()
if settings.log_format == "json":
    configure_logging(settings.log_level)

app = create_app()
