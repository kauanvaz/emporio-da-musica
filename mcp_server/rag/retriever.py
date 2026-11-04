from typing import Protocol

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from mcp_server.domain.models import PolicyChunk


class PolicyRetrievalError(RuntimeError):
    pass


class PolicyRetrieverProtocol(Protocol):
    def retrieve(self, query: str) -> list[PolicyChunk]: ...


class PolicyRetriever:
    def __init__(
        self,
        vector_store: Chroma,
        embeddings: Embeddings,
        top_k: int,
    ) -> None:
        if top_k < 1:
            raise ValueError("RAG_TOP_K must be greater than zero.")
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._top_k = top_k

    def retrieve(self, query: str) -> list[PolicyChunk]:
        embedding = self._embeddings.embed_query(query)
        documents = self._vector_store.similarity_search_by_vector(
            embedding,
            k=self._top_k,
        )
        return [_to_policy_chunk(document) for document in documents]


def _to_policy_chunk(document: Document) -> PolicyChunk:
    chunk_id = document.metadata.get("chunk_id") or document.id
    section = document.metadata.get("section")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise PolicyRetrievalError("Retrieved policy chunk is missing its chunk_id.")
    if not isinstance(section, str) or not section.strip():
        raise PolicyRetrievalError(
            f"Retrieved policy chunk {chunk_id!r} is missing its section."
        )
    return PolicyChunk(
        chunk_id=chunk_id,
        section=section,
        text=document.page_content,
    )


__all__ = [
    "PolicyRetrievalError",
    "PolicyRetriever",
    "PolicyRetrieverProtocol",
]
