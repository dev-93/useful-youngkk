"""노티파이어 모듈 테스트.

formatter.py와 telegram.py의 단위 테스트를 포함한다.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import Announcement, PostHistory
from src.notifier.formatter import (
    escape_markdown_v2,
    format_eligibility_section,
    format_new_announcement,
)
from src.notifier.telegram import MAX_RETRIES, RETRY_INTERVAL_SECONDS, TelegramNotifier


# ─── formatter 테스트 ───────────────────────────────────────────────


class TestEscapeMarkdownV2:
    """escape_markdown_v2 함수 테스트."""

    def test_escapes_special_characters(self):
        """특수 문자가 올바르게 이스케이프된다."""
        text = "hello_world*bold[link](url)"
        result = escape_markdown_v2(text)
        assert result == r"hello\_world\*bold\[link\]\(url\)"

    def test_no_escape_for_plain_text(self):
        """특수 문자가 없는 텍스트는 변경 없이 반환된다."""
        text = "안녕하세요 테스트입니다"
        result = escape_markdown_v2(text)
        assert result == text

    def test_escapes_dot_and_dash(self):
        """점(.)과 하이픈(-)이 이스케이프된다."""
        text = "2024.01.01 - 2024.12.31"
        result = escape_markdown_v2(text)
        assert result == r"2024\.01\.01 \- 2024\.12\.31"

    def test_escapes_exclamation_mark(self):
        """느낌표(!)가 이스케이프된다."""
        text = "주의!"
        result = escape_markdown_v2(text)
        assert result == r"주의\!"

    def test_empty_string(self):
        """빈 문자열은 빈 문자열을 반환한다."""
        assert escape_markdown_v2("") == ""

    def test_escapes_pipe_and_tilde(self):
        """파이프(|)와 틸드(~)가 이스케이프된다."""
        text = "a|b~c"
        result = escape_markdown_v2(text)
        assert result == r"a\|b\~c"


class TestFormatEligibilitySection:
    """format_eligibility_section 함수 테스트."""

    def _make_announcement(
        self,
        age: str | None = None,
        income: str | None = None,
        homeless: str | None = None,
        residence: str | None = None,
    ) -> Announcement:
        """테스트용 Announcement 객체를 생성한다."""
        a = Announcement(
            id=1,
            source_site="sh",
            source_id="TEST001",
            title="테스트 공고",
            eligibility_age=age,
            eligibility_income=income,
            eligibility_homeless=homeless,
            eligibility_residence=residence,
        )
        return a

    def test_all_fields_present(self):
        """모든 자격요건 항목이 있을 때 안내 문구가 없다."""
        announcement = self._make_announcement(
            age="만 19~39세",
            income="중위소득 100% 이하",
            homeless="무주택 세대구성원",
            residence="서울 거주 1년 이상",
        )
        result = format_eligibility_section(announcement)

        assert "📋 *자격요건*" in result
        assert "나이:" in result
        assert "소득:" in result
        assert "무주택:" in result
        assert "거주기간:" in result
        # 안내 문구가 없어야 함
        assert "상세 요건은 공고 원문을 확인해 주세요" not in result

    def test_missing_fields_show_notice(self):
        """누락된 항목이 있을 때 안내 문구가 포함된다."""
        announcement = self._make_announcement(
            age="만 19~39세",
            income=None,
            homeless="무주택 세대구성원",
            residence=None,
        )
        result = format_eligibility_section(announcement)

        assert "정보 없음" in result
        assert "상세 요건은 공고 원문을 확인해 주세요" in result

    def test_all_fields_missing(self):
        """모든 항목이 누락되면 모두 '정보 없음'으로 표시되고 안내 문구가 있다."""
        announcement = self._make_announcement()
        result = format_eligibility_section(announcement)

        assert result.count("정보 없음") == 4
        assert "상세 요건은 공고 원문을 확인해 주세요" in result

    def test_section_header(self):
        """'📋 자격요건' 섹션 헤더가 포함된다."""
        announcement = self._make_announcement(age="만 19세 이상")
        result = format_eligibility_section(announcement)
        assert result.startswith("📋 *자격요건*")

    def test_special_characters_escaped(self):
        """자격요건 값의 특수 문자가 이스케이프된다."""
        announcement = self._make_announcement(
            age="만 19~39세",
            income="중위소득 100% (기준)",
            homeless="무주택자",
            residence="1년 이상",
        )
        result = format_eligibility_section(announcement)
        # 틸드와 괄호가 이스케이프 되어야 함
        assert r"19\~39" in result
        assert r"\(" in result
        assert r"\)" in result


class TestFormatNewAnnouncement:
    """format_new_announcement 함수 테스트."""

    def _make_announcement(self, **kwargs) -> Announcement:
        """테스트용 Announcement 객체를 생성한다."""
        defaults = {
            "id": 1,
            "source_site": "sh",
            "source_id": "SH2024001",
            "title": "2024년 행복주택 모집공고",
            "housing_type": "행복주택",
            "start_date": date(2024, 3, 1),
            "end_date": date(2024, 3, 31),
            "eligibility_age": "만 19~39세",
            "eligibility_income": "중위소득 100% 이하",
            "eligibility_homeless": "무주택 세대구성원",
            "eligibility_residence": "서울 거주 1년 이상",
            "original_url": "https://www.i-sh.co.kr/example",
        }
        defaults.update(kwargs)
        return Announcement(**defaults)

    def test_contains_header(self):
        """메시지에 '새 청약 공고' 헤더가 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "🏠 *새 청약 공고*" in result

    def test_contains_title(self):
        """메시지에 공고명이 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "*공고명:*" in result
        assert "2024년 행복주택 모집공고" in result

    def test_contains_housing_type(self):
        """메시지에 공고 구분과 모집유형이 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "행복주택" in result

    def test_contains_period(self):
        """메시지에 신청기간이 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "*신청기간:*" in result
        assert "2024" in result

    def test_contains_eligibility_section(self):
        """메시지에 자격요건 섹션이 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "📋 *자격요건*" in result

    def test_contains_link(self):
        """메시지에 원문 링크가 포함된다."""
        announcement = self._make_announcement()
        result = format_new_announcement(announcement)
        assert "🔗 [원문 보기]" in result
        assert "https://www.i-sh.co.kr/example" in result

    def test_missing_housing_type_shows_default(self):
        """모집유형이 없으면 '미정'으로 표시된다."""
        announcement = self._make_announcement(housing_type=None)
        result = format_new_announcement(announcement)
        assert "미정" in result

    def test_missing_dates_shows_default(self):
        """신청기간이 없으면 '미정'으로 표시된다."""
        announcement = self._make_announcement(start_date=None, end_date=None)
        result = format_new_announcement(announcement)
        # "미정" should appear in the period section
        lines = result.split("\n")
        period_line = [l for l in lines if "신청기간" in l][0]
        assert "미정" in period_line

    def test_no_link_when_url_missing(self):
        """원문 URL이 없으면 링크 섹션이 없다."""
        announcement = self._make_announcement(original_url=None)
        result = format_new_announcement(announcement)
        assert "🔗" not in result

    def test_only_start_date(self):
        """시작일만 있을 때 기간이 올바르게 표시된다."""
        announcement = self._make_announcement(start_date=date(2024, 5, 1), end_date=None)
        result = format_new_announcement(announcement)
        assert "2024" in result
        assert "05" in result


