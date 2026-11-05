import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from langchain_core.embeddings import Embeddings
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.config import Settings
from mcp_server.database.engine import create_runtime_engine
from mcp_server.domain.errors import VALIDATION_ERROR, DomainError
from mcp_server.domain.models import (
    OrderDetails,
    OrderQuery,
    PolicyChunk,
    PolicyQueryResult,
    ProductSearchInput,
    ProductSearchResult,
    PromotionSearchInput,
    PromotionSearchResult,
)
from mcp_server.logging import configure_logging, log_tool_call
from mcp_server.rag.index import PolicyIndexError, ensure_policy_index
from mcp_server.rag.retriever import PolicyRetrievalError, PolicyRetrieverProtocol
from mcp_server.repositories.orders import (
    OrderRepository,
    SQLiteOrderRepository,
)
from mcp_server.repositories.products import (
    ProductRepository,
    SQLiteProductRepository,
)
from mcp_server.repositories.promotions import (
    PromotionRepository,
    SQLitePromotionRepository,
)
from mcp_server.services.orders import OrderService
from mcp_server.services.policies import PolicyService
from mcp_server.services.products import ProductService
from mcp_server.services.promotions import PromotionService

logger = logging.getLogger(__name__)

_SERVER_NAME = "emporio-store"
_MCP_PATH = "/mcp"
_HEALTH_PATH = "/health"


class McpServerStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerDependencies:
    settings: Settings
    product_repository: ProductRepository
    promotion_repository: PromotionRepository
    order_repository: OrderRepository
    retriever: PolicyRetrieverProtocol | None = None
    embeddings: Embeddings | None = None


@dataclass
class _ServerState:
    retriever: PolicyRetrieverProtocol | None
    ready: bool = False


class _RetrieverProxy:
    def __init__(self, state: _ServerState) -> None:
        self._state = state

    def retrieve(self, query: str) -> list[PolicyChunk]:
        retriever = self._state.retriever
        if retriever is None:
            raise PolicyRetrievalError("Policy index is not ready.")
        return retriever.retrieve(query)


def build_dependencies(
    settings: Settings,
    *,
    retriever: PolicyRetrieverProtocol | None = None,
    embeddings: Embeddings | None = None,
) -> ServerDependencies:
    engine = create_runtime_engine(settings.database_path)
    return ServerDependencies(
        settings=settings,
        product_repository=SQLiteProductRepository(engine),
        promotion_repository=SQLitePromotionRepository(engine),
        order_repository=SQLiteOrderRepository(engine),
        retriever=retriever,
        embeddings=embeddings,
    )


