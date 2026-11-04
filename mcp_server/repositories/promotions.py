from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from sqlalchemy import ColumnElement, Engine, Join, RowMapping, func, or_, select

from mcp_server.database.schema import categories, products, promotions
from mcp_server.domain.enums import ProductStatus
from mcp_server.domain.models import (
    PromotionSearchInput,
    PromotionSearchResult,
    PromotionSummary,
    normalize_search_text,
)


class PromotionRepository(Protocol):
    def list_active(
        self,
        filters: PromotionSearchInput,
    ) -> PromotionSearchResult: ...


class SQLitePromotionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_active(
        self,
        filters: PromotionSearchInput,
    ) -> PromotionSearchResult:
        normalized_query = _normalize_filter(filters.query)
        normalized_category = _normalize_filter(filters.category)

        conditions: list[ColumnElement[bool]] = [promotions.c.is_active.is_(True)]
        if normalized_query is not None:
            conditions.append(
                or_(
                    promotions.c.description_normalized.contains(
                        normalized_query,
                        autoescape=True,
                    ),
                    products.c.name_normalized.contains(
                        normalized_query,
                        autoescape=True,
                    ),
                )
            )
        if normalized_category is not None:
            conditions.append(categories.c.name_normalized == normalized_category)

        from_clause = _from_clause()
        count_statement = (
            select(func.count()).select_from(from_clause).where(*conditions)
        )
        page_statement = (
            select(
                promotions.c.promotion_id,
                promotions.c.description,
                products.c.product_id,
                products.c.name.label("product_name"),
                categories.c.name.label("category"),
                products.c.status.label("product_status"),
                products.c.stock_quantity,
                products.c.price_brl.label("original_price_brl"),
                promotions.c.discount_percent,
            )
            .select_from(from_clause)
            .where(*conditions)
            .order_by(promotions.c.promotion_id.asc())
            .limit(filters.limit)
            .offset(filters.offset)
        )

        with self._engine.connect() as connection:
            total = int(connection.execute(count_statement).scalar_one())
            rows = connection.execute(page_statement).mappings().all()

        items = [_to_summary(row) for row in rows]

        return PromotionSearchResult(
            items=items,
            total=total,
            has_more=filters.offset + len(items) < total,
            applied_filters=_applied_filters(
                filters,
                normalized_query,
                normalized_category,
            ),
        )


def _from_clause() -> Join:
    return products.join(
        promotions,
        promotions.c.product_id == products.c.product_id,
    ).join(
        categories,
        products.c.category_id == categories.c.category_id,
    )


def _to_summary(row: RowMapping) -> PromotionSummary:
    product_status = str(row["product_status"])
    stock_quantity = int(row["stock_quantity"])
    original_price = Decimal(str(row["original_price_brl"]))
    discount_percent = Decimal(str(row["discount_percent"]))
    promotional_price = (
        original_price * (Decimal(100) - discount_percent) / Decimal(100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return PromotionSummary(
        promotion_id=int(row["promotion_id"]),
        description=str(row["description"]),
        product_id=int(row["product_id"]),
        product_name=str(row["product_name"]),
        category=str(row["category"]),
        product_status=product_status,
        stock_quantity=stock_quantity,
        is_available=(
            product_status == ProductStatus.ACTIVE.value and stock_quantity > 0
        ),
        original_price_brl=original_price,
        discount_percent=discount_percent,
        promotional_price_brl=promotional_price,
    )


def _normalize_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_search_text(value)
    return normalized or None


def _applied_filters(
    filters: PromotionSearchInput,
    normalized_query: str | None,
    normalized_category: str | None,
) -> dict[str, object]:
    applied: dict[str, object] = {}
    if normalized_query is not None:
        applied["query"] = normalized_query
    if normalized_category is not None:
        applied["category"] = normalized_category
    applied["limit"] = filters.limit
    applied["offset"] = filters.offset
    return applied


__all__ = ["PromotionRepository", "SQLitePromotionRepository"]
