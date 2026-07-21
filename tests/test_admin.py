"""관리자 알림 모듈 테스트.

admin.py의 알림 유틸리티 함수 및 DB 재시도 로직을 검증한다.

Validates: Requirements 2.4, 6.3
"""

from __future__ import annotations

import time
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
from src.notifier.admin import (
    DB_RETRY_MAX,
    create_notifier,
    notify_admin_error,
    notify_crawl_failure,
    notify_db_save_failure,
    notify_job_failure,
    notify_notion_failure,
    retry_db_operation,
)
from src.notifier.telegram import TelegramNotifier


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


@pytest.fixture
def mock_notifier() -> TelegramNotifier:
    """send_admin_notification이 모킹된 TelegramNotifier를 반환한다."""
    notifier = MagicMock(spec=TelegramNotifier)
    notifier.send_admin_notification = AsyncMock()
    return notifier


class TestCreateNotifier:
    """create_notifier 함수 테스트."""

    def test_creates_notifier_from_settings(self, mock_settings: Settings) -> None:
        """Settings에서 TelegramNotifier를 올바르게 생성한다."""
        with patch("src.notifier.admin.TelegramNotifier") as mock_cls:
            mock_cls.return_value = MagicMock()
            notifier = create_notifier(mock_settings)
            mock_cls.assert_called_once_with(
                bot_token="test-token",
                channel_id="@test_channel",
                admin_chat_id="12345",
            )


