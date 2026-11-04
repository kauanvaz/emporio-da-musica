from mcp_server.domain.errors import NO_RESULTS, DomainError
from mcp_server.domain.models import (
    ProductSearchInput,
    ProductSearchResult,
    normalize_search_text,
)
from mcp_server.repositories.products import ProductRepository


class ProductService:
    def __init__(self, repository: ProductRepository) -> None:
        self._repository = repository

    def search_products(self, filters: ProductSearchInput) -> ProductSearchResult:
        result = self._repository.search(_normalized(filters))
        if not result.items:
            raise DomainError(NO_RESULTS, "No products found for the given filters.")
        return result


def _normalized(filters: ProductSearchInput) -> ProductSearchInput:
    return filters.model_copy(
        update={
            "query": _normalize_optional(filters.query),
            "category": _normalize_optional(filters.category),
        },
    )


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_search_text(value)
    return normalized or None


__all__ = ["ProductService"]
