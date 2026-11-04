from collections.abc import Sequence
from typing import Literal

import httpx
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


class BackendClientError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def send_message(
        self,
        *,
        session_id: str,
        message: str,
        history: Sequence[ChatMessage],
    ) -> AgentAnswer:
        request = ChatRequest(
            session_id=session_id,
            message=message,
            history=list(history),
        )

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self._base_url}/chat",
                    json=request.model_dump(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendClientError("The backend request failed.") from exc

        try:
            payload = ChatResponse.model_validate(response.json())
        except ValueError as exc:
            raise BackendClientError(
                "The backend returned an invalid response."
            ) from exc

        return payload.answer


__all__ = [
    "AgentAnswer",
    "BackendClient",
    "BackendClientError",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
]
