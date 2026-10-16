from __future__ import annotations

from pydantic import BaseModel


class SourceCreateRequest(BaseModel):
    name: str
    source_type: str
    configuration: dict | None = None


class SourceSyncRequest(BaseModel):
    refresh: bool = False
