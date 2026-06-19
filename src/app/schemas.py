"""Pydantic models — these ARE your API contract.

Every field here shows up in the auto-generated OpenAPI docs at /docs. FastAPI
uses them to (1) validate & parse incoming JSON, (2) serialize responses, and
(3) generate that interactive documentation. Define the data, get the docs free.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(
        ...,  # `...` (Ellipsis) means REQUIRED with no default.
        min_length=1,
        max_length=2000,
        examples=["What is the refund window for damaged goods?"],
    )
    conversation_id: str | None = Field(
        default=None,
        description="Pass an existing id to continue a conversation; omit to start a new one.",
    )


class Citation(BaseModel):
    source: str = Field(..., description="Where the snippet came from (doc name / section).")
    snippet: str
    score: float = Field(..., ge=0.0, le=1.0, description="Retrieval relevance, 0..1.")


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[Citation]


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
