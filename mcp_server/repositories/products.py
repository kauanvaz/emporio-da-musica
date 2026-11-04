from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from sqlalchemy import ColumnElement, Engine, case, func, or_, select

from mcp_server.database.schema import categories, products
from mcp_server.domain.enums import ProductStatus
from mcp_server.domain.models import (
    ProductSearchInput,
    ProductSearchResult,
    ProductSummary,
    normalize_search_text,
)


class ProductRepository(Protocol):
    def search(self, filters: ProductSearchInput) -> ProductSearchResult: ...


class SQLiteProductRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search(self, filters: ProductSearchInput) -> ProductSearchResult:
        normalized_query = _normalize_filter(filters.query)
        normalized_category = _normalize_filter(filters.category)

        conditions: list[ColumnElement[bool]] = []
        if normalized_query is not None:
            conditions.append(
                or_(
                    products.c.name_normalized.contains(
                        normalized_query,
                        autoescape=True,
                    ),
                    products.c.description_normalized.contains(
                        normalized_query,
                        autoescape=True,
                    ),
                )
            )
        if normalized_category is not None:
            conditions.append(categories.c.name_normalized == normalized_category)
        if filters.min_price is not None:
            conditions.append(products.c.price_brl >= filters.min_price)
        if filters.max_price is not None:
            conditions.append(products.c.price_brl <= filters.max_price)
        if filters.only_in_stock:
            conditions.append(products.c.stock_quantity > 0)
            conditions.append(products.c.status == ProductStatus.ACTIVE.value)

        order_by = _order_by(filters, normalized_query)

        join_condition = products.c.category_id == categories.c.category_id
        count_statement = (
            select(func.count())
            .select_from(products.join(categories, join_condition))
            .where(*conditions)
        )
        page_statement = (
            select(
                products.c.product_id,
                products.c.name,
                categories.c.name.label("category"),
                products.c.price_brl,
                products.c.stock_quantity,
                products.c.status,
                products.c.description,
            )
            .select_from(products.join(categories, join_condition))
            .where(*conditions)
            .order_by(*order_by)
            .limit(filters.limit)
            .offset(filters.offset)
        )

        with self._engine.connect() as connection:
            total = int(connection.execute(count_statement).scalar_one())
            rows = connection.execute(page_statement).mappings().all()

        items = [
            ProductSummary(
                product_id=row["product_id"],
                name=row["name"],
                category=row["category"],
                price_brl=row["price_brl"],
                stock_quantity=row["stock_quantity"],
                status=row["status"],
                description=row["description"],
            )
            for row in rows
        ]

        return ProductSearchResult(
            items=items,
            total=total,
            has_more=filters.offset + len(items) < total,
            applied_filters=_applied_filters(
                filters,
                normalized_query,
                normalized_category,
            ),
        )


def _normalize_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_search_text(value)
    return normalized or None


def _order_by(
    filters: ProductSearchInput,
    normalized_query: str | None,
) -> tuple[ColumnElement[Any], ...]:
    if filters.sort_by == "price_asc":
        return (products.c.price_brl.asc(), products.c.product_id.asc())
    if filters.sort_by == "price_desc":
        return (products.c.price_brl.desc(), products.c.product_id.asc())
    if normalized_query is not None:
        relevance = case(
            (products.c.name_normalized == normalized_query, 0),
            (
                products.c.name_normalized.startswith(
                    normalized_query,
                    autoescape=True,
                ),
                1,
            ),
            (
                products.c.name_normalized.contains(
                    normalized_query,
                    autoescape=True,
                ),
                2,
            ),
            else_=3,
        )
        return (relevance.asc(), products.c.product_id.asc())
    return (products.c.product_id.asc(),)


def _format_money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _applied_filters(
    filters: ProductSearchInput,
    normalized_query: str | None,
    normalized_category: str | None,
) -> dict[str, object]:
    applied: dict[str, object] = {}
    if normalized_query is not None:
        applied["query"] = normalized_query
    if normalized_category is not None:
        applied["category"] = normalized_category
    if filters.min_price is not None:
        applied["min_price"] = _format_money(filters.min_price)
    if filters.max_price is not None:
        applied["max_price"] = _format_money(filters.max_price)
    applied["only_in_stock"] = filters.only_in_stock
    applied["sort_by"] = filters.sort_by
    applied["limit"] = filters.limit
    applied["offset"] = filters.offset
    return applied


__all__ = ["ProductRepository", "SQLiteProductRepository"]
