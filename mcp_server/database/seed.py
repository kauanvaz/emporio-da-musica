import csv
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Engine, Table, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from mcp_server.database.engine import create_seed_engine
from mcp_server.database.schema import (
    categories,
    customers,
    metadata,
    order_items,
    orders,
    products,
    promotions,
)
from mcp_server.domain.enums import OrderStatus, PaymentMethod, ProductStatus
from mcp_server.domain.models import normalize_search_text

CSV_PREFIX = "desafio_tecnico_ai_eng - "

CATEGORIES_FILENAME = f"{CSV_PREFIX}categories.csv"
CUSTOMERS_FILENAME = f"{CSV_PREFIX}customers.csv"
ORDER_ITEMS_FILENAME = f"{CSV_PREFIX}order_items.csv"
ORDERS_FILENAME = f"{CSV_PREFIX}orders.csv"
PRODUCTS_FILENAME = f"{CSV_PREFIX}products.csv"
PROMOTIONS_FILENAME = f"{CSV_PREFIX}promotions.csv"

CATEGORY_HEADERS = ("category_id", "name", "description")
CUSTOMER_HEADERS = ("customer_id", "name", "phone", "email", "city")
ORDER_ITEM_HEADERS = ("order_id", "quantity", "product_id")
ORDER_HEADERS = (
    "order_id",
    "customer_id",
    "order_date",
    "status",
    "total_brl",
    "payment_method",
    "tracking_code",
    "estimated_delivery",
    "notes",
)
PRODUCT_HEADERS = (
    "product_id",
    "price_brl",
    "name",
    "category_id",
    "description",
    "stock_quantity",
    "status",
    "specs",
    "created_at",
)
PROMOTION_HEADERS = (
    "promotion_id",
    "product_id",
    "discount_percent",
    "description",
    "is_active",
)


class SeedValidationError(Exception):
    """Raised when seed data or the generated database is invalid."""


class CategoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ProductRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: int = Field(ge=1)
    price_brl: Decimal = Field(ge=0)
    name: str = Field(min_length=1)
    category_id: int = Field(ge=1)
    description: str = Field(min_length=1)
    stock_quantity: int = Field(ge=0)
    status: ProductStatus
    specs: dict[str, object]
    created_at: date

    @field_validator("specs", mode="before")
    @classmethod
    def parse_specs(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("specs must be a valid JSON object") from exc
        if not isinstance(parsed, dict):
            raise TypeError("specs must be a JSON object")
        return parsed


class PromotionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    promotion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    discount_percent: Decimal = Field(ge=0, le=100)
    description: str = Field(min_length=1)
    is_active: bool

    @field_validator("is_active", mode="before")
    @classmethod
    def parse_is_active(cls, value: object) -> object:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if normalized == "1":
                return True
            if normalized == "0":
                return False
        raise ValueError("is_active must be 0 or 1")


class CustomerRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    email: str = Field(min_length=1)
    city: str = Field(min_length=1)


class OrderRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: int = Field(ge=1)
    customer_id: int = Field(ge=1)
    order_date: date
    status: OrderStatus
    total_brl: Decimal = Field(ge=0)
    payment_method: PaymentMethod
    tracking_code: str | None = None
    estimated_delivery: date | None = None
    notes: str | None = None

    @field_validator("tracking_code", "notes", mode="before")
    @classmethod
    def empty_text_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("estimated_delivery", mode="before")
    @classmethod
    def empty_date_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class OrderItemRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    quantity: int = Field(gt=0)


@dataclass(frozen=True)
class _LoadedData:
    categories: list[tuple[int, CategoryRow]]
    products: list[tuple[int, ProductRow]]
    promotions: list[tuple[int, PromotionRow]]
    customers: list[tuple[int, CustomerRow]]
    orders: list[tuple[int, OrderRow]]
    order_items: list[tuple[int, OrderItemRow]]


def _format_validation_error(
    path: Path,
    line: int,
    error: ValidationError,
) -> str:
    details = error.errors()[0]
    location = ".".join(str(part) for part in details["loc"])
    return f"{path}:{line}: invalid value for '{location}': {details['msg']}"


def _read_csv[ModelT: BaseModel](
    path: Path,
    headers: tuple[str, ...],
    model: type[ModelT],
) -> list[tuple[int, ModelT]]:
    if not path.is_file():
        raise SeedValidationError(f"{path}: CSV file not found")

    rows: list[tuple[int, ModelT]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise SeedValidationError(f"{path}:1: CSV file has no header")

            if tuple(reader.fieldnames) != headers:
                raise SeedValidationError(
                    f"{path}:1: invalid headers {reader.fieldnames}; "
                    f"expected {list(headers)}"
                )

            for raw_row in reader:
                line = reader.line_num
                if None in raw_row or any(
                    raw_row.get(header) is None for header in headers
                ):
                    raise SeedValidationError(f"{path}:{line}: wrong number of columns")
                try:
                    row = model.model_validate(raw_row)
                except ValidationError as exc:
                    raise SeedValidationError(
                        _format_validation_error(path, line, exc)
                    ) from exc
                except TypeError as exc:
                    raise SeedValidationError(
                        f"{path}:{line}: invalid value: {exc}"
                    ) from exc
                rows.append((line, row))
    except OSError as exc:
        raise SeedValidationError(f"{path}: could not read CSV file: {exc}") from exc

    return rows


def _load_all(data_dir: Path) -> _LoadedData:
    return _LoadedData(
        categories=_read_csv(
            data_dir / CATEGORIES_FILENAME,
            CATEGORY_HEADERS,
            CategoryRow,
        ),
        products=_read_csv(
            data_dir / PRODUCTS_FILENAME,
            PRODUCT_HEADERS,
            ProductRow,
        ),
        promotions=_read_csv(
            data_dir / PROMOTIONS_FILENAME,
            PROMOTION_HEADERS,
            PromotionRow,
        ),
        customers=_read_csv(
            data_dir / CUSTOMERS_FILENAME,
            CUSTOMER_HEADERS,
            CustomerRow,
        ),
        orders=_read_csv(
            data_dir / ORDERS_FILENAME,
            ORDER_HEADERS,
            OrderRow,
        ),
        order_items=_read_csv(
            data_dir / ORDER_ITEMS_FILENAME,
            ORDER_ITEM_HEADERS,
            OrderItemRow,
        ),
    )


def _ensure_unique_ids[ModelT: BaseModel](
    rows: list[tuple[int, ModelT]],
    field: str,
    path: Path,
) -> dict[int, int]:
    seen: dict[int, int] = {}
    for line, row in rows:
        value = getattr(row, field)
        if value in seen:
            raise SeedValidationError(
                f"{path}:{line}: duplicate {field} {value!r}; "
                f"first occurrence on line {seen[value]}"
            )
        seen[value] = line
    return seen


def _validate_reference[ModelT: BaseModel](
    rows: list[tuple[int, ModelT]],
    field: str,
    references: Mapping[int, int],
    source_path: Path,
    target_filename: str,
) -> None:
    for line, row in rows:
        value = getattr(row, field)
        if value not in references:
            raise SeedValidationError(
                f"{source_path}:{line}: {field} {value!r} "
                f"does not exist in {target_filename}"
            )


def _validate_loaded_data(data: _LoadedData, data_dir: Path) -> None:
    categories_path = data_dir / CATEGORIES_FILENAME
    products_path = data_dir / PRODUCTS_FILENAME
    promotions_path = data_dir / PROMOTIONS_FILENAME
    customers_path = data_dir / CUSTOMERS_FILENAME
    orders_path = data_dir / ORDERS_FILENAME
    order_items_path = data_dir / ORDER_ITEMS_FILENAME

    category_ids = _ensure_unique_ids(
        data.categories,
        "category_id",
        categories_path,
    )
    product_ids = _ensure_unique_ids(
        data.products,
        "product_id",
        products_path,
    )
    _ensure_unique_ids(
        data.promotions,
        "promotion_id",
        promotions_path,
    )
    customer_ids = _ensure_unique_ids(
        data.customers,
        "customer_id",
        customers_path,
    )
    order_ids = _ensure_unique_ids(data.orders, "order_id", orders_path)

    _validate_reference(
        data.products,
        "category_id",
        category_ids,
        products_path,
        CATEGORIES_FILENAME,
    )
    _validate_reference(
        data.promotions,
        "product_id",
        product_ids,
        promotions_path,
        PRODUCTS_FILENAME,
    )
    _validate_reference(
        data.orders,
        "customer_id",
        customer_ids,
        orders_path,
        CUSTOMERS_FILENAME,
    )
    _validate_reference(
        data.order_items,
        "order_id",
        order_ids,
        order_items_path,
        ORDERS_FILENAME,
    )
    _validate_reference(
        data.order_items,
        "product_id",
        product_ids,
        order_items_path,
        PRODUCTS_FILENAME,
    )


def _category_values(
    rows: list[tuple[int, CategoryRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "category_id": row.category_id,
                "name": row.name,
                "description": row.description,
                "name_normalized": normalize_search_text(row.name),
            },
        )
        for line, row in rows
    ]


def _product_values(
    rows: list[tuple[int, ProductRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "product_id": row.product_id,
                "price_brl": row.price_brl,
                "name": row.name,
                "category_id": row.category_id,
                "description": row.description,
                "stock_quantity": row.stock_quantity,
                "status": row.status.value,
                "specs": json.dumps(row.specs, ensure_ascii=False),
                "created_at": row.created_at,
                "name_normalized": normalize_search_text(row.name),
                "description_normalized": normalize_search_text(row.description),
            },
        )
        for line, row in rows
    ]


def _promotion_values(
    rows: list[tuple[int, PromotionRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "promotion_id": row.promotion_id,
                "product_id": row.product_id,
                "discount_percent": row.discount_percent,
                "description": row.description,
                "is_active": row.is_active,
                "description_normalized": normalize_search_text(row.description),
            },
        )
        for line, row in rows
    ]


def _customer_values(
    rows: list[tuple[int, CustomerRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "customer_id": row.customer_id,
                "name": row.name,
                "phone": row.phone,
                "email": row.email,
                "city": row.city,
            },
        )
        for line, row in rows
    ]


def _order_values(
    rows: list[tuple[int, OrderRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "order_date": row.order_date,
                "status": row.status.value,
                "total_brl": row.total_brl,
                "payment_method": row.payment_method.value,
                "tracking_code": row.tracking_code,
                "estimated_delivery": row.estimated_delivery,
                "notes": row.notes,
            },
        )
        for line, row in rows
    ]


def _order_item_values(
    rows: list[tuple[int, OrderItemRow]],
) -> list[tuple[int, dict[str, Any]]]:
    return [
        (
            line,
            {
                "order_id": row.order_id,
                "product_id": row.product_id,
                "quantity": row.quantity,
            },
        )
        for line, row in rows
    ]


def _insert_rows(
    connection: Connection,
    table: Table,
    source_path: Path,
    rows: Iterable[tuple[int, Mapping[str, Any]]],
) -> None:
    for line, values in rows:
        try:
            connection.execute(table.insert().values(**dict(values)))
        except IntegrityError as exc:
            detail = str(exc.orig).splitlines()[0]
            raise SeedValidationError(
                f"{source_path}:{line}: database constraint violation: {detail}"
            ) from exc


def _validate_inserted_rows(
    connection: Connection,
    expected_counts: Mapping[str, int],
) -> None:
    for table in metadata.sorted_tables:
        actual = connection.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        expected = expected_counts[table.name]
        if actual != expected:
            raise SeedValidationError(
                f"database validation failed: table '{table.name}' has "
                f"{actual} rows; expected {expected}"
            )

    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        table_name, rowid, parent, _ = violations[0]
        raise SeedValidationError(
            "database validation failed: foreign key check reported "
            f"table '{table_name}', row {rowid}, referencing '{parent}'"
        )


def seed_database(
    *,
    database_path: str | Path = "emporio.db",
    data_dir: str | Path = "data",
) -> Path:
    final_path = Path(database_path)
    data_path = Path(data_dir)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{final_path.name}.",
        suffix=".tmp",
        dir=final_path.parent,
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)
    engine: Engine | None = None

    try:
        engine = create_seed_engine(temp_path)
        metadata.create_all(engine)

        data = _load_all(data_path)
        _validate_loaded_data(data, data_path)

        category_rows = _category_values(data.categories)
        product_rows = _product_values(data.products)
        promotion_rows = _promotion_values(data.promotions)
        customer_rows = _customer_values(data.customers)
        order_rows = _order_values(data.orders)
        order_item_rows = _order_item_values(data.order_items)

        with engine.begin() as connection:
            _insert_rows(
                connection,
                categories,
                data_path / CATEGORIES_FILENAME,
                category_rows,
            )
            _insert_rows(
                connection,
                products,
                data_path / PRODUCTS_FILENAME,
                product_rows,
            )
            _insert_rows(
                connection,
                promotions,
                data_path / PROMOTIONS_FILENAME,
                promotion_rows,
            )
            _insert_rows(
                connection,
                customers,
                data_path / CUSTOMERS_FILENAME,
                customer_rows,
            )
            _insert_rows(
                connection,
                orders,
                data_path / ORDERS_FILENAME,
                order_rows,
            )
            _insert_rows(
                connection,
                order_items,
                data_path / ORDER_ITEMS_FILENAME,
                order_item_rows,
            )
            _validate_inserted_rows(
                connection,
                {
                    categories.name: len(category_rows),
                    products.name: len(product_rows),
                    promotions.name: len(promotion_rows),
                    customers.name: len(customer_rows),
                    orders.name: len(order_rows),
                    order_items.name: len(order_item_rows),
                },
            )

        engine.dispose()
        engine = None
        os.replace(temp_path, final_path)
        return final_path
    finally:
        if engine is not None:
            engine.dispose()
        temp_path.unlink(missing_ok=True)


__all__ = ["SeedValidationError", "seed_database"]
