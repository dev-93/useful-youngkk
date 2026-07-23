"""노션 캘린더 연동 모듈 테스트."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from notion_client.errors import APIResponseError

from src.calendar.notion_client import (
    MAX_RETRIES,
    NotionCalendarManager,
    determine_status,
    with_retry,
)
from src.db.models import Announcement


# --- determine_status 테스트 ---


class TestDetermineStatus:
    """determine_status 함수 테스트."""

    def test_returns_예정_when_today_before_start_date(self):
        """오늘이 시작일 이전이면 '예정'을 반환한다."""
        future_start = date.today() + timedelta(days=5)
        future_end = date.today() + timedelta(days=15)
        assert determine_status(future_start, future_end) == "예정"

    def test_returns_진행중_when_today_between_dates(self):
        """오늘이 시작일과 마감일 사이이면 '진행중'을 반환한다."""
        past_start = date.today() - timedelta(days=5)
        future_end = date.today() + timedelta(days=5)
        assert determine_status(past_start, future_end) == "진행중"

    def test_returns_마감_when_today_after_end_date(self):
        """오늘이 마감일 이후이면 '마감'을 반환한다."""
        past_start = date.today() - timedelta(days=15)
        past_end = date.today() - timedelta(days=1)
        assert determine_status(past_start, past_end) == "마감"

    def test_returns_진행중_when_today_equals_start_date(self):
        """오늘이 시작일과 같으면 '진행중'을 반환한다."""
        today = date.today()
        future_end = today + timedelta(days=10)
        assert determine_status(today, future_end) == "진행중"

    def test_returns_진행중_when_today_equals_end_date(self):
        """오늘이 마감일과 같으면 '진행중'을 반환한다."""
        past_start = date.today() - timedelta(days=5)
        today = date.today()
        assert determine_status(past_start, today) == "진행중"

    def test_returns_진행중_when_start_date_is_none(self):
        """시작일이 없으면 '진행중'을 반환한다."""
        future_end = date.today() + timedelta(days=5)
        assert determine_status(None, future_end) == "진행중"

    def test_returns_진행중_when_end_date_is_none(self):
        """마감일이 없으면 '진행중'을 반환한다."""
        past_start = date.today() - timedelta(days=5)
        assert determine_status(past_start, None) == "진행중"

    def test_returns_진행중_when_both_dates_none(self):
        """시작일과 마감일이 모두 없으면 '진행중'을 반환한다."""
        assert determine_status(None, None) == "진행중"


# --- with_retry 데코레이터 테스트 ---


class TestWithRetry:
    """with_retry 데코레이터 테스트."""

    def test_succeeds_on_first_try(self):
        """첫 시도에 성공하면 바로 결과를 반환한다."""
        mock_func = MagicMock(return_value="success")
        decorated = with_retry(mock_func)
        result = decorated()
        assert result == "success"
        assert mock_func.call_count == 1

    @patch("src.calendar.notion_client.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        """실패 후 재시도하여 성공한다."""
        mock_func = MagicMock(
            side_effect=[Exception("fail"), Exception("fail"), "success"]
        )
        decorated = with_retry(mock_func)
        result = decorated()
        assert result == "success"
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("src.calendar.notion_client.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        """최대 재시도 횟수를 초과하면 예외를 발생시킨다."""
        mock_func = MagicMock(side_effect=Exception("persistent failure"))
        decorated = with_retry(mock_func)
        with pytest.raises(Exception, match="persistent failure"):
            decorated()
        assert mock_func.call_count == MAX_RETRIES
        assert mock_sleep.call_count == MAX_RETRIES - 1

    @patch("src.calendar.notion_client.time.sleep")
    def test_retries_on_api_response_error(self, mock_sleep):
        """APIResponseError 발생 시 재시도한다."""
        import httpx

        api_error = APIResponseError(
            code="internal_server_error",
            status=500,
            message="Server Error",
            headers=httpx.Headers({}),
            raw_body_text="",
        )
        mock_func = MagicMock(side_effect=[api_error, "success"])
        decorated = with_retry(mock_func)
        result = decorated()
        assert result == "success"
        assert mock_func.call_count == 2


# --- NotionCalendarManager 테스트 ---


def _make_announcement(**kwargs) -> Announcement:
    """테스트용 Announcement 인스턴스를 생성한다."""
    defaults = {
        "id": 1,
        "source_site": "sh",
        "source_id": "12345",
        "title": "테스트 공고",
        "housing_type": "행복주택",
        "start_date": date.today() - timedelta(days=2),
        "end_date": date.today() + timedelta(days=10),
        "result_date": date.today() + timedelta(days=30),
        "original_url": "https://example.com/announcement/1",
        "status": "active",
        "notion_page_id": None,
    }
    defaults.update(kwargs)
    announcement = Announcement()
    for key, value in defaults.items():
        setattr(announcement, key, value)
    return announcement


class TestNotionCalendarManager:
    """NotionCalendarManager 클래스 테스트."""

    def setup_method(self):
        """테스트 전 매니저 인스턴스를 생성한다."""
        with patch("src.calendar.notion_client.Client"):
            self.manager = NotionCalendarManager(
                api_key="test-api-key",
                database_id="test-db-id",
                data_source_id="test-ds-id",
                calendar_share_url="https://notion.so/test-calendar",
            )
        self.manager.client = MagicMock()

    def test_get_share_url(self):
        """캘린더 공유 URL을 반환한다."""
        assert self.manager.get_share_url() == "https://notion.so/test-calendar"

    def test_create_page_success(self):
        """공고를 노션 페이지로 성공적으로 생성한다."""
        announcement = _make_announcement()
        self.manager.client.pages.create.return_value = {"id": "page-id-123"}

        page_id = self.manager.create_page(announcement)

        assert page_id == "page-id-123"
        self.manager.client.pages.create.assert_called_once()
        call_kwargs = self.manager.client.pages.create.call_args[1]
        assert call_kwargs["parent"] == {"database_id": "test-db-id"}

        props = call_kwargs["properties"]
        assert props["공고명"]["title"][0]["text"]["content"] == "테스트 공고"
        assert props["모집 유형"]["select"]["name"] == "행복주택"
        assert props["상태"]["select"]["name"] == "진행중"
        assert props["원문 링크"]["url"] == "https://example.com/announcement/1"

    def test_create_page_with_dates(self):
        """날짜 필드가 ISO 형식으로 설정된다."""
        start = date(2025, 1, 15)
        end = date(2025, 2, 15)
        result = date(2025, 3, 1)
        announcement = _make_announcement(
            start_date=start, end_date=end, result_date=result
        )
        self.manager.client.pages.create.return_value = {"id": "page-id-456"}

        self.manager.create_page(announcement)

        call_kwargs = self.manager.client.pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert props["시작일"]["date"]["start"] == "2025-01-15"
        assert props["마감일"]["date"]["start"] == "2025-02-15"
        assert props["발표일"]["date"]["start"] == "2025-03-01"

    def test_create_page_without_optional_fields(self):
        """선택 필드가 없으면 해당 속성을 제외한다."""
        announcement = _make_announcement(
            housing_type=None,
            start_date=None,
            end_date=None,
            result_date=None,
            original_url=None,
        )
        self.manager.client.pages.create.return_value = {"id": "page-id-789"}

        page_id = self.manager.create_page(announcement)

        assert page_id == "page-id-789"
        call_kwargs = self.manager.client.pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert "모집 유형" not in props
        assert "시작일" not in props
        assert "마감일" not in props
        assert "발표일" not in props
        assert "원문링크" not in props

    def test_update_status_success(self):
        """노션 페이지 상태를 성공적으로 업데이트한다."""
        self.manager.client.pages.update.return_value = {}

        self.manager.update_status("page-id-123", "마감")

        self.manager.client.pages.update.assert_called_once_with(
            page_id="page-id-123",
            properties={"상태": {"select": {"name": "마감"}}},
        )

    def test_close_expired_updates_expired_announcements(self):
        """마감일이 경과한 공고들의 상태를 '마감'으로 변경한다."""
        expired = _make_announcement(
            id=1,
            end_date=date.today() - timedelta(days=1),
            notion_page_id="page-expired",
        )
        active = _make_announcement(
            id=2,
            end_date=date.today() + timedelta(days=5),
            notion_page_id="page-active",
        )
        no_notion = _make_announcement(
            id=3,
            end_date=date.today() - timedelta(days=1),
            notion_page_id=None,
        )

        self.manager.client.pages.update.return_value = {}

        updated = self.manager.close_expired([expired, active, no_notion])

        assert updated == ["page-expired"]
        self.manager.client.pages.update.assert_called_once()

    def test_close_expired_continues_on_individual_failure(self):
        """개별 공고 상태 변경 실패 시에도 나머지 공고를 처리한다."""
        expired1 = _make_announcement(
            id=1,
            end_date=date.today() - timedelta(days=1),
            notion_page_id="page-1",
        )
        expired2 = _make_announcement(
            id=2,
            end_date=date.today() - timedelta(days=2),
            notion_page_id="page-2",
        )

        # 첫 번째 호출은 모든 재시도 후 실패, 두 번째 호출은 성공
        self.manager.client.pages.update.side_effect = [
            Exception("API Error"),
            Exception("API Error"),
            Exception("API Error"),
            {},  # page-2 성공
        ]

        updated = self.manager.close_expired([expired1, expired2])

        assert updated == ["page-2"]

    def test_create_page_status_예정_for_future_announcement(self):
        """시작일이 미래인 공고는 '예정' 상태로 생성한다."""
        announcement = _make_announcement(
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=15),
        )
        self.manager.client.pages.create.return_value = {"id": "page-future"}

        self.manager.create_page(announcement)

        call_kwargs = self.manager.client.pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert props["상태"]["select"]["name"] == "예정"

    def test_create_page_status_마감_for_past_announcement(self):
        """마감일이 과거인 공고는 '마감' 상태로 생성한다."""
        announcement = _make_announcement(
            start_date=date.today() - timedelta(days=15),
            end_date=date.today() - timedelta(days=1),
        )
        self.manager.client.pages.create.return_value = {"id": "page-past"}

        self.manager.create_page(announcement)

        call_kwargs = self.manager.client.pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert props["상태"]["select"]["name"] == "마감"
