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
    query = _normalize_optional(filters.query)
    category = _normalize_optional(filters.category)
    if query is not None and category is not None and _matches_category(query, category):
        query = None
    return filters.model_copy(
        update={
            "query": query,
            "category": category,
        },
    )


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_search_text(value)
    return normalized or None


def _matches_category(query: str, category: str) -> bool:
    query_forms = _singular_forms(query)
    category_forms = {
        form
        for term in category.replace("(", " ").replace(")", " ").split()
        for form in _singular_forms(term)
    }
    return not query_forms.isdisjoint(category_forms)


def _singular_forms(term: str) -> set[str]:
    forms = {term}
    if term.endswith("oes"):
        forms.add(f"{term[:-3]}ao")
    if term.endswith("s") and len(term) > 1:
        forms.add(term[:-1])
    return forms


__all__ = ["ProductService"]
