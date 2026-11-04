from decimal import ROUND_HALF_UP, Decimal

from mcp_server.domain.enums import ProductStatus
from mcp_server.domain.errors import NO_RESULTS, DomainError
from mcp_server.domain.models import (
    PromotionSearchInput,
    PromotionSearchResult,
    PromotionSummary,
)
from mcp_server.repositories.promotions import PromotionRepository


class PromotionService:
    def __init__(self, repository: PromotionRepository) -> None:
        self._repository = repository

    def list_active_promotions(
        self,
        filters: PromotionSearchInput,
    ) -> PromotionSearchResult:
        result = self._repository.list_active(filters)
        if not result.items:
            raise DomainError(
                NO_RESULTS,
                "No active promotions found for the given filters.",
            )
        return PromotionSearchResult(
            items=[_with_pricing(item) for item in result.items],
            total=result.total,
            has_more=result.has_more,
            applied_filters=result.applied_filters,
        )


def _with_pricing(item: PromotionSummary) -> PromotionSummary:
    return PromotionSummary(
        promotion_id=item.promotion_id,
        description=item.description,
        product_id=item.product_id,
        product_name=item.product_name,
        category=item.category,
        product_status=item.product_status,
        stock_quantity=item.stock_quantity,
        is_available=(
            item.product_status == ProductStatus.ACTIVE.value
            and item.stock_quantity > 0
        ),
        original_price_brl=item.original_price_brl,
        discount_percent=item.discount_percent,
        promotional_price_brl=_promotional_price(
            item.original_price_brl,
            item.discount_percent,
        ),
    )


def _promotional_price(
    original_price: Decimal,
    discount_percent: Decimal,
) -> Decimal:
    return (original_price * (Decimal(100) - discount_percent) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


__all__ = ["PromotionService"]
