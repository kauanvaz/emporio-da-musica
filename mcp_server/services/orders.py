from mcp_server.domain.errors import ORDER_NOT_FOUND, DomainError
from mcp_server.domain.models import OrderDetails, OrderQuery
from mcp_server.repositories.orders import OrderRepository


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def get_order_status(self, query: OrderQuery) -> OrderDetails:
        order = self._repository.get_by_id(query.order_id)
        if order is None:
            raise DomainError(ORDER_NOT_FOUND, "Order not found.")
        return order


__all__ = ["OrderService"]
