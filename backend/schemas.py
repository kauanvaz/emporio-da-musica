from typing import Literal

from pydantic import BaseModel, Field


class AgentAnswer(BaseModel):
    status: Literal[
        "answered",
        "partially_answered",
        "not_answerable",
        "out_of_scope",
    ]
    answer: str
    requires_human_support: bool = False
    human_support_reason: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: AgentAnswer


__all__ = [
    "AgentAnswer",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
]
