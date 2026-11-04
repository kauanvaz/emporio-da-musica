from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import FastMCP
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

from backend.config import Settings
from backend.main import create_app

_FAKE_ANSWER = {
    "status": "answered",
    "answer": "Temos violões a partir de R$ 899,10.",
    "requires_human_support": False,
    "human_support_reason": None,
}


def build_fake_mcp_server() -> FastMCP:
    server: FastMCP = FastMCP(name="fake-emporio-store")

    @server.tool
    def search_products(
        query: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        only_in_stock: bool = True,
        sort_by: str = "relevance",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        return {
            "items": [
                {
                    "product_id": 1,
                    "name": "Violão Folk",
                    "category": "Violões",
                    "price_brl": "899.10",
                    "stock_quantity": 4,
                    "status": "active",
                    "is_available": True,
                }
            ],
            "total": 1,
            "has_more": False,
            "applied_filters": {
                "query": query,
                "category": category,
                "min_price": min_price,
                "max_price": max_price,
                "only_in_stock": only_in_stock,
                "sort_by": sort_by,
                "limit": limit,
                "offset": offset,
            },
        }

    @server.tool
    def list_active_promotions(
        query: str | None = None,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        return {
            "items": [
                {
                    "promotion_id": 1,
                    "description": "Semana do violão",
                    "product_id": 1,
                    "product_name": "Violão Folk",
                    "category": "Violões",
                    "product_status": "active",
                    "stock_quantity": 4,
                    "is_available": True,
                    "original_price_brl": "999.00",
                    "discount_percent": "10.00",
                    "promotional_price_brl": "899.10",
                }
            ],
            "total": 1,
            "has_more": False,
            "applied_filters": {
                "query": query,
                "category": category,
                "limit": limit,
                "offset": offset,
            },
        }

    @server.tool
    def get_order_status(order_id: int) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "customer_id": 1,
            "order_date": "2025-01-10",
            "status": "confirmed",
            "total_brl": "999.00",
            "payment_method": "pix",
            "tracking_code": None,
            "estimated_delivery": None,
            "notes": None,
            "items": [
                {
                    "product_id": 1,
                    "product_name": "Violão Folk",
                    "quantity": 1,
                }
            ],
        }

    @server.tool
    def query_policy(query: str) -> dict[str, Any]:
        return {
            "query": query,
            "chunks": [
                {
                    "chunk_id": "policy-1",
                    "section": "5. Política de Frete e Entregas",
                    "text": "O prazo de entrega varia conforme a região.",
                }
            ],
        }

    return server


class FakeChatModel(BaseChatModel):
    responses: list[AIMessage]
    received_messages: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[str] = Field(default_factory=list)
    _response_index: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling-chat-model"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        self.bound_tool_names = [
            tool.name if isinstance(tool, BaseTool) else str(tool) for tool in tools
        ]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received_messages.append(list(messages))
        if self._response_index >= len(self.responses):
            raise AssertionError(
                "The fake chat model received more calls than configured responses."
            )
        response = self.responses[self._response_index]
        self._response_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


@dataclass(frozen=True)
class FakeApi:
    client: TestClient
    model: FakeChatModel


def build_answer_message(**overrides: Any) -> AIMessage:
    arguments = {**_FAKE_ANSWER, **overrides}
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "AgentAnswer",
                "args": arguments,
                "id": "call-agent-answer",
                "type": "tool_call",
            }
        ],
    )


@contextmanager
def _open_fake_api(responses: list[AIMessage]) -> Iterator[FakeApi]:
    model = FakeChatModel(responses=responses)
    settings = Settings(
        openai_chat_model="fake-chat-model",
        openai_api_key=None,
        log_level="CRITICAL",
    )
    app = create_app(
        settings,
        model=model,
        mcp_target=build_fake_mcp_server(),
    )
    with TestClient(app) as client:
        yield FakeApi(client=client, model=model)


type FakeApiFactory = Callable[
    [list[AIMessage]],
    AbstractContextManager[FakeApi],
]


@pytest.fixture
def fake_api() -> FakeApiFactory:
    return _open_fake_api


@pytest.fixture
def answer_message() -> Callable[..., AIMessage]:
    return build_answer_message


__all__ = [
    "FakeApi",
    "FakeApiFactory",
    "FakeChatModel",
    "build_answer_message",
    "build_fake_mcp_server",
]
