"""주간 요약 및 마감 리마인더 생성 모듈.

매주 월요일 주간 마감 예정 공고 요약 메시지와
마감 전일 리마인더 메시지를 생성한다.

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.db.repository import AnnouncementRepository
from src.notifier.formatter import escape_markdown_v2

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.db.models import Announcement

logger = logging.getLogger(__name__)


def get_week_range(reference_date: date) -> tuple[date, date]:
    """기준 날짜가 속한 주의 월요일과 일요일을 반환한다.

    Args:
        reference_date: 기준 날짜.

    Returns:
        (monday, sunday) 튜플.
    """
    # weekday(): 월=0, 화=1, ..., 일=6
    monday = reference_date - timedelta(days=reference_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


class WeeklySummaryGenerator:
    """주간 요약 및 마감 리마인더 생성 클래스.

    Args:
        session: SQLAlchemy DB 세션.
        calendar_share_url: 노션 캘린더 공유 URL.
    """

    def __init__(self, session: Session, calendar_share_url: str) -> None:
        self.session = session
        self.calendar_share_url = calendar_share_url
        self.repository = AnnouncementRepository(session)

    def get_weekly_announcements(self, reference_date: date | None = None) -> list[Announcement]:
        """이번 주(월~일) 마감 예정인 공고 목록을 조회한다.

        Args:
            reference_date: 기준 날짜. None이면 오늘 기준.

        Returns:
            마감 예정 공고 목록 (마감일 오름차순).

        Validates: Requirements 5.1
        """
        if reference_date is None:
            reference_date = date.today()

        monday, sunday = get_week_range(reference_date)
        announcements = self.repository.get_ending_between(monday, sunday)

        logger.info(
            "주간 마감 예정 공고 조회: %s ~ %s, %d건",
            monday.isoformat(),
            sunday.isoformat(),
            len(announcements),
        )
        return announcements

    def format_weekly_summary(self, announcements: list[Announcement]) -> str:
        """주간 요약 메시지를 MarkdownV2 형식으로 포맷팅한다.

        Args:
            announcements: 주간 마감 예정 공고 목록.

        Returns:
            포맷팅된 MarkdownV2 메시지 문자열.

        Validates: Requirements 5.2, 5.3
        """
        escaped_url = self.calendar_share_url
        header = "📅 *이번 주 마감 예정 청약*"

        if not announcements:
            # 공고가 없는 경우
            no_announcement_msg = escape_markdown_v2("이번 주 마감 예정 청약이 없습니다.")
            calendar_link = f"📋 [전체 일정 확인하기]({escaped_url})"
            return f"{header}\n\n{no_announcement_msg}\n\n{calendar_link}"

        # 공고 목록 포맷팅
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        items: list[str] = []

        for i, announcement in enumerate(announcements):
            emoji = number_emojis[i] if i < len(number_emojis) else f"{i + 1}\\."
            title = escape_markdown_v2(announcement.title)
            end_date_str = (
                escape_markdown_v2(announcement.end_date.strftime("%Y.%m.%d"))
                if announcement.end_date
                else escape_markdown_v2("미정")
            )
            housing_type = escape_markdown_v2(announcement.housing_type or "미정")

            item = (
                f"{emoji} *{title}*\n"
                f"   마감일: {end_date_str} \\| 유형: {housing_type}"
            )
            items.append(item)

        items_text = "\n\n".join(items)
        calendar_link = f"📋 [전체 일정 확인하기]({escaped_url})"

        return f"{header}\n\n{items_text}\n\n{calendar_link}"

    def get_reminder_announcements(self, reference_date: date | None = None) -> list[Announcement]:
        """내일 마감 예정인 공고 목록을 조회한다.

        Args:
            reference_date: 기준 날짜(오늘). None이면 오늘 기준.

        Returns:
            내일 마감 예정 공고 목록.

        Validates: Requirements 5.4
        """
        if reference_date is None:
            reference_date = date.today()

        tomorrow = reference_date + timedelta(days=1)
        announcements = self.repository.get_ending_on(tomorrow)

        logger.info(
            "마감 리마인더 대상 조회: %s 마감, %d건",
            tomorrow.isoformat(),
            len(announcements),
        )
        return announcements

    def format_reminder(self, announcement: Announcement) -> str:
        """단일 공고에 대한 마감 리마인더 메시지를 생성한다.

        Args:
            announcement: 리마인더 대상 공고.

        Returns:
            포맷팅된 MarkdownV2 리마인더 메시지.

        Validates: Requirements 5.4
        """
        title = escape_markdown_v2(announcement.title)
        end_date_str = (
            escape_markdown_v2(announcement.end_date.strftime("%Y.%m.%d"))
            if announcement.end_date
            else escape_markdown_v2("미정")
        )
        housing_type = escape_markdown_v2(announcement.housing_type or "미정")

        lines = [
            "⏰ *내일 마감 리마인더*",
            "",
            f"*{title}*",
            f"마감일: {end_date_str} \\| 유형: {housing_type}",
        ]

        if announcement.original_url:
            lines.append("")
            lines.append(f"🔗 [원문 보기]({announcement.original_url})")

        return "\n".join(lines)

    def format_reminder_batch(self, announcements: list[Announcement]) -> str:
        """여러 공고에 대한 마감 리마인더 메시지를 하나로 합쳐 생성한다.

        Args:
            announcements: 리마인더 대상 공고 목록.

        Returns:
            포맷팅된 MarkdownV2 일괄 리마인더 메시지.
            공고가 없으면 빈 문자열을 반환한다.

        Validates: Requirements 5.4
        """
        if not announcements:
            return ""

        if len(announcements) == 1:
            return self.format_reminder(announcements[0])

        # 여러 건일 때 합쳐서 하나의 메시지로
        header = "⏰ *내일 마감 리마인더*"
        items: list[str] = []

        for announcement in announcements:
            title = escape_markdown_v2(announcement.title)
            end_date_str = (
                escape_markdown_v2(announcement.end_date.strftime("%Y.%m.%d"))
                if announcement.end_date
                else escape_markdown_v2("미정")
            )
            housing_type = escape_markdown_v2(announcement.housing_type or "미정")

            item_lines = [
                f"*{title}*",
                f"마감일: {end_date_str} \\| 유형: {housing_type}",
            ]

            if announcement.original_url:
                item_lines.append(f"🔗 [원문 보기]({announcement.original_url})")

            items.append("\n".join(item_lines))

        items_text = "\n\n".join(items)
        return f"{header}\n\n{items_text}"
