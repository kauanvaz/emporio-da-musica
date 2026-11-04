from mcp_server.domain.errors import NO_RESULTS, VALIDATION_ERROR, DomainError
from mcp_server.domain.models import PolicyQueryResult
from mcp_server.rag.retriever import PolicyRetrieverProtocol


class PolicyService:
    def __init__(self, retriever: PolicyRetrieverProtocol) -> None:
        self._retriever = retriever

    def query_policy(self, query: str) -> PolicyQueryResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise DomainError(VALIDATION_ERROR, "Query must not be empty.")

        chunks = self._retriever.retrieve(normalized_query)
        if not chunks:
            raise DomainError(
                NO_RESULTS,
                "No policy content found for the given query.",
            )
        return PolicyQueryResult(query=normalized_query, chunks=chunks)


__all__ = ["PolicyService"]