# ─── telegram.py 테스트 ─────────────────────────────────────────────


class TestTelegramNotifier:
    """TelegramNotifier 클래스 테스트."""

    def _make_announcement(self) -> Announcement:
        """테스트용 Announcement 객체를 생성한다."""
        return Announcement(
            id=1,
            source_site="sh",
            source_id="SH2024001",
            title="테스트 공고",
            housing_type="행복주택",
            start_date=date(2024, 3, 1),
            end_date=date(2024, 3, 31),
            eligibility_age="만 19~39세",
            eligibility_income="중위소득 100% 이하",
            eligibility_homeless="무주택 세대구성원",
            eligibility_residence="서울 거주 1년 이상",
            original_url="https://example.com",
        )

    @pytest.mark.asyncio
    async def test_send_new_announcement_success(self):
        """포스팅 성공 시 True를 반환하고 post_history를 기록한다."""
        announcement = self._make_announcement()
        session = MagicMock()

        mock_message = MagicMock()
        mock_message.message_id = 12345

        with patch("telegram.Bot.send_message", new_callable=AsyncMock, return_value=mock_message):
            notifier = TelegramNotifier(
                bot_token="test_token",
                channel_id="@test_channel",
                admin_chat_id="123456789",
            )
            result = await notifier.send_new_announcement(announcement, session)

        assert result is True
        session.add.assert_called_once()
        session.flush.assert_called_once()

        # post_history 레코드 확인
        post_record = session.add.call_args[0][0]
        assert isinstance(post_record, PostHistory)
        assert post_record.status == "success"
        assert post_record.post_type == "new"
        assert post_record.telegram_message_id == "12345"

    @pytest.mark.asyncio
    async def test_send_new_announcement_retry_success(self):
        """첫 시도 실패 후 재시도에서 성공한다."""
        announcement = self._make_announcement()
        session = MagicMock()

        mock_message = MagicMock()
        mock_message.message_id = 99999

        from telegram.error import TelegramError

        with patch(
            "telegram.Bot.send_message",
            new_callable=AsyncMock,
            side_effect=[TelegramError("Network error"), mock_message],
        ) as mock_send:
            with patch("src.notifier.telegram.asyncio.sleep", new_callable=AsyncMock):
                notifier = TelegramNotifier(
                    bot_token="test_token",
                    channel_id="@test_channel",
                    admin_chat_id="123456789",
                )
                result = await notifier.send_new_announcement(announcement, session)

        assert result is True
        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_send_new_announcement_all_retries_fail(self):
        """모든 재시도가 실패하면 False를 반환하고 관리자 알림을 전송한다."""
        announcement = self._make_announcement()
        session = MagicMock()

        from telegram.error import TelegramError

        with patch(
            "telegram.Bot.send_message",
            new_callable=AsyncMock,
            side_effect=TelegramError("Persistent error"),
        ) as mock_send:
            with patch("src.notifier.telegram.asyncio.sleep", new_callable=AsyncMock):
                notifier = TelegramNotifier(
                    bot_token="test_token",
                    channel_id="@test_channel",
                    admin_chat_id="123456789",
                )
                result = await notifier.send_new_announcement(announcement, session)

        assert result is False
        # 3 retries + 1 admin notification attempt
        assert mock_send.call_count == MAX_RETRIES + 1

        # post_history에 실패 기록
        post_record = session.add.call_args[0][0]
        assert isinstance(post_record, PostHistory)
        assert post_record.status == "failed"
        assert post_record.error_message == "Persistent error"

    @pytest.mark.asyncio
    async def test_send_admin_notification_success(self):
        """관리자 알림이 성공적으로 전송된다."""
        mock_message = MagicMock()
        mock_message.message_id = 1

        with patch(
            "telegram.Bot.send_message", new_callable=AsyncMock, return_value=mock_message
        ) as mock_send:
            notifier = TelegramNotifier(
                bot_token="test_token",
                channel_id="@test_channel",
                admin_chat_id="123456789",
            )
            await notifier.send_admin_notification("테스트 알림")

        mock_send.assert_called_once_with(
            chat_id="123456789",
            text="테스트 알림",
        )

    @pytest.mark.asyncio
    async def test_send_admin_notification_failure_no_exception(self):
        """관리자 알림 전송 실패 시 예외가 전파되지 않는다."""
        from telegram.error import TelegramError

        with patch(
            "telegram.Bot.send_message",
            new_callable=AsyncMock,
            side_effect=TelegramError("Admin unreachable"),
        ):
            notifier = TelegramNotifier(
                bot_token="test_token",
                channel_id="@test_channel",
                admin_chat_id="123456789",
            )
            # 예외가 발생하지 않아야 함
            await notifier.send_admin_notification("테스트 알림")

    @pytest.mark.asyncio
    async def test_retry_interval_is_30_seconds(self):
        """재시도 간격이 30초인지 확인한다."""
        assert RETRY_INTERVAL_SECONDS == 30

    @pytest.mark.asyncio
    async def test_max_retries_is_3(self):
        """최대 재시도 횟수가 3회인지 확인한다."""
        assert MAX_RETRIES == 3

    @pytest.mark.asyncio
    async def test_send_channel_message_success(self):
        """채널 메시지 전송 성공 시 메시지 ID를 반환한다."""
        mock_message = MagicMock()
        mock_message.message_id = 777

        with patch(
            "telegram.Bot.send_message", new_callable=AsyncMock, return_value=mock_message
        ):
            notifier = TelegramNotifier(
                bot_token="test_token",
                channel_id="@test_channel",
                admin_chat_id="123456789",
            )
            result = await notifier.send_channel_message("테스트 메시지")

        assert result == "777"

    @pytest.mark.asyncio
    async def test_send_channel_message_failure_returns_none(self):
        """채널 메시지 전송 실패 시 None을 반환한다."""
        from telegram.error import TelegramError

        with patch(
            "telegram.Bot.send_message",
            new_callable=AsyncMock,
            side_effect=TelegramError("Channel error"),
        ):
            notifier = TelegramNotifier(
                bot_token="test_token",
                channel_id="@test_channel",
                admin_chat_id="123456789",
            )
            result = await notifier.send_channel_message("테스트 메시지")

        assert result is None