def build_server(deps: ServerDependencies) -> FastMCP:
    configure_logging(deps.settings.log_level)

    state = _ServerState(retriever=deps.retriever)
    retriever = _RetrieverProxy(state)
    product_service = ProductService(deps.product_repository)
    promotion_service = PromotionService(deps.promotion_repository)
    order_service = OrderService(deps.order_repository)
    policy_service = PolicyService(retriever)

    server: FastMCP = FastMCP(
        name=_SERVER_NAME,
        instructions=(
            "Read-only tools for the Empório da Música store: product search, "
            "active promotions, order status and store policy retrieval."
        ),
        lifespan=_make_lifespan(deps, state),
    )

    @server.tool(
        name="search_products",
        description=(
            "Search the product catalog by name or description, category, price "
            "range and stock availability. Returns paginated products with prices "
            "in BRL."
        ),
        annotations={"readOnlyHint": True},
    )
    def search_products(
        query: str | None = None,
        category: str | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        only_in_stock: bool = True,
        sort_by: Literal["relevance", "price_asc", "price_desc"] = "relevance",
        limit: int = 10,
        offset: int = 0,
    ) -> ProductSearchResult:
        arguments = {
            "query": query,
            "category": category,
            "min_price": min_price,
            "max_price": max_price,
            "only_in_stock": only_in_stock,
            "sort_by": sort_by,
            "limit": limit,
            "offset": offset,
        }

        def action() -> ProductSearchResult:
            filters = ProductSearchInput(
                query=query,
                category=category,
                min_price=min_price,
                max_price=max_price,
                only_in_stock=only_in_stock,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
            )
            return product_service.search_products(filters)

        return _execute_tool("search_products", arguments, action)

    @server.tool(
        name="list_active_promotions",
        description=(
            "List active promotions with product, category, stock availability and "
            "the calculated promotional price in BRL. Inactive promotions are never "
            "returned."
        ),
        annotations={"readOnlyHint": True},
    )
    def list_active_promotions(
        query: str | None = None,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> PromotionSearchResult:
        arguments = {
            "query": query,
            "category": category,
            "limit": limit,
            "offset": offset,
        }

        def action() -> PromotionSearchResult:
            filters = PromotionSearchInput(
                query=query,
                category=category,
                limit=limit,
                offset=offset,
            )
            return promotion_service.list_active_promotions(filters)

        return _execute_tool("list_active_promotions", arguments, action)

    @server.tool(
        name="get_order_status",
        description=(
            "Return the status, payment method, tracking code, delivery estimate "
            "and items of a store order by its numeric order_id."
        ),
        annotations={"readOnlyHint": True},
    )
    def get_order_status(order_id: int) -> OrderDetails:
        arguments = {"order_id": order_id}

        def action() -> OrderDetails:
            return order_service.get_order_status(OrderQuery(order_id=order_id))

        return _execute_tool("get_order_status", arguments, action)

    @server.tool(
        name="query_policy",
        description=(
            "Retrieve the most relevant excerpts of the store policy manual for a "
            "subject or question. Use only for store rules and policies, not for "
            "order status, items, payment, totals, tracking or delivery estimates "
            "of a specific order. Returns only the top-k chunks, without "
            "summarizing or rewriting them."
        ),
        annotations={"readOnlyHint": True},
    )
    def query_policy(query: str) -> PolicyQueryResult:
        arguments = {"query": query}

        def action() -> PolicyQueryResult:
            return policy_service.query_policy(query)

        return _execute_tool("query_policy", arguments, action)

    @server.custom_route(_HEALTH_PATH, methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        if not state.ready:
            return JSONResponse({"status": "starting"}, status_code=503)
        return JSONResponse({"status": "ok"})

    return server


def _make_lifespan(
    deps: ServerDependencies,
    state: _ServerState,
) -> Callable[[FastMCP], AbstractAsyncContextManager[dict[str, Any]]]:
    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
        await _startup(deps, state)
        try:
            yield {"state": state}
        finally:
            state.ready = False

    return lifespan


async def _startup(deps: ServerDependencies, state: _ServerState) -> None:
    _ensure_database_exists(deps.settings.database_path)
    retriever = await asyncio.to_thread(
        ensure_policy_index,
        deps.settings,
        deps.embeddings,
    )
    if state.retriever is None:
        state.retriever = retriever
    state.ready = True
    logger.info(
        "MCP server startup complete: database=%s collection=%s",
        deps.settings.database_path,
        deps.settings.chroma_collection_name,
    )


def _ensure_database_exists(database_path: str) -> None:
    path = Path(database_path)
    if not path.is_file():
        raise McpServerStartupError(
            f"Database not found at {path}. Run "
            "`uv run python scripts/seed_database.py` before starting the MCP "
            "server."
        )


def _execute_tool[T](
    tool_name: str,
    arguments: dict[str, Any],
    action: Callable[[], T],
) -> T:
    try:
        with log_tool_call(tool_name, arguments):
            return action()
    except DomainError as exc:
        raise ToolError(f"{exc.code.value}: {exc.message}") from exc
    except PydanticValidationError as exc:
        raise ToolError(f"{VALIDATION_ERROR.value}: Invalid tool arguments.") from exc


def main() -> None:
    settings = Settings.model_validate({})
    configure_logging(settings.log_level)
    deps = build_dependencies(settings)
    server = build_server(deps)

    try:
        server.run(
            transport="streamable-http",
            host=settings.mcp_server_host,
            port=settings.mcp_server_port,
            path=_MCP_PATH,
            log_level=settings.log_level.lower(),
            show_banner=False,
        )
    except (McpServerStartupError, PolicyIndexError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


__all__ = [
    "McpServerStartupError",
    "ServerDependencies",
    "build_dependencies",
    "build_server",
    "main",
]


if __name__ == "__main__":
    main()
