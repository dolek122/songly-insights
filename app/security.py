import secrets

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings
from app.errors import UnauthorizedError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.api_key.get_secret_value() if settings.api_key else ""
    if not expected:
        raise UnauthorizedError("Write endpoints are disabled: API_KEY is not set on the server")
    if key is None or not secrets.compare_digest(key.encode(), expected.encode()):
        raise UnauthorizedError("Missing or invalid X-API-Key header")


WRITE_ACCESS = [Depends(require_api_key)]
