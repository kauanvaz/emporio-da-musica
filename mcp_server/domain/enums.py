from enum import StrEnum


class ProductStatus(StrEnum):
    ACTIVE = "active"
    COMING_SOON = "coming_soon"
    DISCONTINUED = "discontinued"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentMethod(StrEnum):
    PIX = "pix"
    DEBIT = "debit"
    BOLETO = "boleto"
    CREDIT_3X = "credit_3x"
    CREDIT_6X = "credit_6x"
    CREDIT_12X = "credit_12x"
