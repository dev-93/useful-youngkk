"""스케줄러 모듈 테스트.

jobs.py의 크롤링·포스팅·주간 요약·리마인더 작업과
main.py의 스케줄러 설정을 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    DatabaseConfig,
    LoggingConfig,
    NotionConfig,
    SchedulerConfig,
    Settings,
    TelegramConfig,
)
from src.main import create_scheduler
from src.scheduler.jobs import crawl_and_post, reminder_job, weekly_summary_job


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
        scheduler=SchedulerConfig(
            crawl_hours=[11, 17],
            weekly_summary_day="mon",
            weekly_summary_hour=9,
        ),
        logging=LoggingConfig(level="INFO", log_dir="./logs"),
    )


class TestCreateScheduler:
    """create_scheduler 함수 테스트."""

    def test_scheduler_creates_correct_number_of_jobs(
        self, mock_settings: Settings
    ) -> None:
        """스케줄러에 올바른 수의 작업이 등록되는지 확인한다."""
        scheduler = create_scheduler(mock_settings)
        jobs = scheduler.get_jobs()

        # 크롤링 2개(11시, 17시) + 주간 요약 1개 + 리마인더 1개 = 4개
        assert len(jobs) == 4

    def test_scheduler_crawl_jobs_are_weekday_only(
        self, mock_settings: Settings
    ) -> None:
        """크롤링 작업이 평일(mon-fri)에만 실행되도록 설정되는지 확인한다."""
        scheduler = create_scheduler(mock_settings)
        jobs = scheduler.get_jobs()

        crawl_jobs = [j for j in jobs if j.id.startswith("crawl_and_post")]
        assert len(crawl_jobs) == 2

        for job in crawl_jobs:
            trigger = job.trigger
            # CronTrigger의 fields에서 day_of_week 확인
            day_of_week_field = trigger.fields[4]  # day_of_week is index 4
            assert str(day_of_week_field) == "mon-fri"

    def test_scheduler_weekly_summary_on_monday(
        self, mock_settings: Settings
    ) -> None:
        """주간 요약이 월요일 9시에 실행되도록 설정되는지 확인한다."""
        scheduler = create_scheduler(mock_settings)
        jobs = scheduler.get_jobs()

        weekly_job = next(j for j in jobs if j.id == "weekly_summary")
        trigger = weekly_job.trigger

        day_of_week_field = trigger.fields[4]
        hour_field = trigger.fields[5]
        assert str(day_of_week_field) == "mon"
        assert str(hour_field) == "9"

    def test_scheduler_reminder_daily(self, mock_settings: Settings) -> None:
        """리마인더가 매일 9시에 실행되도록 설정되는지 확인한다."""
        scheduler = create_scheduler(mock_settings)
        jobs = scheduler.get_jobs()

        reminder = next(j for j in jobs if j.id == "reminder")
        trigger = reminder.trigger

        hour_field = trigger.fields[5]
        assert str(hour_field) == "9"

    def test_scheduler_custom_crawl_hours(self) -> None:
        """사용자 정의 크롤링 시간이 반영되는지 확인한다."""
        settings = Settings(
            telegram=TelegramConfig(
                bot_token="t", channel_id="c", admin_chat_id="a"
            ),
            notion=NotionConfig(
                access_token="k", database_id="d", data_source_id="ds", calendar_share_url="u"
            ),
            database=DatabaseConfig(url="sqlite:///test.db"),
            scheduler=SchedulerConfig(
                crawl_hours=[9, 13, 18],
                weekly_summary_day="mon",
                weekly_summary_hour=9,
            ),
            logging=LoggingConfig(level="INFO", log_dir="./logs"),
        )
        scheduler = create_scheduler(settings)
        jobs = scheduler.get_jobs()

        crawl_jobs = [j for j in jobs if j.id.startswith("crawl_and_post")]
        assert len(crawl_jobs) == 3

        crawl_ids = sorted([j.id for j in crawl_jobs])
        assert crawl_ids == [
            "crawl_and_post_09",
            "crawl_and_post_13",
            "crawl_and_post_18",
        ]


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
        """새 공고가 없을 때 포스팅을 건너뛰는지 확인한다."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        # 크롤링 결과: 성공했지만 0건
        mock_crawl_log = MagicMock()
        mock_crawl_log.status = "success"
        mock_crawl_log.new_count = 0
        mock_run_with_retry.return_value = mock_crawl_log

        await crawl_and_post(mock_settings)

        # CalendarManager가 중복 체크를 위해 호출됨
        mock_calendar_cls.assert_called_once()
        mock_session.commit.assert_called_once()
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


class TestWeeklySummaryJob:
    """weekly_summary_job 작업 테스트."""

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.create_notifier")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    async def test_weekly_summary_posts_message(
        self,
        mock_calendar_cls: MagicMock,
        mock_create_notifier: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """주간 요약이 정상적으로 포스팅되는지 확인한다."""
        mock_notifier = MagicMock()
        mock_notifier.send_channel_message = AsyncMock(return_value="msg-1")
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        mock_calendar = MagicMock()
        mock_calendar.query_weekly_deadlines.return_value = []
        mock_calendar_cls.return_value = mock_calendar

        await weekly_summary_job(mock_settings)

        mock_calendar.query_weekly_deadlines.assert_called_once()
        mock_notifier.send_channel_message.assert_called_once()


class TestReminderJob:
    """reminder_job 작업 테스트."""

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.create_notifier")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    async def test_reminder_job_posts_and_updates(
        self,
        mock_calendar_cls: MagicMock,
        mock_create_notifier: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """리마인더가 포스팅되고 노션 상태가 업데이트되는지 확인한다."""
        mock_notifier = MagicMock()
        mock_notifier.send_channel_message = AsyncMock(return_value="msg-1")
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        mock_calendar = MagicMock()
        mock_calendar.query_tomorrow_deadlines.return_value = [
            {"page_id": "p1", "title": "테스트 공고", "end_date": "2026-07-22", "url": "https://example.com"}
        ]
        mock_calendar.query_expired_active.return_value = [{"page_id": "p2"}]
        mock_calendar.update_status.return_value = None
        mock_calendar_cls.return_value = mock_calendar

        await reminder_job(mock_settings)

        mock_notifier.send_channel_message.assert_called_once()
        mock_calendar.update_status.assert_called_once_with("p2", "마감")

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.create_notifier")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    async def test_reminder_job_no_reminders(
        self,
        mock_calendar_cls: MagicMock,
        mock_create_notifier: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """리마인더 대상이 없을 때 포스팅을 건너뛰는지 확인한다."""
        mock_notifier = MagicMock()
        mock_notifier.send_channel_message = AsyncMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        mock_calendar = MagicMock()
        mock_calendar.query_tomorrow_deadlines.return_value = []
        mock_calendar.query_expired_active.return_value = []
        mock_calendar_cls.return_value = mock_calendar

        await reminder_job(mock_settings)

        mock_notifier.send_channel_message.assert_not_called()
