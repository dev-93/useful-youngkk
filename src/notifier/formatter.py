"""메시지 포맷팅 모듈.

텔레그램 Markdown v2 형식으로 청약 공고 메시지를 포맷팅한다.
자격요건 섹션 포맷팅, 특수문자 이스케이프 처리를 담당한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Announcement

# Markdown v2에서 이스케이프해야 하는 특수 문자
_MARKDOWN_V2_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"

# 자격요건 항목이 누락되었을 때 표시할 기본 텍스트
_MISSING_FIELD_TEXT = "정보 없음"

# 누락 안내 문구
_MISSING_NOTICE = "상세 요건은 공고 원문을 확인해 주세요"


def escape_markdown_v2(text: str) -> str:
    """Telegram MarkdownV2 특수 문자를 이스케이프한다.

    Args:
        text: 이스케이프할 원본 텍스트.

    Returns:
        이스케이프 처리된 텍스트.
    """
    result = []
    for char in text:
        if char in _MARKDOWN_V2_SPECIAL_CHARS:
            result.append(f"\\{char}")
        else:
            result.append(char)
    return "".join(result)


def format_eligibility_section(announcement: Announcement) -> str:
    """자격요건 섹션을 MarkdownV2 형식으로 포맷팅한다.

    나이, 소득, 무주택, 거주기간 요건을 항목별로 정리한다.
    누락된 항목이 있으면 안내 문구를 포함한다.

    Args:
        announcement: 공고 데이터 객체.

    Returns:
        포맷팅된 자격요건 섹션 문자열 (MarkdownV2).

    Validates: Requirements 3.1, 3.2, 3.3
    """
    age = announcement.eligibility_age
    income = announcement.eligibility_income
    homeless = announcement.eligibility_homeless
    residence = announcement.eligibility_residence

    has_missing = False

    # 각 항목 처리
    age_text = escape_markdown_v2(age) if age else escape_markdown_v2(_MISSING_FIELD_TEXT)
    if not age:
        has_missing = True

    income_text = escape_markdown_v2(income) if income else escape_markdown_v2(_MISSING_FIELD_TEXT)
    if not income:
        has_missing = True

    homeless_text = escape_markdown_v2(homeless) if homeless else escape_markdown_v2(_MISSING_FIELD_TEXT)
    if not homeless:
        has_missing = True

    residence_text = escape_markdown_v2(residence) if residence else escape_markdown_v2(_MISSING_FIELD_TEXT)
    if not residence:
        has_missing = True

    lines = [
        "📋 *자격요건*",
        f"• 나이: {age_text}",
        f"• 소득: {income_text}",
        f"• 무주택: {homeless_text}",
        f"• 거주기간: {residence_text}",
    ]

    if has_missing:
        notice = escape_markdown_v2(_MISSING_NOTICE)
        lines.append("")
        lines.append(f"ℹ️ _{notice}_")

    return "\n".join(lines)


def format_new_announcement(announcement: Announcement) -> str:
    """새 공고 메시지를 MarkdownV2 형식으로 포맷팅한다.

    공고명, 모집유형, 신청기간, 자격요건, 원문 링크를 포함한다.

    Args:
        announcement: 공고 데이터 객체.

    Returns:
        포맷팅된 전체 메시지 문자열 (MarkdownV2).

    Validates: Requirements 2.2, 3.1, 3.2, 3.3
    """
    title = escape_markdown_v2(announcement.title)
    housing_type = escape_markdown_v2(announcement.housing_type or "미정")

    # 공고 카테고리 (공공임대 / 민간분양)
    category = escape_markdown_v2(announcement.announcement_category or "미분류")

    # 신청 기간 포맷팅
    start_date = announcement.start_date
    end_date = announcement.end_date
    if start_date and end_date:
        period = escape_markdown_v2(f"{start_date.strftime('%Y.%m.%d')} ~ {end_date.strftime('%Y.%m.%d')}")
    elif start_date:
        period = escape_markdown_v2(f"{start_date.strftime('%Y.%m.%d')} ~")
    elif end_date:
        period = escape_markdown_v2(f"~ {end_date.strftime('%Y.%m.%d')}")
    else:
        period = escape_markdown_v2("미정")

    # 자격요건 섹션
    eligibility_section = format_eligibility_section(announcement)

    # 원문 링크
    if announcement.original_url:
        url = announcement.original_url
        link_section = f"🔗 [원문 보기]({url})"
    else:
        link_section = ""

    lines = [
        "🏠 *새 청약 공고*",
        "",
        f"*\\[{category}\\]* {housing_type}",
        f"*공고명:* {title}",
        f"*신청기간:* {period}",
        "",
        eligibility_section,
        "",
        link_section,
    ]

    # 빈 줄 정리 (마지막 빈 줄 제거)
    message = "\n".join(lines).rstrip()
    return message
