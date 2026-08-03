from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    institute_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)
    action_label: Mapped[str | None] = mapped_column(String(80))
    action_url: Mapped[str | None] = mapped_column(String(500))
    audience_type: Mapped[str] = mapped_column(String(30), nullable=False, default="all_students")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    targets: Mapped[list["NotificationTarget"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan", lazy="selectin"
    )


class NotificationTarget(Base):
    __tablename__ = "notification_targets"
    __table_args__ = (UniqueConstraint("notification_id", "target_type", "target_id", name="uq_notification_target"),)

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notification: Mapped[Notification] = relationship(back_populates="targets")


class NotificationReceipt(Base):
    __tablename__ = "notification_receipts"
    __table_args__ = (UniqueConstraint("notification_id", "student_id", name="uq_notification_receipt"),)

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    institute_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
