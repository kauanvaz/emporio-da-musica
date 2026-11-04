from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
)

from mcp_server.domain.enums import OrderStatus, PaymentMethod, ProductStatus

metadata = MetaData()

PRODUCT_STATUSES = tuple(status.value for status in ProductStatus)
ORDER_STATUSES = tuple(status.value for status in OrderStatus)
PAYMENT_METHODS = tuple(method.value for method in PaymentMethod)


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


categories = Table(
    "categories",
    metadata,
    Column("category_id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False),
    Column("name_normalized", String, nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("product_id", Integer, primary_key=True),
    Column("price_brl", Numeric(12, 2), nullable=False),
    Column("name", String, nullable=False),
    Column(
        "category_id",
        Integer,
        ForeignKey("categories.category_id"),
        nullable=False,
    ),
    Column("description", String, nullable=False),
    Column("stock_quantity", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("specs", String, nullable=False),
    Column("created_at", Date, nullable=False),
    Column("name_normalized", String, nullable=False),
    Column("description_normalized", String, nullable=False),
    CheckConstraint("price_brl >= 0", name="ck_products_price_non_negative"),
    CheckConstraint(
        "stock_quantity >= 0",
        name="ck_products_stock_non_negative",
    ),
    CheckConstraint(
        f"status IN ({_quoted_values(PRODUCT_STATUSES)})",
        name="ck_products_status",
    ),
)

promotions = Table(
    "promotions",
    metadata,
    Column("promotion_id", Integer, primary_key=True),
    Column(
        "product_id",
        Integer,
        ForeignKey("products.product_id"),
        nullable=False,
    ),
    Column("discount_percent", Numeric(5, 2), nullable=False),
    Column("description", String, nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("description_normalized", String, nullable=False),
    CheckConstraint(
        "discount_percent >= 0 AND discount_percent <= 100",
        name="ck_promotions_discount_percent_range",
    ),
)

customers = Table(
    "customers",
    metadata,
    Column("customer_id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("phone", String, nullable=False),
    Column("email", String, nullable=False),
    Column("city", String, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("order_id", Integer, primary_key=True),
    Column(
        "customer_id",
        Integer,
        ForeignKey("customers.customer_id"),
        nullable=False,
    ),
    Column("order_date", Date, nullable=False),
    Column("status", String, nullable=False),
    Column("total_brl", Numeric(12, 2), nullable=False),
    Column("payment_method", String, nullable=False),
    Column("tracking_code", String, nullable=True),
    Column("estimated_delivery", Date, nullable=True),
    Column("notes", String, nullable=True),
    CheckConstraint("total_brl >= 0", name="ck_orders_total_non_negative"),
    CheckConstraint(
        f"status IN ({_quoted_values(ORDER_STATUSES)})",
        name="ck_orders_status",
    ),
    CheckConstraint(
        f"payment_method IN ({_quoted_values(PAYMENT_METHODS)})",
        name="ck_orders_payment_method",
    ),
)

order_items = Table(
    "order_items",
    metadata,
    Column(
        "order_id",
        Integer,
        ForeignKey("orders.order_id"),
        nullable=False,
    ),
    Column(
        "product_id",
        Integer,
        ForeignKey("products.product_id"),
        nullable=False,
    ),
    Column("quantity", Integer, nullable=False),
    PrimaryKeyConstraint("order_id", "product_id", name="pk_order_items"),
    CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
)

__all__ = [
    "ORDER_STATUSES",
    "PAYMENT_METHODS",
    "PRODUCT_STATUSES",
    "categories",
    "customers",
    "metadata",
    "order_items",
    "orders",
    "products",
    "promotions",
]
