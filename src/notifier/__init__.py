"""노티파이어 모듈.

텔레그램 채널 포스팅, 메시지 포맷팅, 주간 요약 생성, 관리자 알림 기능을 제공한다.
"""

from src.notifier.admin import (
    create_notifier,
    notify_admin_error,
    notify_crawl_failure,
    notify_db_save_failure,
    notify_job_failure,
    notify_notion_failure,
    retry_db_operation,
)
from src.notifier.formatter import (
    escape_markdown_v2,
    format_eligibility_section,
    format_new_announcement,
)
from src.notifier.telegram import TelegramNotifier
from src.notifier.weekly_summary import WeeklySummaryGenerator, get_week_range

__all__ = [
    "TelegramNotifier",
    "WeeklySummaryGenerator",
    "create_notifier",
    "escape_markdown_v2",
    "format_eligibility_section",
    "format_new_announcement",
    "get_week_range",
    "notify_admin_error",
    "notify_crawl_failure",
    "notify_db_save_failure",
    "notify_job_failure",
    "notify_notion_failure",
    "retry_db_operation",
]
