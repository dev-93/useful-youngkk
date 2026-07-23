"""크롤러 베이스 클래스.

모든 사이트별 크롤러가 상속하는 추상 클래스와 재시도 유틸리티를 정의한다.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from src.db.models import Announcement, CrawlLog
from src.db.repository import AnnouncementRepository, CrawlLogRepository

logger = logging.getLogger(__name__)


# 재시도 설정 상수
RETRY_INTERVAL_SECONDS = 30  # 30초 (GitHub Actions 환경 고려)
MAX_RETRIES = 2  # 최대 2회 재시도


def _is_client_error(exc: Exception) -> bool:
    """4xx HTTP 클라이언트 에러인지 판별한다."""
    error_str = str(exc)
    # httpx의 HTTPStatusError에서 4xx 확인
    if hasattr(exc, "response"):
        status = getattr(exc.response, "status_code", 0)
        if 400 <= status < 500:
            return True
    # 문자열에서 4xx 패턴 확인
    if "404" in error_str or "403" in error_str or "401" in error_str:
        return True
    return False


@dataclass
class AnnouncementData:
    """크롤링된 공고 데이터 구조체.

    파싱 결과를 담아 save 단계로 전달한다.
    """

    source_site: str
    source_id: str
    title: str
    announcement_category: str | None = None  # "공공임대" | "민간분양"
    housing_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    result_date: date | None = None
    target_region: str | None = None
    eligibility_age: str | None = None
    eligibility_income: str | None = None
    eligibility_homeless: str | None = None
    eligibility_residence: str | None = None
    original_url: str | None = None


@dataclass
class ListItem:
    """목록 페이지에서 파싱된 개별 항목."""

    source_id: str
    title: str
    detail_url: str
    extra: dict = field(default_factory=dict)


class BaseCrawler(ABC):
    """크롤러 추상 베이스 클래스.

    하위 클래스는 fetch_list, parse_list, fetch_detail, parse_detail을 구현해야 한다.
    run() 메서드가 전체 크롤링 플로우를 오케스트레이션한다.
    """

    source_site: str = ""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.announcement_repo = AnnouncementRepository(session)
        self.crawl_log_repo = CrawlLogRepository(session)

    @abstractmethod
    def fetch_list(self) -> str:
        """목록 페이지 HTML을 가져온다.

        Returns:
            목록 페이지 HTML 문자열.
        """
        ...

    @abstractmethod
    def parse_list(self, html: str) -> list[ListItem]:
        """목록 페이지 HTML에서 공고 항목 목록을 파싱한다.

        Args:
            html: 목록 페이지 HTML 문자열.

        Returns:
            파싱된 ListItem 목록.
        """
        ...

    @abstractmethod
    def fetch_detail(self, item: ListItem) -> str:
        """상세 페이지 HTML을 가져온다.

        Args:
            item: 목록에서 파싱된 항목.

        Returns:
            상세 페이지 HTML 문자열.
        """
        ...

    @abstractmethod
    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        """상세 페이지 HTML에서 공고 상세 정보를 파싱한다.

        Args:
            html: 상세 페이지 HTML 문자열.
            item: 목록에서 파싱된 항목.

        Returns:
            구조화된 공고 데이터.
        """
        ...

    def save(self, data: AnnouncementData) -> Announcement | None:
        """파싱된 공고 데이터를 DB에 저장한다.

        중복 체크, 불완전 공고 상태 처리를 수행한다.

        Args:
            data: 구조화된 공고 데이터.

        Returns:
            저장된 Announcement 객체 또는 중복 시 None.
        """
        # 중복 체크
        if self.announcement_repo.exists(data.source_site, data.source_id):
            logger.debug(
                "중복 공고 건너뜀: %s:%s", data.source_site, data.source_id
            )
            return None

        # 불완전 공고 판별 (공고명 또는 모집 기간 누락)
        status = "active"
        missing_fields: list[str] = []

        if not data.title:
            missing_fields.append("title")
        if data.start_date is None and data.end_date is None:
            missing_fields.append("모집 기간(start_date, end_date)")
        elif data.start_date is None:
            missing_fields.append("start_date")
        elif data.end_date is None:
            missing_fields.append("end_date")

        if missing_fields:
            status = "incomplete"
            logger.warning(
                "불완전 공고 감지 [%s:%s]: 누락 필드 - %s",
                data.source_site,
                data.source_id,
                ", ".join(missing_fields),
            )

        announcement = Announcement(
            source_site=data.source_site,
            source_id=data.source_id,
            title=data.title or "(제목 없음)",
            announcement_category=data.announcement_category,
            housing_type=data.housing_type,
            start_date=data.start_date,
            end_date=data.end_date,
            result_date=data.result_date,
            target_region=data.target_region,
            eligibility_age=data.eligibility_age,
            eligibility_income=data.eligibility_income,
            eligibility_homeless=data.eligibility_homeless,
            eligibility_residence=data.eligibility_residence,
            original_url=data.original_url,
            status=status,
        )

        self.announcement_repo.create(announcement)
        logger.info(
            "새 공고 저장: %s:%s [%s] - %s",
            data.source_site,
            data.source_id,
            status,
            data.title,
        )
        return announcement

    def run(self) -> int:
        """전체 크롤링 플로우를 실행한다.

        fetch_list → parse_list → 각 항목에 대해 중복 체크 →
        fetch_detail → parse_detail → save

        Returns:
            신규 저장된 공고 수.
        """
        new_count = 0

        logger.info("[%s] 목록 페이지 가져오기 시작", self.source_site)
        list_html = self.fetch_list()

        logger.info("[%s] 목록 페이지 파싱 시작", self.source_site)
        items = self.parse_list(list_html)
        logger.info("[%s] %d개 항목 발견", self.source_site, len(items))

        for item in items:
            # 중복 체크 (상세 크롤링 전에 판별하여 불필요한 요청 방지)
            if self.announcement_repo.exists(self.source_site, item.source_id):
                logger.debug(
                    "[%s] 중복 건너뜀: %s", self.source_site, item.source_id
                )
                continue

            try:
                logger.debug(
                    "[%s] 상세 페이지 가져오기: %s",
                    self.source_site,
                    item.detail_url,
                )
                detail_html = self.fetch_detail(item)
                data = self.parse_detail(detail_html, item)
                result = self.save(data)
                if result is not None:
                    new_count += 1
            except Exception as e:
                logger.error(
                    "[%s] 상세 크롤링 실패 (%s): %s",
                    self.source_site,
                    item.source_id,
                    str(e),
                )
                continue

        logger.info("[%s] 크롤링 완료: 신규 %d건", self.source_site, new_count)
        return new_count


def run_with_retry(
    crawler: BaseCrawler,
    retry_interval: int = RETRY_INTERVAL_SECONDS,
    max_retries: int = MAX_RETRIES,
) -> CrawlLog:
    """재시도 로직을 포함하여 크롤러를 실행한다.

    실패 시 retry_interval 간격으로 최대 max_retries회 재시도한다.
    모든 결과를 crawl_logs 테이블에 기록한다.

    Args:
        crawler: 실행할 크롤러 인스턴스.
        retry_interval: 재시도 간격(초). 기본 30분(1800초).
        max_retries: 최대 재시도 횟수. 기본 3회.

    Returns:
        CrawlLog 기록.
    """
    crawl_log = CrawlLog(
        source_site=crawler.source_site,
        started_at=datetime.utcnow(),
        status="running",
        new_count=0,
        retry_count=0,
    )
    crawler.crawl_log_repo.create(crawl_log)
    crawler.session.commit()

    attempt = 0
    last_error: str | None = None

    while attempt <= max_retries:
        try:
            new_count = crawler.run()
            # 성공
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = "success"
            crawl_log.new_count = new_count
            crawl_log.retry_count = attempt
            crawl_log.error_message = None
            crawler.session.commit()
            logger.info(
                "[%s] 크롤링 성공 (시도 %d/%d): 신규 %d건",
                crawler.source_site,
                attempt + 1,
                max_retries + 1,
                new_count,
            )
            return crawl_log

        except Exception as e:
            last_error = str(e)
            logger.error(
                "[%s] 크롤링 실패 (시도 %d/%d): %s",
                crawler.source_site,
                attempt + 1,
                max_retries + 1,
                last_error,
            )

            # 4xx 에러(클라이언트 오류)는 재시도 무의미 → 즉시 중단
            if _is_client_error(e):
                logger.warning(
                    "[%s] 클라이언트 에러(4xx) — 재시도 건너뜀",
                    crawler.source_site,
                )
                break

            attempt += 1

            if attempt <= max_retries:
                logger.info(
                    "[%s] %d초 후 재시도 예정...",
                    crawler.source_site,
                    retry_interval,
                )
                time.sleep(retry_interval)

    # 모든 재시도 실패
    crawl_log.finished_at = datetime.utcnow()
    crawl_log.status = "failed"
    crawl_log.retry_count = max_retries
    crawl_log.error_message = last_error
    crawler.session.commit()

    logger.error(
        "[%s] 크롤링 최종 실패 (%d회 시도): %s",
        crawler.source_site,
        max_retries + 1,
        last_error,
    )
    return crawl_log
