"""텔레그램 채널 포스팅 모듈.

텔레그램 Bot API를 통해 채널에 메시지를 전송하고,
실패 시 재시도 로직과 관리자 알림을 처리한다.
post_history 테이블에 포스팅 결과를 기록한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from src.notifier.formatter import format_new_announcement

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.db.models import Announcement

logger = logging.getLogger(__name__)

# 재시도 설정
MAX_RETRIES = 3
RETRY_INTERVAL_SECONDS = 30


class TelegramNotifier:
    """텔레그램 채널 포스팅 및 관리자 알림 클래스.

    Args:
        bot_token: 텔레그램 봇 토큰.
        channel_id: 포스팅 대상 채널 ID.
        admin_chat_id: 관리자 DM 채팅 ID.
    """

    def __init__(self, bot_token: str, channel_id: str, admin_chat_id: str) -> None:
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
        self.admin_chat_id = admin_chat_id

    async def send_message(self, chat_id: str, text: str) -> str | None:
        """텔레그램 메시지를 전송한다.

        Args:
            chat_id: 메시지 전송 대상 채팅 ID.
            text: 전송할 메시지 텍스트 (MarkdownV2 형식).

        Returns:
            성공 시 메시지 ID 문자열, 실패 시 None.

        Raises:
            TelegramError: 텔레그램 API 에러.
        """
        message = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return str(message.message_id)

    async def send_new_announcement(
        self, announcement: Announcement, session: Session
    ) -> bool:
        """새 공고를 텔레그램 채널에 포스팅한다.

        실패 시 30초 간격으로 최대 3회 재시도하며,
        모든 시도가 실패하면 관리자에게 알림을 전송한다.
        결과를 post_history 테이블에 기록한다.

        Args:
            announcement: 포스팅할 공고 데이터.
            session: DB 세션 (post_history 기록용).

        Returns:
            성공 여부.

        Validates: Requirements 2.1, 2.2, 2.3, 2.4
        """
        from src.db.models import PostHistory

        text = format_new_announcement(announcement)
        last_error: str | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                message_id = await self.send_message(self.channel_id, text)

                # 성공 기록
                post_history = PostHistory(
                    announcement_id=announcement.id,
                    post_type="new",
                    posted_at=datetime.utcnow(),
                    status="success",
                    telegram_message_id=message_id,
                )
                session.add(post_history)
                session.flush()

                logger.info(
                    "공고 포스팅 성공: announcement_id=%d, message_id=%s",
                    announcement.id,
                    message_id,
                )
                return True

            except TelegramError as e:
                last_error = str(e)
                logger.warning(
                    "공고 포스팅 실패 (시도 %d/%d): announcement_id=%d, error=%s",
                    attempt,
                    MAX_RETRIES,
                    announcement.id,
                    last_error,
                )

                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_INTERVAL_SECONDS)

        # 모든 재시도 실패
        post_history = PostHistory(
            announcement_id=announcement.id,
            post_type="new",
            posted_at=datetime.utcnow(),
            status="failed",
            error_message=last_error,
        )
        session.add(post_history)
        session.flush()

        logger.error(
            "공고 포스팅 최종 실패: announcement_id=%d, error=%s",
            announcement.id,
            last_error,
        )

        # 관리자 알림 전송
        await self.send_admin_notification(
            f"⚠️ 공고 포스팅 실패\n\n"
            f"공고 ID: {announcement.id}\n"
            f"공고명: {announcement.title}\n"
            f"오류: {last_error}"
        )

        return False

    async def send_admin_notification(self, message: str) -> None:
        """관리자에게 DM 알림을 전송한다.

        관리자 알림 전송 자체가 실패해도 예외를 전파하지 않고 로그만 남긴다.

        Args:
            message: 전송할 알림 메시지 (플레인 텍스트).

        Validates: Requirements 2.4
        """
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=message,
            )
            logger.info("관리자 알림 전송 성공")
        except TelegramError as e:
            logger.error("관리자 알림 전송 실패: %s", e)

    async def send_channel_message(self, text: str) -> str | None:
        """채널에 MarkdownV2 메시지를 전송한다 (범용).

        Args:
            text: 전송할 메시지 텍스트 (MarkdownV2 형식).

        Returns:
            성공 시 메시지 ID 문자열, 실패 시 None.
        """
        try:
            message_id = await self.send_message(self.channel_id, text)
            return message_id
        except TelegramError as e:
            logger.error("채널 메시지 전송 실패: %s", e)
            return None