# ─── weekly_summary.py 테스트 ───────────────────────────────────────


from src.notifier.weekly_summary import WeeklySummaryGenerator, get_week_range

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


class TestGetWeekRange:
    """get_week_range 함수 테스트."""

    def test_monday_returns_same_week(self):
        """월요일 입력 시 해당 주 월~일을 반환한다."""
        monday = date(2024, 7, 1)  # 2024-07-01 = 월요일
        result_monday, result_sunday = get_week_range(monday)
        assert result_monday == date(2024, 7, 1)
        assert result_sunday == date(2024, 7, 7)

    def test_wednesday_returns_same_week(self):
        """수요일 입력 시 해당 주 월~일을 반환한다."""
        wednesday = date(2024, 7, 3)  # 2024-07-03 = 수요일
        result_monday, result_sunday = get_week_range(wednesday)
        assert result_monday == date(2024, 7, 1)
        assert result_sunday == date(2024, 7, 7)

    def test_sunday_returns_same_week(self):
        """일요일 입력 시 해당 주 월~일을 반환한다."""
        sunday = date(2024, 7, 7)  # 2024-07-07 = 일요일
        result_monday, result_sunday = get_week_range(sunday)
        assert result_monday == date(2024, 7, 1)
        assert result_sunday == date(2024, 7, 7)

    def test_saturday_returns_same_week(self):
        """토요일 입력 시 해당 주 월~일을 반환한다."""
        saturday = date(2024, 7, 6)  # 2024-07-06 = 토요일
        result_monday, result_sunday = get_week_range(saturday)
        assert result_monday == date(2024, 7, 1)
        assert result_sunday == date(2024, 7, 7)


