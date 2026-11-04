from pathlib import Path

import chromadb
from chromadb.errors import NotFoundError
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from mcp_server.config import Settings
from mcp_server.domain.models import normalize_search_text
from mcp_server.rag.chunking import PolicyChunkingError, chunk_policy_manual
from mcp_server.rag.embeddings import (
    EmbeddingConfigurationError,
    create_policy_embeddings,
)
from mcp_server.rag.parsing import PolicyParsingError, parse_policy_manual
from mcp_server.rag.retriever import PolicyRetriever

_STATUS_KEY = "status"
_STATUS_INCOMPLETE = "indexing"
_STATUS_READY = "ready"


class PolicyIndexError(RuntimeError):
    pass


def ensure_policy_index(
    settings: Settings,
    embeddings: Embeddings | None = None,
) -> PolicyRetriever:
    try:
        policy_embeddings = embeddings or create_policy_embeddings(settings)
    except EmbeddingConfigurationError as exc:
        raise PolicyIndexError(str(exc)) from exc

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    existing = _get_collection(client, settings.chroma_collection_name)

    if existing is not None and _collection_status(existing) == _STATUS_READY:
        store = _open_store(
            client,
            collection_name=settings.chroma_collection_name,
            embeddings=policy_embeddings,
        )
        return _build_retriever(store, policy_embeddings, settings)

    if existing is not None:
        client.delete_collection(settings.chroma_collection_name)

    store = _open_store(
        client,
        collection_name=settings.chroma_collection_name,
        embeddings=policy_embeddings,
        collection_metadata={_STATUS_KEY: _STATUS_INCOMPLETE},
    )
    pdf_path = Path(settings.policy_pdf_path)
    if not pdf_path.is_file():
        raise PolicyIndexError(
            f"Policy PDF not found at {pdf_path}. "
            "Set POLICY_PDF_PATH to a valid policy manual."
        )

    try:
        markdown = parse_policy_manual(pdf_path)
        chunks = chunk_policy_manual(
            markdown,
            document_id=_document_id(pdf_path),
            max_chunk_chars=settings.rag_max_chunk_chars,
            chunk_overlap_chars=settings.rag_chunk_overlap_chars,
        )
    except (PolicyParsingError, PolicyChunkingError) as exc:
        raise PolicyIndexError(
            f"Could not prepare policy manual at {pdf_path} for indexing: {exc}"
        ) from exc

    ids = [chunk.chunk_id for chunk in chunks]
    if len(set(ids)) != len(ids):
        raise PolicyIndexError("Policy manual produced duplicate chunk ids.")

    try:
        store.add_texts(
            texts=[chunk.text for chunk in chunks],
            metadatas=[
                {"chunk_id": chunk.chunk_id, "section": chunk.section}
                for chunk in chunks
            ],
            ids=ids,
        )
    except Exception as exc:
        raise PolicyIndexError(
            f"Failed to index policy manual at {pdf_path}: {exc}"
        ) from exc

    collection = store._collection
    indexed_count = collection.count()
    if indexed_count != len(chunks):
        raise PolicyIndexError(
            "Policy index validation failed: expected "
            f"{len(chunks)} chunk(s) but Chroma has {indexed_count}."
        )
    collection.modify(metadata={_STATUS_KEY: _STATUS_READY})

    return _build_retriever(store, policy_embeddings, settings)


def _get_collection(
    client: chromadb.ClientAPI,
    collection_name: str,
) -> chromadb.Collection | None:
    try:
        return client.get_collection(collection_name)
    except NotFoundError:
        return None


def _collection_status(collection: chromadb.Collection) -> str | None:
    metadata = collection.metadata or {}
    status = metadata.get(_STATUS_KEY)
    return status if isinstance(status, str) else None


def _open_store(
    client: chromadb.ClientAPI,
    *,
    collection_name: str,
    embeddings: Embeddings,
    collection_metadata: dict[str, str] | None = None,
) -> Chroma:
    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
        collection_metadata=collection_metadata,
    )


def _document_id(pdf_path: Path) -> str:
    normalized = normalize_search_text(pdf_path.stem)
    return normalized or "policy_manual"


def _build_retriever(
    store: Chroma,
    embeddings: Embeddings,
    settings: Settings,
) -> PolicyRetriever:
    return PolicyRetriever(
        vector_store=store,
        embeddings=embeddings,
        top_k=settings.rag_top_k,
    )


__all__ = ["PolicyIndexError", "ensure_policy_index"]
