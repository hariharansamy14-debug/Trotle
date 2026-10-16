from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=3)
    conversation_id: int | None = None
    source_ids: list[int] | None = None


class FeedbackRequest(BaseModel):
    rating: str
    comment: str | None = None
