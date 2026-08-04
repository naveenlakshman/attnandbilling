from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class FeeReminderSettings(Base):
    __tablename__ = "fee_reminder_settings"

    institute_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    days_before_due: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    repeat_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    extension_min_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    extension_max_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    allow_extension_requests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title_template: Mapped[str] = mapped_column(String(160), nullable=False, default="Fee payment reminder")
    message_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="Your installment of {amount} for {invoice_no} is due on {due_date}.",
    )
    icon: Mapped[str] = mapped_column(String(60), nullable=False, default="bi-wallet2")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FeeReminderImpression(Base):
    __tablename__ = "fee_reminder_impressions"
    __table_args__ = (
        UniqueConstraint("institute_id", "student_id", "installment_id", name="uq_fee_reminder_impression"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    institute_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    installment_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    first_shown_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_shown_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class FeeExtensionRequest(Base):
    __tablename__ = "fee_extension_requests"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    institute_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    installment_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    original_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    extension_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
