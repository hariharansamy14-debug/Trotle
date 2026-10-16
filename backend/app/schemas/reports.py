from __future__ import annotations

from pydantic import BaseModel


class ExportRequest(BaseModel):
    format: str = "json"
