import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def normalize_search_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(char for char in value if not unicodedata.combining(char))


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, Field(ge=0), AfterValidator(_quantize_money)]


class ProductSearchInput(BaseModel):
    query: str | None = None
    category: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    only_in_stock: bool = True
    sort_by: Literal["relevance", "price_asc", "price_desc"] = "relevance"
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must be less than or equal to max_price")
        return self


class ProductSummary(BaseModel):
    product_id: int
    name: str
    category: str
    price_brl: Money
    stock_quantity: int = Field(ge=0)
    status: str
    description: str | None = None


class ProductSearchResult(BaseModel):
    items: list[ProductSummary]
    total: int = Field(ge=0)
    has_more: bool
    applied_filters: dict[str, object]


class PromotionSearchInput(BaseModel):
    query: str | None = None
    category: str | None = None
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0)


class PromotionSummary(BaseModel):
    promotion_id: int
    description: str
    product_id: int
    product_name: str
    category: str
    product_status: str
    stock_quantity: int = Field(ge=0)
    is_available: bool
    original_price_brl: Money
    discount_percent: Decimal = Field(ge=0, le=100)
    promotional_price_brl: Money


class PromotionSearchResult(BaseModel):
    items: list[PromotionSummary]
    total: int = Field(ge=0)
    has_more: bool
    applied_filters: dict[str, object]


class OrderQuery(BaseModel):
    order_id: int


class OrderItemDetails(BaseModel):
    product_id: int
    product_name: str
    quantity: int = Field(gt=0)


class OrderDetails(BaseModel):
    order_id: int
    customer_id: int
    order_date: date
    status: str
    total_brl: Money
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: list[OrderItemDetails]


class PolicyChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    section: str
    text: str


class PolicyQueryResult(BaseModel):
    query: str
    chunks: list[PolicyChunk]


__all__ = [
    "OrderDetails",
    "OrderItemDetails",
    "OrderQuery",
    "PolicyChunk",
    "PolicyQueryResult",
    "ProductSearchInput",
    "ProductSearchResult",
    "ProductSummary",
    "PromotionSearchInput",
    "PromotionSearchResult",
    "PromotionSummary",
    "normalize_search_text",
]
