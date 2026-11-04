from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from fastmcp import Client, FastMCP
from langchain_core.embeddings import Embeddings

from mcp_server.config import Settings
from mcp_server.database.seed import seed_database
from mcp_server.server import build_dependencies, build_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
POLICY_PDF_PATH = DATA_DIR / "políticas_da_loja.pdf"


class FakeEmbeddings(Embeddings):
    dimensions = 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        checksum = sum(
            (position + 1) * ord(character) for position, character in enumerate(text)
        )
        return [
            float((checksum + position) % 17 + 1) for position in range(self.dimensions)
        ]


@dataclass(frozen=True)
class McpTestContext:
    server: FastMCP
    settings: Settings
    data_dir: Path


@pytest.fixture(scope="session")
def mcp_context(tmp_path_factory: pytest.TempPathFactory) -> McpTestContext:
    temp_dir = tmp_path_factory.mktemp("mcp_tools")
    database_path = temp_dir / "emporio.db"
    seed_database(database_path=database_path, data_dir=DATA_DIR)

    settings = Settings(
        openai_api_key=None,
        openai_embedding_model="fake-embeddings",
        database_path=str(database_path),
        chroma_persist_dir=str(temp_dir / "chroma"),
        data_dir=str(DATA_DIR),
        policy_pdf_path=str(POLICY_PDF_PATH),
        log_level="CRITICAL",
    )
    dependencies = build_dependencies(settings, embeddings=FakeEmbeddings())
    return McpTestContext(
        server=build_server(dependencies),
        settings=settings,
        data_dir=DATA_DIR,
    )


@pytest.fixture
def rag_top_k(mcp_context: McpTestContext) -> int:
    return mcp_context.settings.rag_top_k


@pytest_asyncio.fixture
async def client(mcp_context: McpTestContext) -> AsyncIterator[Client]:
    async with Client(mcp_context.server) as connected_client:
        yield connected_client
