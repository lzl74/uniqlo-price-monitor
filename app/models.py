from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    open_id = Column(String(64), unique=True, nullable=False, index=True)
    nickname = Column(String(64), default="")
    notify_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    watch_items = relationship("WatchList", back_populates="user")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    internal_code = Column(String(32), unique=True, nullable=False, index=True)
    product_code = Column(String(16), nullable=False, index=True)
    name = Column(String(128), default="")
    original_price = Column(Float, default=0)
    current_price = Column(Float, default=0)
    min_size = Column(String(8), default="")
    max_size = Column(String(8), default="")
    sku_count = Column(Integer, default=0)
    evaluation_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    image_url = Column(String(512), default="")
    url = Column(String(512), default="")
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    price_records = relationship("PriceHistory", back_populates="product")
    watch_items = relationship("WatchList", back_populates="product")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price = Column(Float, nullable=False)
    price_type = Column(String(16), default="normal")  # normal / limited / selected
    recorded_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="price_records")

    __table_args__ = (
        Index("ix_price_history_product_time", "product_id", "recorded_at"),
    )


class WatchList(Base):
    __tablename__ = "watch_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    target_price = Column(Float, nullable=True)
    notify_on_drop = Column(Boolean, default=True)
    notify_on_restock = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="watch_items")
    product = relationship("Product", back_populates="watch_items")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_user_product"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    type = Column(String(16), nullable=False)  # price_drop / back_in_stock / target_reached
    old_price = Column(Float, nullable=True)
    new_price = Column(Float, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    is_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_notification_user_time", "user_id", "created_at"),
    )


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(32), nullable=False)  # add_product / add_watch / remove_watch / refresh_price / price_drop / delete
    detail = Column(String(256), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
