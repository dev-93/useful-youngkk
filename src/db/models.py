"""SQLAlchemy 데이터 모델.

announcements, crawl_logs, post_history 테이블을 정의한다.
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 선언적 베이스 클래스."""

    pass


class Announcement(Base):
    """청약 공고 테이블."""

    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("source_site", "source_id", name="uq_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_site: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    announcement_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    housing_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_region: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_age: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_income: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_homeless: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_residence: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    notion_page_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    post_history: Mapped[list["PostHistory"]] = relationship(
        back_populates="announcement"
    )

    def __repr__(self) -> str:
        return f"<Announcement(id={self.id}, source={self.source_site}:{self.source_id}, title='{self.title}')>"


class CrawlLog(Base):
    """크롤링 로그 테이블."""

    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_site: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<CrawlLog(id={self.id}, site={self.source_site}, status={self.status})>"


class PostHistory(Base):
    """포스팅 이력 테이블."""

    __tablename__ = "post_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    announcement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("announcements.id"), nullable=False
    )
    post_type: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    announcement: Mapped["Announcement"] = relationship(back_populates="post_history")

    def __repr__(self) -> str:
        return f"<PostHistory(id={self.id}, type={self.post_type}, status={self.status})>"
