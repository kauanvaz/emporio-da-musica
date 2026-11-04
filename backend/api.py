from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from backend.agent import build_agent_input, extract_agent_answer
from backend.config import Settings
from backend.logging import ToolCall, ToolResult, TurnRecord, log_turn
from backend.schemas import ChatRequest, ChatResponse

_GENERIC_ERROR_MESSAGE = (
    "Não foi possível processar sua mensagem agora. Tente novamente em instantes."
)


@dataclass
class RuntimeState:
    settings: Settings
    agent: CompiledStateGraph[Any, Any, Any, Any] | None = None
    tools: tuple[BaseTool, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.agent is not None and bool(self.tools)


def create_router(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        agent = state.agent
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_GENERIC_ERROR_MESSAGE,
            )

        try:
            result = await agent.ainvoke(
                build_agent_input(
                    message=payload.message,
                    history=payload.history,
                    max_history_messages=state.settings.max_history_messages,
                )
            )
            answer = extract_agent_answer(result)
            tool_calls, tool_results = _extract_tool_activity(result)
        except Exception as exc:
            log_turn(
                TurnRecord(
                    session_id=payload.session_id,
                    user_message=payload.message,
                    error=exc,
                )
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=_GENERIC_ERROR_MESSAGE,
            ) from exc

        log_turn(
            TurnRecord(
                session_id=payload.session_id,
                user_message=payload.message,
                tool_calls=tool_calls,
                tool_results=tool_results,
                answer=answer,
            )
        )
        return ChatResponse(answer=answer)

    @router.get("/health")
    async def health() -> dict[str, str]:
        if not state.ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service is not ready.",
            )
        return {"status": "ok"}

    return router


def _extract_tool_activity(
    result: Mapping[str, Any],
) -> tuple[list[ToolCall], list[ToolResult]]:
    messages = result.get("messages", [])
    if not isinstance(messages, Sequence):
        return [], []

    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                name = call.get("name")
                arguments = call.get("args")
                if isinstance(name, str):
                    tool_calls.append(
                        ToolCall(
                            name=name,
                            arguments=(
                                arguments if isinstance(arguments, Mapping) else {}
                            ),
                        )
                    )
        elif isinstance(message, ToolMessage):
            tool_results.append(
                ToolResult(
                    name=message.name or "",
                    result=_tool_result_payload(message),
                )
            )
    return tool_calls, tool_results


def _tool_result_payload(message: ToolMessage) -> Any:
    if message.artifact is not None:
        return message.artifact
    return message.content


__all__ = ["RuntimeState", "create_router"]
