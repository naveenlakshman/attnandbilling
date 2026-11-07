from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")

class LMSBatchTopicProgress(Base):
    __tablename__ = "lms_batch_topic_progress"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    program_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    master_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    taught_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    taught_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
