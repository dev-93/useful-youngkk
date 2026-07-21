"""데이터 접근 레이어.

announcements, crawl_logs, post_history에 대한 CRUD 및 비즈니스 쿼리를 제공한다.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Announcement, CrawlLog, PostHistory

logger = logging.getLogger(__name__)


class AnnouncementRepository:
    """청약 공고 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, announcement: Announcement) -> Announcement:
        """새 공고를 저장한다."""
        self.session.add(announcement)
        self.session.flush()
        return announcement

    def get_by_id(self, announcement_id: int) -> Announcement | None:
        """ID로 공고를 조회한다."""
        return self.session.get(Announcement, announcement_id)

    def exists(self, source_site: str, source_id: str) -> bool:
        """(source_site, source_id) 조합으로 중복 여부를 확인한다."""
        stmt = select(Announcement).where(
            Announcement.source_site == source_site,
            Announcement.source_id == source_id,
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        return result is not None

    def get_by_source(self, source_site: str, source_id: str) -> Announcement | None:
        """(source_site, source_id) 조합으로 공고를 조회한다."""
        stmt = select(Announcement).where(
            Announcement.source_site == source_site,
            Announcement.source_id == source_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_active(self) -> list[Announcement]:
        """활성 상태(active)인 공고 목록을 조회한다."""
        stmt = (
            select(Announcement)
            .where(Announcement.status == "active")
            .order_by(Announcement.end_date.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_ending_between(self, start: date, end: date) -> list[Announcement]:
        """지정 기간 내 마감 예정인 활성 공고를 조회한다."""
        stmt = (
            select(Announcement)
            .where(
                Announcement.status == "active",
                Announcement.end_date >= start,
                Announcement.end_date <= end,
            )
            .order_by(Announcement.end_date.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_ending_on(self, target_date: date) -> list[Announcement]:
        """특정 날짜에 마감 예정인 활성 공고를 조회한다."""
        stmt = (
            select(Announcement)
            .where(
                Announcement.status == "active",
                Announcement.end_date == target_date,
            )
            .order_by(Announcement.title.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def update_status(self, announcement_id: int, status: str) -> Announcement | None:
        """공고 상태를 업데이트한다."""
        announcement = self.get_by_id(announcement_id)
        if announcement:
            announcement.status = status
            self.session.flush()
        return announcement

    def update_notion_page_id(
        self, announcement_id: int, notion_page_id: str
    ) -> Announcement | None:
        """공고의 노션 페이지 ID를 업데이트한다."""
        announcement = self.get_by_id(announcement_id)
        if announcement:
            announcement.notion_page_id = notion_page_id
            self.session.flush()
        return announcement

    def archive_expired(self, days: int = 90) -> int:
        """마감일로부터 지정 일수가 경과한 공고를 아카이브 처리한다.

        Args:
            days: 마감일 기준 경과 일수. 기본값 90일.

        Returns:
            아카이브 처리된 공고 수.
        """
        cutoff_date = date.today() - timedelta(days=days)
        stmt = select(Announcement).where(
            Announcement.status == "active",
            Announcement.end_date.isnot(None),
            Announcement.end_date <= cutoff_date,
        )
        announcements = list(self.session.execute(stmt).scalars().all())
        count = 0
        for announcement in announcements:
            announcement.status = "archived"
            count += 1
        self.session.flush()
        logger.info("%d개 공고를 아카이브 처리했습니다 (기준: %s)", count, cutoff_date)
        return count


class CrawlLogRepository:
    """크롤링 로그 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, crawl_log: CrawlLog) -> CrawlLog:
        """크롤링 로그를 기록한다."""
        self.session.add(crawl_log)
        self.session.flush()
        return crawl_log

    def get_by_id(self, log_id: int) -> CrawlLog | None:
        """ID로 크롤링 로그를 조회한다."""
        return self.session.get(CrawlLog, log_id)

    def update_finished(
        self,
        log_id: int,
        status: str,
        new_count: int,
        error_message: str | None = None,
    ) -> CrawlLog | None:
        """크롤링 완료 정보를 업데이트한다."""
        crawl_log = self.get_by_id(log_id)
        if crawl_log:
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = status
            crawl_log.new_count = new_count
            crawl_log.error_message = error_message
            self.session.flush()
        return crawl_log

    def get_latest_by_site(self, source_site: str) -> CrawlLog | None:
        """사이트별 가장 최근 크롤링 로그를 조회한다."""
        stmt = (
            select(CrawlLog)
            .where(CrawlLog.source_site == source_site)
            .order_by(CrawlLog.started_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()


class PostHistoryRepository:
    """포스팅 이력 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, post_history: PostHistory) -> PostHistory:
        """포스팅 이력을 기록한다."""
        self.session.add(post_history)
        self.session.flush()
        return post_history

    def get_by_id(self, history_id: int) -> PostHistory | None:
        """ID로 포스팅 이력을 조회한다."""
        return self.session.get(PostHistory, history_id)

    def get_by_announcement(self, announcement_id: int) -> list[PostHistory]:
        """공고별 포스팅 이력을 조회한다."""
        stmt = (
            select(PostHistory)
            .where(PostHistory.announcement_id == announcement_id)
            .order_by(PostHistory.posted_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def has_been_posted(self, announcement_id: int, post_type: str) -> bool:
        """특정 공고가 특정 유형으로 이미 포스팅되었는지 확인한다."""
        stmt = select(PostHistory).where(
            PostHistory.announcement_id == announcement_id,
            PostHistory.post_type == post_type,
            PostHistory.status == "success",
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        return result is not None
