"""GitHub Actions에서 실행하는 수집 파이프라인 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    DatabaseConfig,
    LoggingConfig,
    NotionConfig,
    Settings,
    TelegramConfig,
)
from src.scheduler.jobs import crawl_and_post


@pytest.fixture
def mock_settings() -> Settings:
    """테스트용 Settings 객체를 생성한다."""
    return Settings(
        telegram=TelegramConfig(
            bot_token="test-token",
            channel_id="@test_channel",
            admin_chat_id="12345",
        ),
        notion=NotionConfig(
            access_token="notion-key",
            database_id="notion-db-id",
            data_source_id="notion-ds-id",
            calendar_share_url="https://notion.so/calendar",
        ),
        database=DatabaseConfig(url="sqlite:///test.db"),
        logging=LoggingConfig(level="INFO", log_dir="./logs"),
    )


class TestCrawlAndPost:
    """crawl_and_post 작업 테스트."""

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.run_with_retry")
    @patch("src.scheduler.jobs.create_notifier")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    async def test_crawl_and_post_no_new_announcements(
        self,
        mock_calendar_cls: MagicMock,
        mock_create_notifier: MagicMock,
        mock_run_with_retry: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """새 공고가 없어도 상태 업데이트와 리마인더를 실행한다."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_notifier.send_channel_message = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        mock_calendar = MagicMock()
        mock_calendar.query_expired_active.return_value = [{"page_id": "expired-1"}]
        mock_calendar.query_tomorrow_deadlines.return_value = [
            {
                "page_id": "deadline-1",
                "title": "내일 마감 공고",
                "end_date": "2026-10-01",
                "url": "https://example.com/deadline",
            }
        ]
        mock_calendar_cls.return_value = mock_calendar

        # 크롤링 결과: 성공했지만 0건
        mock_crawl_log = MagicMock()
        mock_crawl_log.status = "success"
        mock_crawl_log.new_count = 0
        mock_run_with_retry.return_value = mock_crawl_log

        await crawl_and_post(mock_settings)

        # CalendarManager가 중복 체크를 위해 호출됨
        mock_calendar_cls.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_calendar.query_expired_active.assert_called_once_with()
        mock_calendar.update_status.assert_called_once_with("expired-1", "마감")
        mock_calendar.query_tomorrow_deadlines.assert_called_once_with()
        mock_notifier.send_channel_message.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.run_with_retry")
    @patch("src.scheduler.jobs.AnnouncementRepository")
    @patch("src.scheduler.jobs.create_notifier")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    async def test_crawl_and_post_with_new_announcements(
        self,
        mock_calendar_cls: MagicMock,
        mock_create_notifier: MagicMock,
        mock_repo_cls: MagicMock,
        mock_run_with_retry: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """새 공고가 있을 때 포스팅과 노션 등록이 실행되는지 확인한다."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # 크롤링 성공 (1건 새 공고)
        mock_crawl_log = MagicMock()
        mock_crawl_log.status = "success"
        mock_crawl_log.new_count = 1
        mock_run_with_retry.return_value = mock_crawl_log

        # 새 공고 (notion_page_id가 None)
        mock_announcement = MagicMock()
        mock_announcement.id = 1
        mock_announcement.notion_page_id = None

        mock_repo = MagicMock()
        mock_repo.get_active.return_value = [mock_announcement]
        mock_repo_cls.return_value = mock_repo

        # 노션 페이지 생성 결과
        mock_calendar = MagicMock()
        mock_calendar.create_page.return_value = "page-123"
        mock_calendar_cls.return_value = mock_calendar

        # 텔레그램 포스팅 (create_notifier가 반환하는 notifier)
        mock_notifier = MagicMock()
        mock_notifier.send_new_announcement = AsyncMock(return_value=True)
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        await crawl_and_post(mock_settings)

        # 포스팅 호출 확인
        mock_notifier.send_new_announcement.assert_called_once_with(
            mock_announcement, mock_session
        )
        # 노션 등록 확인
        mock_calendar.create_page.assert_called_once_with(mock_announcement)
        mock_repo.update_notion_page_id.assert_called_once_with(1, "page-123")
        mock_session.commit.assert_called()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.run_with_retry")
    @patch("src.scheduler.jobs.create_notifier")
    async def test_crawl_and_post_handles_crawl_failure(
        self,
        mock_create_notifier: MagicMock,
        mock_run_with_retry: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """크롤링 실패 시에도 예외를 전파하지 않고 다음 크롤러로 진행하는지 확인한다."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        # 모든 크롤러가 실패
        mock_run_with_retry.side_effect = Exception("network error")

        # 예외가 발생하지 않아야 함
        await crawl_and_post(mock_settings)
        mock_session.commit.assert_called()
        mock_session.close.assert_called_once()
