from __future__ import annotations

import csv
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, TypedDict

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

CSV_PREFIX = "desafio_tecnico_ai_eng - "
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXPECTED_TOOL_NAMES = {
    "search_products",
    "list_active_promotions",
    "get_order_status",
    "query_policy",
}


class ExpectedOrderItem(TypedDict):
    product_id: int
    product_name: str
    quantity: int


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(
        character for character in value if not unicodedata.combining(character)
    )


def _rows(filename: str) -> list[dict[str, str]]:
    path = DATA_DIR / f"{CSV_PREFIX}{filename}"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _money(value: str | Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


async def _call(
    client: Client,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await client.call_tool(tool_name, arguments or {})
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.asyncio
async def test_server_lists_exactly_the_four_tools(client: Client) -> None:
    tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES
    assert len(tools) == 4


@pytest.mark.asyncio
async def test_search_products_ignores_accents(client: Client) -> None:
    accented = await _call(client, "search_products", {"query": "Violão"})
    plain = await _call(client, "search_products", {"query": "violao"})

    assert accented["total"] == plain["total"]
    assert [int(item["product_id"]) for item in accented["items"]] == [
        int(item["product_id"]) for item in plain["items"]
    ]


@pytest.mark.asyncio
async def test_search_products_respects_max_price(client: Client) -> None:
    max_price = Decimal("500.00")
    expected = sorted(
        (
            (Decimal(product["price_brl"]), int(product["product_id"]))
            for product in _rows("products.csv")
            if product["status"] == "active"
            and int(product["stock_quantity"]) > 0
            and Decimal(product["price_brl"]) <= max_price
        ),
    )

    result = await _call(
        client,
        "search_products",
        {"max_price": "500.00", "sort_by": "price_asc", "limit": 25},
    )

    assert result["total"] == len(expected)
    assert [int(item["product_id"]) for item in result["items"]] == [
        product_id for _, product_id in expected
    ]
    assert all(Decimal(item["price_brl"]) <= max_price for item in result["items"])


@pytest.mark.asyncio
async def test_search_products_returns_pagination_totals(client: Client) -> None:
    query = "violao"
    normalized_query = _normalize(query)
    expected = sorted(
        (
            (Decimal(product["price_brl"]), int(product["product_id"]))
            for product in _rows("products.csv")
            if product["status"] == "active"
            and int(product["stock_quantity"]) > 0
            and (
                normalized_query in _normalize(product["name"])
                or normalized_query in _normalize(product["description"])
            )
        ),
    )

    first_page = await _call(
        client,
        "search_products",
        {"query": query, "sort_by": "price_asc", "limit": 10, "offset": 0},
    )
    second_page = await _call(
        client,
        "search_products",
        {"query": query, "sort_by": "price_asc", "limit": 10, "offset": 10},
    )

    assert first_page["total"] == len(expected)
    assert second_page["total"] == len(expected)
    assert [int(item["product_id"]) for item in first_page["items"]] == [
        product_id for _, product_id in expected[:10]
    ]
    assert [int(item["product_id"]) for item in second_page["items"]] == [
        product_id for _, product_id in expected[10:20]
    ]
    assert first_page["has_more"] is True
    assert second_page["has_more"] is (len(expected) > 20)


@pytest.mark.asyncio
async def test_list_active_promotions_excludes_inactive(client: Client) -> None:
    promotions = _rows("promotions.csv")
    active_ids = {
        int(promotion["promotion_id"])
        for promotion in promotions
        if promotion["is_active"] == "1"
    }
    inactive_ids = {
        int(promotion["promotion_id"])
        for promotion in promotions
        if promotion["is_active"] != "1"
    }

    result = await _call(client, "list_active_promotions", {"limit": 25})
    returned_ids = {int(item["promotion_id"]) for item in result["items"]}

    assert result["total"] == len(active_ids)
    assert returned_ids == active_ids
    assert returned_ids.isdisjoint(inactive_ids)


@pytest.mark.asyncio
async def test_list_active_promotions_computes_exact_price(client: Client) -> None:
    products = {
        int(product["product_id"]): product for product in _rows("products.csv")
    }
    promotions = {
        int(promotion["promotion_id"]): promotion
        for promotion in _rows("promotions.csv")
        if promotion["is_active"] == "1"
    }

    result = await _call(client, "list_active_promotions", {"limit": 25})

    assert result["items"]
    for item in result["items"]:
        promotion = promotions[int(item["promotion_id"])]
        product = products[int(promotion["product_id"])]
        original_price = Decimal(product["price_brl"]).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        promotional_price = (
            original_price
            * (Decimal(100) - Decimal(promotion["discount_percent"]))
            / Decimal(100)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert item["original_price_brl"] == _money(original_price)
        assert item["promotional_price_brl"] == _money(promotional_price)


@pytest.mark.asyncio
async def test_get_order_status_returns_order_with_items(client: Client) -> None:
    order_id = 15
    orders = {int(order["order_id"]): order for order in _rows("orders.csv")}
    products = {
        int(product["product_id"]): product for product in _rows("products.csv")
    }
    order = orders[order_id]
    expected_items: list[ExpectedOrderItem] = sorted(
        (
            ExpectedOrderItem(
                product_id=int(item["product_id"]),
                product_name=products[int(item["product_id"])]["name"],
                quantity=int(item["quantity"]),
            )
            for item in _rows("order_items.csv")
            if int(item["order_id"]) == order_id
        ),
        key=lambda item: item["product_id"],
    )

    result = await _call(client, "get_order_status", {"order_id": order_id})

    assert result["order_id"] == order_id
    assert result["customer_id"] == int(order["customer_id"])
    assert result["order_date"] == order["order_date"]
    assert result["status"] == order["status"]
    assert result["total_brl"] == _money(order["total_brl"])
    assert result["payment_method"] == order["payment_method"]
    assert result["tracking_code"] is None
    assert result["estimated_delivery"] is None
    assert result["notes"] is None
    assert result["items"] == expected_items


@pytest.mark.asyncio
async def test_get_order_status_of_missing_order_returns_error(client: Client) -> None:
    order_id = max(int(order["order_id"]) for order in _rows("orders.csv")) + 1

    with pytest.raises(ToolError) as exc_info:
        await client.call_tool("get_order_status", {"order_id": order_id})

    message = str(exc_info.value)
    assert message.startswith("ORDER_NOT_FOUND:")
    assert "Order not found." in message
    assert "Traceback" not in message


@pytest.mark.asyncio
async def test_query_policy_returns_top_k_chunks(
    client: Client,
    rag_top_k: int,
) -> None:
    query = "prazo de entrega"

    result = await _call(client, "query_policy", {"query": query})
    chunks = result["chunks"]

    assert result["query"] == query
    assert 1 <= len(chunks) <= rag_top_k
    for chunk in chunks:
        assert isinstance(chunk["chunk_id"], str)
        assert chunk["chunk_id"]
        assert isinstance(chunk["section"], str)
        assert chunk["section"].strip()
        assert isinstance(chunk["text"], str)
        assert chunk["text"].strip()
