from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ---- User ----

class UserCreate(BaseModel):
    code: str  # 微信 login code


class UserOut(BaseModel):
    id: int
    open_id: str
    nickname: str
    notify_enabled: bool

    model_config = {"from_attributes": True}


# ---- Product ----

class ProductAdd(BaseModel):
    product_code: str  # 货号或链接
    title_hint: Optional[str] = None  # 商品标题（淘宝场景下用户手动粘贴）


class ProductOut(BaseModel):
    id: int
    internal_code: str
    product_code: str
    name: str
    original_price: float
    current_price: float
    min_size: str
    max_size: str
    sku_count: int
    evaluation_count: int
    is_active: bool
    url: str
    last_checked_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---- Price History ----

class PriceHistoryOut(BaseModel):
    price: float
    price_type: str
    recorded_at: datetime

    model_config = {"from_attributes": True}


# ---- WatchList ----

class WatchAdd(BaseModel):
    product_code: str
    target_price: Optional[float] = None
    title_hint: Optional[str] = None


class WatchOut(BaseModel):
    id: int
    product: ProductOut
    target_price: Optional[float]
    notify_on_drop: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
