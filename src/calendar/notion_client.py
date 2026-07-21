"""노션 API 연동 모듈.

노션 데이터베이스에 청약 공고 일정을 등록하고 상태를 관리한다.
"""

import functools
import logging
import time
from datetime import date
from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError

from src.db.models import Announcement

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1


def with_retry(func):
    """노션 API 호출 재시도 데코레이터.

    최대 3회까지 재시도하며, 실패 시 로그를 기록한다.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exception: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except APIResponseError as e:
                last_exception = e
                logger.warning(
                    "노션 API 호출 실패 (시도 %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    str(e),
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
            except Exception as e:
                last_exception = e
                logger.warning(
                    "노션 API 호출 중 예외 발생 (시도 %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    str(e),
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

        logger.error(
            "노션 API 호출 최대 재시도(%d회) 초과: %s", MAX_RETRIES, str(last_exception)
        )
        raise last_exception  # type: ignore[misc]

    return wrapper


def determine_status(start_date: date | None, end_date: date | None) -> str:
    """공고의 시작일과 마감일을 기준으로 상태를 결정한다.

    Args:
        start_date: 모집 시작일.
        end_date: 모집 마감일.

    Returns:
        상태 문자열: "예정", "진행중", "마감" 중 하나.
    """
    today = date.today()

    if end_date and today > end_date:
        return "마감"
    if start_date and today < start_date:
        return "예정"
    return "진행중"


class NotionCalendarManager:
    """노션 캘린더 관리 클래스.

    노션 DB에 공고 일정을 등록하고, 상태를 관리한다.
    """

    def __init__(
        self, api_key: str, database_id: str, calendar_share_url: str
    ) -> None:
        """NotionCalendarManager를 초기화한다.

        Args:
            api_key: 노션 Access Token.
            database_id: 노션 데이터베이스 ID.
            calendar_share_url: 노션 캘린더 공유 URL.
        """
        self.client = Client(auth=api_key)
        self.database_id = database_id
        self.calendar_share_url = calendar_share_url

    def get_share_url(self) -> str:
        """노션 캘린더 공유 URL을 반환한다."""
        return self.calendar_share_url

    @with_retry
    def create_page(self, announcement: Announcement) -> str:
        """공고 정보를 노션 DB에 페이지로 생성한다.

        Args:
            announcement: 공고 데이터 모델.

        Returns:
            생성된 노션 페이지 ID.
        """
        status = determine_status(announcement.start_date, announcement.end_date)
        properties = self._build_properties(announcement, status)

        response = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties,
        )

        page_id = response["id"]
        logger.info(
            "노션 페이지 생성 완료: %s (page_id=%s)", announcement.title, page_id
        )
        return page_id

    @with_retry
    def update_status(self, page_id: str, new_status: str) -> None:
        """노션 페이지의 상태를 업데이트한다.

        Args:
            page_id: 노션 페이지 ID.
            new_status: 새로운 상태 ("예정", "진행중", "마감").
        """
        self.client.pages.update(
            page_id=page_id,
            properties={
                "상태": {"select": {"name": new_status}},
            },
        )
        logger.info("노션 페이지 상태 변경: page_id=%s → %s", page_id, new_status)

    def close_expired(self, announcements: list[Announcement]) -> list[str]:
        """마감일이 경과한 공고의 상태를 "마감"으로 변경한다.

        Args:
            announcements: 마감 처리할 공고 목록.

        Returns:
            상태 변경된 노션 페이지 ID 목록.
        """
        today = date.today()
        updated_page_ids: list[str] = []

        for announcement in announcements:
            if not announcement.notion_page_id:
                continue
            if announcement.end_date and today > announcement.end_date:
                try:
                    self.update_status(announcement.notion_page_id, "마감")
                    updated_page_ids.append(announcement.notion_page_id)
                except Exception as e:
                    logger.error(
                        "마감 상태 변경 실패: announcement_id=%d, error=%s",
                        announcement.id,
                        str(e),
                    )

        if updated_page_ids:
            logger.info("%d개 공고를 '마감' 상태로 변경했습니다.", len(updated_page_ids))

        return updated_page_ids

    def _build_properties(
        self, announcement: Announcement, status: str
    ) -> dict[str, Any]:
        """노션 페이지 속성을 구성한다.

        Args:
            announcement: 공고 데이터 모델.
            status: 공고 상태.

        Returns:
            노션 API 속성 딕셔너리.
        """
        properties: dict[str, Any] = {
            "공고명": {"title": [{"text": {"content": announcement.title}}]},
            "상태": {"select": {"name": status}},
        }

        if announcement.announcement_category:
            properties["공고 구분"] = {"select": {"name": announcement.announcement_category}}

        if announcement.housing_type:
            properties["모집 유형"] = {"select": {"name": announcement.housing_type}}

        if announcement.start_date:
            properties["시작일"] = {
                "date": {"start": announcement.start_date.isoformat()}
            }

        if announcement.end_date:
            properties["마감일"] = {
                "date": {"start": announcement.end_date.isoformat()}
            }

        if announcement.result_date:
            properties["발표일"] = {
                "date": {"start": announcement.result_date.isoformat()}
            }

        if announcement.original_url:
            properties["원문 링크"] = {"url": announcement.original_url}

        # 출처 사이트 매핑
        source_map = {
            "sh": "SH공사",
            "lh": "LH공사",
            "myhome": "마이홈",
            "applyhome": "청약홈",
        }
        source_name = source_map.get(announcement.source_site)
        if source_name:
            properties["출처"] = {"select": {"name": source_name}}

        # 자격요건 요약
        eligibility_parts = []
        if announcement.eligibility_age:
            eligibility_parts.append(f"나이: {announcement.eligibility_age}")
        if announcement.eligibility_income:
            eligibility_parts.append(f"소득: {announcement.eligibility_income}")
        if announcement.eligibility_homeless:
            eligibility_parts.append(f"무주택: {announcement.eligibility_homeless}")
        if eligibility_parts:
            properties["자격요건 요약"] = {
                "rich_text": [{"text": {"content": " / ".join(eligibility_parts)[:2000]}}]
            }

        # 대상 지역
        if announcement.target_region:
            properties["대상 지역"] = {
                "rich_text": [{"text": {"content": announcement.target_region}}]
            }

        return properties