@pytest.fixture
def db_session():
    """인메모리 SQLite DB 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestWeeklySummaryGenerator:
    """WeeklySummaryGenerator 클래스 테스트."""

    CALENDAR_URL = "https://notion.so/calendar/test-share-url"

    def _make_announcement(self, **kwargs) -> Announcement:
        """테스트용 Announcement 객체를 생성한다."""
        defaults = {
            "source_site": "sh",
            "source_id": "SH2024001",
            "title": "행복주택 신촌 모집공고",
            "housing_type": "행복주택",
            "start_date": date(2024, 7, 1),
            "end_date": date(2024, 7, 5),
            "status": "active",
            "original_url": "https://www.i-sh.co.kr/example",
        }
        defaults.update(kwargs)
        return Announcement(**defaults)

    def test_get_weekly_announcements_returns_ending_this_week(self, db_session):
        """이번 주 마감 공고를 조회한다."""
        # 2024-07-01 (월) ~ 2024-07-07 (일)
        a1 = self._make_announcement(
            source_id="A1", end_date=date(2024, 7, 3), title="공고A"
        )
        a2 = self._make_announcement(
            source_id="A2", end_date=date(2024, 7, 7), title="공고B"
        )
        # 다음 주 마감 → 포함되면 안 됨
        a3 = self._make_announcement(
            source_id="A3", end_date=date(2024, 7, 8), title="공고C"
        )

        db_session.add_all([a1, a2, a3])
        db_session.commit()

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.get_weekly_announcements(reference_date=date(2024, 7, 1))

        assert len(result) == 2
        assert result[0].title == "공고A"
        assert result[1].title == "공고B"

    def test_get_weekly_announcements_empty(self, db_session):
        """주간 마감 공고가 없으면 빈 리스트를 반환한다."""
        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.get_weekly_announcements(reference_date=date(2024, 7, 1))
        assert result == []

    def test_format_weekly_summary_with_announcements(self, db_session):
        """공고가 있을 때 주간 요약 메시지를 올바르게 포맷팅한다."""
        announcements = [
            self._make_announcement(
                source_id="A1",
                title="행복주택 신촌",
                end_date=date(2024, 7, 3),
                housing_type="행복주택",
            ),
            self._make_announcement(
                source_id="A2",
                title="공공임대 강남",
                end_date=date(2024, 7, 5),
                housing_type="공공임대",
            ),
        ]

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_weekly_summary(announcements)

        # 헤더 포함
        assert "📅 *이번 주 마감 예정 청약*" in result
        # 번호 이모지 포함
        assert "1️⃣" in result
        assert "2️⃣" in result
        # 공고명 포함
        assert "행복주택 신촌" in result
        assert "공공임대 강남" in result
        # 마감일 포함
        assert "2024" in result
        assert "07" in result
        # 유형 포함
        assert "행복주택" in result
        assert "공공임대" in result
        # 캘린더 링크 포함
        assert "📋 [전체 일정 확인하기]" in result
        assert self.CALENDAR_URL in result

    def test_format_weekly_summary_no_announcements(self, db_session):
        """공고가 없을 때 안내 메시지를 포맷팅한다."""
        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_weekly_summary([])

        assert "📅 *이번 주 마감 예정 청약*" in result
        assert "이번 주 마감 예정 청약이 없습니다" in result
        assert "📋 [전체 일정 확인하기]" in result
        assert self.CALENDAR_URL in result
        # 번호 이모지가 없어야 함
        assert "1️⃣" not in result

    def test_format_weekly_summary_escapes_special_chars(self, db_session):
        """공고명의 특수 문자가 이스케이프된다."""
        announcements = [
            self._make_announcement(
                source_id="A1",
                title="SH 2024-1차 공고 (서울)",
                end_date=date(2024, 7, 3),
            ),
        ]

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_weekly_summary(announcements)

        # 하이픈, 괄호가 이스케이프 되어야 함
        assert r"\-" in result
        assert r"\(" in result
        assert r"\)" in result

    def test_get_reminder_announcements(self, db_session):
        """내일 마감 공고를 조회한다."""
        # reference_date = 2024-07-02, tomorrow = 2024-07-03
        a1 = self._make_announcement(
            source_id="A1", end_date=date(2024, 7, 3), title="내일마감"
        )
        a2 = self._make_announcement(
            source_id="A2", end_date=date(2024, 7, 4), title="모레마감"
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.get_reminder_announcements(reference_date=date(2024, 7, 2))

        assert len(result) == 1
        assert result[0].title == "내일마감"

    def test_get_reminder_announcements_empty(self, db_session):
        """내일 마감 공고가 없으면 빈 리스트를 반환한다."""
        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.get_reminder_announcements(reference_date=date(2024, 7, 2))
        assert result == []

    def test_format_reminder_single(self, db_session):
        """단일 공고 리마인더 메시지를 올바르게 포맷팅한다."""
        announcement = self._make_announcement(
            title="행복주택 역삼",
            end_date=date(2024, 7, 3),
            housing_type="행복주택",
            original_url="https://example.com/detail",
        )

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_reminder(announcement)

        assert "⏰ *내일 마감 리마인더*" in result
        assert "행복주택 역삼" in result
        assert "2024" in result
        assert "행복주택" in result
        assert "🔗 [원문 보기]" in result
        assert "https://example.com/detail" in result

    def test_format_reminder_no_url(self, db_session):
        """원문 URL이 없는 공고 리마인더에 링크가 없다."""
        announcement = self._make_announcement(
            title="공공임대 강남",
            end_date=date(2024, 7, 3),
            original_url=None,
        )

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_reminder(announcement)

        assert "⏰ *내일 마감 리마인더*" in result
        assert "공공임대 강남" in result
        assert "🔗" not in result

    def test_format_reminder_batch_single(self, db_session):
        """단건 일괄 리마인더는 format_reminder와 동일하다."""
        announcement = self._make_announcement(
            title="행복주택 역삼",
            end_date=date(2024, 7, 3),
            housing_type="행복주택",
        )

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        single_result = generator.format_reminder(announcement)
        batch_result = generator.format_reminder_batch([announcement])

        assert single_result == batch_result

    def test_format_reminder_batch_multiple(self, db_session):
        """여러 공고 일괄 리마인더 메시지를 포맷팅한다."""
        announcements = [
            self._make_announcement(
                source_id="A1",
                title="행복주택 역삼",
                end_date=date(2024, 7, 3),
                housing_type="행복주택",
                original_url="https://example.com/1",
            ),
            self._make_announcement(
                source_id="A2",
                title="공공임대 신촌",
                end_date=date(2024, 7, 3),
                housing_type="공공임대",
                original_url="https://example.com/2",
            ),
        ]

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_reminder_batch(announcements)

        # 헤더 한 번만
        assert result.count("⏰ *내일 마감 리마인더*") == 1
        # 두 공고 모두 포함
        assert "행복주택 역삼" in result
        assert "공공임대 신촌" in result
        # 원문 링크 포함
        assert "https://example.com/1" in result
        assert "https://example.com/2" in result

    def test_format_reminder_batch_empty(self, db_session):
        """빈 목록에 대한 일괄 리마인더는 빈 문자열을 반환한다."""
        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.format_reminder_batch([])
        assert result == ""

    def test_weekly_summary_excludes_non_active(self, db_session):
        """비활성(archived) 공고는 주간 요약에 포함되지 않는다."""
        a_active = self._make_announcement(
            source_id="A1", end_date=date(2024, 7, 3), title="활성공고", status="active"
        )
        a_archived = self._make_announcement(
            source_id="A2", end_date=date(2024, 7, 4), title="보관공고", status="archived"
        )
        db_session.add_all([a_active, a_archived])
        db_session.commit()

        generator = WeeklySummaryGenerator(db_session, self.CALENDAR_URL)
        result = generator.get_weekly_announcements(reference_date=date(2024, 7, 1))

        assert len(result) == 1
        assert result[0].title == "활성공고"
