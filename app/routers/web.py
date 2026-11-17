from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

router = APIRouter(include_in_schema=False)


@router.get("/")
def home():
    return RedirectResponse("/app/")
