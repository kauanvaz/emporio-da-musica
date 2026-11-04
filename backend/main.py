import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langchain.mcp import MCPAdapter
from langchain.mcp.adapter import MCPAdapterTarget
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from backend.agent import create_store_agent
from backend.api import RuntimeState, create_router
from backend.config import Settings
from backend.logging import configure_logging

logger = logging.getLogger(__name__)

_EXPECTED_TOOL_NAMES = frozenset(
    {
        "search_products",
        "list_active_promotions",
        "get_order_status",
        "query_policy",
    }
)


class BackendStartupError(RuntimeError):
    pass


def create_app(
    settings: Settings | None = None,
    *,
    model: BaseChatModel | None = None,
    mcp_target: MCPAdapterTarget | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.model_validate({})
    configure_logging(resolved_settings.log_level)

    state = RuntimeState(settings=resolved_settings)
    app = FastAPI(
        title="Empório da Música API",
        lifespan=_make_lifespan(state, model=model, mcp_target=mcp_target),
    )
    app.include_router(create_router(state))
    return app


def _make_lifespan(
    state: RuntimeState,
    *,
    model: BaseChatModel | None,
    mcp_target: MCPAdapterTarget | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        target = mcp_target if mcp_target is not None else state.settings.mcp_server_url
        tools = await _load_mcp_tools(target, state.settings.mcp_server_url)
        state.tools = tuple(tools)

        try:
            state.agent = create_store_agent(
                settings=state.settings,
                tools=tools,
                model=model,
            )
        except Exception as exc:
            raise BackendStartupError(
                f"Could not create the store agent: {exc}"
            ) from exc

        logger.info(
            "Backend startup complete with MCP tools: %s",
            sorted(tool.name for tool in tools),
        )
        try:
            yield
        finally:
            state.agent = None
            state.tools = ()

    return lifespan


async def _load_mcp_tools(
    target: MCPAdapterTarget,
    mcp_server_url: str,
) -> list[BaseTool]:
    try:
        tools = await MCPAdapter(target).list_tools()
    except Exception as exc:
        raise BackendStartupError(
            "Could not load tools from the MCP server at "
            f"{mcp_server_url}. Check that the MCP server is running and "
            "reachable."
        ) from exc

    available = {tool.name for tool in tools}
    missing = _EXPECTED_TOOL_NAMES - available
    if missing:
        raise BackendStartupError(
            "The MCP server did not expose the expected tools. Missing: "
            f"{', '.join(sorted(missing))}. Expected: "
            f"{', '.join(sorted(_EXPECTED_TOOL_NAMES))}."
        )
    return tools


def main() -> None:
    settings = Settings.model_validate({})
    configure_logging(settings.log_level)
    uvicorn.run(
        "backend.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.backend_port,
        log_level=settings.log_level.lower(),
    )


__all__ = ["BackendStartupError", "create_app", "main"]


if __name__ == "__main__":
    main()