class TestNotifyAdminError:
    """notify_admin_error 함수 테스트."""

    @pytest.mark.asyncio
    async def test_sends_formatted_error_message(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """오류 유형과 상세 정보가 포함된 메시지를 전송한다."""
        await notify_admin_error(
            notifier=mock_notifier,
            error_type="테스트 오류",
            error_detail="상세 오류 메시지",
        )

        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "⚠️ 테스트 오류" in message
        assert "상세 오류 메시지" in message

    @pytest.mark.asyncio
    async def test_includes_context_when_provided(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """context가 있을 때 메시지에 포함된다."""
        await notify_admin_error(
            notifier=mock_notifier,
            error_type="오류",
            error_detail="에러",
            context="추가 정보",
        )

        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "추가 정보" in message

    @pytest.mark.asyncio
    async def test_no_context_section_when_not_provided(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """context가 없을 때 '상세:' 라인이 없다."""
        await notify_admin_error(
            notifier=mock_notifier,
            error_type="오류",
            error_detail="에러",
        )

        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "상세:" not in message


class TestNotifyCrawlFailure:
    """notify_crawl_failure 함수 테스트."""

    @pytest.mark.asyncio
    async def test_sends_crawl_failure_alert(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """크롤링 실패 알림에 사이트 정보가 포함된다."""
        await notify_crawl_failure(
            notifier=mock_notifier,
            source_site="sh",
            error="Connection timeout",
        )

        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "크롤링 최종 실패" in message
        assert "sh" in message
        assert "Connection timeout" in message
        assert "3회 재시도 모두 실패" in message


class TestNotifyDbSaveFailure:
    """notify_db_save_failure 함수 테스트."""

    @pytest.mark.asyncio
    async def test_sends_db_failure_alert(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """DB 저장 실패 알림에 작업 정보가 포함된다."""
        await notify_db_save_failure(
            notifier=mock_notifier,
            operation="공고 저장",
            error="disk full",
        )

        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "DB 저장 실패" in message
        assert "공고 저장" in message
        assert "disk full" in message


class TestNotifyNotionFailure:
    """notify_notion_failure 함수 테스트."""

    @pytest.mark.asyncio
    async def test_sends_notion_failure_alert(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """노션 API 실패 알림에 공고 ID가 포함된다."""
        await notify_notion_failure(
            notifier=mock_notifier,
            announcement_id=42,
            error="API rate limit exceeded",
        )

        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "노션 API 실패" in message
        assert "42" in message
        assert "API rate limit exceeded" in message


class TestNotifyJobFailure:
    """notify_job_failure 함수 테스트."""

    @pytest.mark.asyncio
    async def test_sends_job_failure_alert(
        self, mock_notifier: TelegramNotifier
    ) -> None:
        """작업 실패 알림에 작업 이름이 포함된다."""
        await notify_job_failure(
            notifier=mock_notifier,
            job_name="crawl_and_post",
            error="Unexpected error",
        )

        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "스케줄 작업 실패" in message
        assert "crawl_and_post" in message
        assert "Unexpected error" in message


class TestRetryDbOperation:
    """retry_db_operation 함수 테스트."""

    def test_success_on_first_attempt(self) -> None:
        """첫 시도에서 성공하면 즉시 결과를 반환한다."""
        operation = MagicMock(return_value="ok")
        result = retry_db_operation(operation, "테스트 작업", retry_interval=0)

        assert result == "ok"
        assert operation.call_count == 1

    def test_success_on_second_attempt(self) -> None:
        """첫 시도 실패 후 두 번째에 성공한다."""
        operation = MagicMock(side_effect=[Exception("fail"), "ok"])
        result = retry_db_operation(operation, "테스트 작업", retry_interval=0)

        assert result == "ok"
        assert operation.call_count == 2

    def test_raises_after_all_retries_exhausted(self) -> None:
        """모든 재시도 실패 시 마지막 예외를 전파한다."""
        operation = MagicMock(side_effect=Exception("persistent error"))

        with pytest.raises(Exception, match="persistent error"):
            retry_db_operation(
                operation, "테스트 작업", max_retries=3, retry_interval=0
            )

        assert operation.call_count == 3

    def test_default_max_retries_is_3(self) -> None:
        """기본 최대 재시도 횟수가 3회인지 확인한다."""
        assert DB_RETRY_MAX == 3

    def test_retries_correct_number_of_times(self) -> None:
        """지정한 max_retries만큼 재시도한다."""
        operation = MagicMock(side_effect=Exception("fail"))

        with pytest.raises(Exception):
            retry_db_operation(
                operation, "테스트 작업", max_retries=2, retry_interval=0
            )

        assert operation.call_count == 2


class TestSchedulerJobsAdminNotifications:
    """스케줄러 작업의 관리자 알림 통합 테스트."""

    @pytest.fixture
    def mock_settings(self) -> Settings:
        return Settings(
            telegram=TelegramConfig(
                bot_token="test-token",
                channel_id="@test_channel",
                admin_chat_id="12345",
            ),
            notion=NotionConfig(
                access_token="notion-key",
                database_id="notion-db-id",
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

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.run_with_retry")
    @patch("src.scheduler.jobs.create_notifier")
    async def test_crawl_failure_sends_admin_notification(
        self,
        mock_create_notifier: MagicMock,
        mock_run_with_retry: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """크롤링 3회 재시도 실패 시 관리자에게 알림이 전송된다."""
        from src.scheduler.jobs import crawl_and_post

        mock_session = MagicMock()
        mock_session.commit = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_notifier.send_new_announcement = AsyncMock(return_value=True)
        mock_create_notifier.return_value = mock_notifier

        # 크롤링 결과: 실패 (3회 재시도 후)
        mock_crawl_log = MagicMock()
        mock_crawl_log.status = "failed"
        mock_crawl_log.error_message = "Connection refused"
        mock_run_with_retry.return_value = mock_crawl_log

        await crawl_and_post(mock_settings)

        # 4개 크롤러 모두 실패 → 4회 관리자 알림
        assert mock_notifier.send_admin_notification.call_count == 4

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.WeeklySummaryGenerator")
    @patch("src.scheduler.jobs.create_notifier")
    async def test_weekly_summary_failure_sends_admin_notification(
        self,
        mock_create_notifier: MagicMock,
        mock_generator_cls: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """주간 요약 작업 실패 시 관리자에게 알림이 전송된다."""
        from src.scheduler.jobs import weekly_summary_job

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_notifier.send_channel_message = AsyncMock()
        mock_create_notifier.return_value = mock_notifier

        # WeeklySummaryGenerator에서 예외 발생
        mock_generator_cls.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await weekly_summary_job(mock_settings)

        # 관리자 알림 전송 확인
        mock_notifier.send_admin_notification.assert_called_once()
        message = mock_notifier.send_admin_notification.call_args[0][0]
        assert "스케줄 작업 실패" in message
        assert "weekly_summary_job" in message

    @pytest.mark.asyncio
    @patch("src.scheduler.jobs.get_session")
    @patch("src.scheduler.jobs.run_with_retry")
    @patch("src.scheduler.jobs.AnnouncementRepository")
    @patch("src.scheduler.jobs.NotionCalendarManager")
    @patch("src.scheduler.jobs.create_notifier")
    async def test_notion_failure_sends_admin_notification(
        self,
        mock_create_notifier: MagicMock,
        mock_calendar_cls: MagicMock,
        mock_repo_cls: MagicMock,
        mock_run_with_retry: MagicMock,
        mock_get_session: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """노션 API 실패 시 관리자에게 알림이 전송된다."""
        from src.scheduler.jobs import crawl_and_post

        mock_session = MagicMock()
        mock_session.commit = MagicMock()
        mock_get_session.return_value = mock_session

        mock_notifier = MagicMock()
        mock_notifier.send_admin_notification = AsyncMock()
        mock_notifier.send_new_announcement = AsyncMock(return_value=True)
        mock_create_notifier.return_value = mock_notifier

        # 크롤링 성공 (1건)
        mock_crawl_log = MagicMock()
        mock_crawl_log.status = "success"
        mock_crawl_log.new_count = 1
        mock_run_with_retry.return_value = mock_crawl_log

        # 새 공고
        mock_announcement = MagicMock()
        mock_announcement.id = 1
        mock_announcement.notion_page_id = None

        mock_repo = MagicMock()
        mock_repo.get_active.return_value = [mock_announcement]
        mock_repo_cls.return_value = mock_repo

        # 노션 API 실패
        mock_calendar = MagicMock()
        mock_calendar.create_page.side_effect = Exception("Notion API timeout")
        mock_calendar_cls.return_value = mock_calendar

        await crawl_and_post(mock_settings)

        # 관리자 알림 전송 확인 (노션 실패)
        mock_notifier.send_admin_notification.assert_called()
        calls = mock_notifier.send_admin_notification.call_args_list
        notion_alert = any("노션 API 실패" in str(c) for c in calls)
        assert notion_alert
