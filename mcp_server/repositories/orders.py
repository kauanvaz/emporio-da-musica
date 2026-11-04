from typing import Protocol

from sqlalchemy import Engine, RowMapping, select

from mcp_server.database.schema import order_items, orders, products
from mcp_server.domain.models import OrderDetails, OrderItemDetails


class OrderRepository(Protocol):
    def get_by_id(self, order_id: int) -> OrderDetails | None: ...


class SQLiteOrderRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_id(self, order_id: int) -> OrderDetails | None:
        order_statement = select(
            orders.c.order_id,
            orders.c.customer_id,
            orders.c.order_date,
            orders.c.status,
            orders.c.total_brl,
            orders.c.payment_method,
            orders.c.tracking_code,
            orders.c.estimated_delivery,
            orders.c.notes,
        ).where(orders.c.order_id == order_id)

        item_statement = (
            select(
                order_items.c.product_id,
                products.c.name.label("product_name"),
                order_items.c.quantity,
            )
            .select_from(
                order_items.join(
                    products,
                    order_items.c.product_id == products.c.product_id,
                )
            )
            .where(order_items.c.order_id == order_id)
            .order_by(order_items.c.product_id.asc())
        )

        with self._engine.connect() as connection:
            order_row = connection.execute(order_statement).mappings().one_or_none()
            if order_row is None:
                return None
            item_rows = connection.execute(item_statement).mappings().all()

        return OrderDetails(
            order_id=order_row["order_id"],
            customer_id=order_row["customer_id"],
            order_date=order_row["order_date"],
            status=order_row["status"],
            total_brl=order_row["total_brl"],
            payment_method=order_row["payment_method"],
            tracking_code=order_row["tracking_code"],
            estimated_delivery=order_row["estimated_delivery"],
            notes=order_row["notes"],
            items=[_to_item(row) for row in item_rows],
        )


def _to_item(row: RowMapping) -> OrderItemDetails:
    return OrderItemDetails(
        product_id=int(row["product_id"]),
        product_name=str(row["product_name"]),
        quantity=int(row["quantity"]),
    )


__all__ = ["OrderRepository", "SQLiteOrderRepository"]
