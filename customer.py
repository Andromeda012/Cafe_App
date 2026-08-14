from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderStatus(str, Enum):
    NEW = "Yeni"
    PREPARING = "Hazırlanıyor"
    READY = "Hazır"
    WITH_WAITER = "Garsona Teslim Edildi"
    DELIVERED = "Teslim Edildi"
    CANCELLED = "İptal Edildi"


class ServiceType(str, Enum):
    WAITER = "Garson Servisi"
    SELF = "Self Servis"


class OrderCreate(BaseModel):
    """Müşterinin onayladığı yeni sipariş için doğrulama modeli."""

    model_config = ConfigDict(str_strip_whitespace=True)

    guest_id: str = Field(min_length=16, max_length=100)
    name: str = Field(min_length=2, max_length=100)
    phone_number: str
    table: str = Field(min_length=2, max_length=10)
    total: float = Field(gt=0)
    service_type: ServiceType = ServiceType.WAITER
    service_fee: float = Field(default=0, ge=0)
    order_status: OrderStatus = OrderStatus.NEW
    order_date: datetime = Field(default_factory=datetime.now)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        cleaned = (
            value.replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        if cleaned.startswith("+90"):
            cleaned = "0" + cleaned[3:]
        elif cleaned.startswith("90") and len(cleaned) == 12:
            cleaned = "0" + cleaned[2:]
        elif len(cleaned) == 10 and cleaned.startswith("5"):
            cleaned = "0" + cleaned

        if not cleaned.isdigit():
            raise ValueError("Telefon numarası yalnızca rakamlardan oluşmalıdır.")
        if len(cleaned) != 11:
            raise ValueError("Telefon numarası 11 haneli olmalıdır.")
        if not cleaned.startswith("05"):
            raise ValueError("Telefon numarası 05 ile başlamalıdır.")

        return cleaned
