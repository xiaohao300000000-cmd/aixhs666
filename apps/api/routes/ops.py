from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["ops"])


@router.get("/ops", response_class=HTMLResponse)
def ops_console() -> HTMLResponse:
    template = Path(__file__).resolve().parents[1] / "templates" / "ops.html"
    return HTMLResponse(template.read_text(encoding="utf-8"))


@router.get("/ops/static/{filename}")
def ops_static(filename: str) -> FileResponse:
    if filename not in {"ops.css", "ops.js"}:
        raise FileNotFoundError(filename)
    return FileResponse(Path(__file__).resolve().parents[1] / "static" / filename)
