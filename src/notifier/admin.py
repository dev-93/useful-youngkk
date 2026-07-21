"""관리자 알림 유틸리티 모듈.

각종 오류 발생 시 관리자에게 텔레그램 DM 알림을 전송하는 중앙 집중 유틸리티.
크롤링 실패, DB 저장 실패, 노션 API 실패 등 모든 오류 경로에서 사용된다.

Validates: Requirements 2.4, 6.3
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Callable, TypeVar

from src.notifier.telegram import TelegramNotifier

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# DB 저장 재시도 설정
DB_RETRY_MAX = 3
DB_RETRY_INTERVAL_SECONDS = 5


def create_notifier(settings: Settings) -> TelegramNotifier:
    """Settings에서 TelegramNotifier 인스턴스를 생성한다.

    Args:
        settings: 애플리케이션 설정.

    Returns:
        TelegramNotifier 인스턴스.
    """
    return TelegramNotifier(
        bot_token=settings.telegram.bot_token,
        channel_id=settings.telegram.channel_id,
        admin_chat_id=settings.telegram.admin_chat_id,
    )


async def notify_admin_error(
    notifier: TelegramNotifier,
    error_type: str,
    error_detail: str,
    context: str | None = None,
) -> None:
    """관리자에게 오류 알림을 전송한다.

    Args:
        notifier: TelegramNotifier 인스턴스.
        error_type: 오류 유형 (예: "크롤링 실패", "DB 저장 실패").
        error_detail: 오류 상세 메시지.
        context: 추가 컨텍스트 정보 (선택).

    Validates: Requirements 2.4, 6.3
    """
    message_parts = [
        f"⚠️ {error_type}",
        "",
        f"오류: {error_detail}",
    ]
    if context:
        message_parts.insert(2, f"상세: {context}")

    message = "\n".join(message_parts)
    await notifier.send_admin_notification(message)


async def notify_crawl_failure(
    notifier: TelegramNotifier,
    source_site: str,
    error: str,
) -> None:
    """크롤링 최종 실패 시 관리자에게 알림을 전송한다.

    Args:
        notifier: TelegramNotifier 인스턴스.
        source_site: 실패한 크롤링 사이트.
        error: 오류 메시지.

    Validates: Requirements 2.4
    """
    await notify_admin_error(
        notifier=notifier,
        error_type="크롤링 최종 실패",
        error_detail=error,
        context=f"사이트: {source_site} (3회 재시도 모두 실패)",
    )


async def notify_db_save_failure(
    notifier: TelegramNotifier,
    operation: str,
    error: str,
) -> None:
    """DB 저장 실패 시 관리자에게 알림을 전송한다.

    Args:
        notifier: TelegramNotifier 인스턴스.
        operation: 실패한 DB 작업 설명.
        error: 오류 메시지.

    Validates: Requirements 6.3
    """
    await notify_admin_error(
        notifier=notifier,
        error_type="DB 저장 실패",
        error_detail=error,
        context=f"작업: {operation} (3회 재시도 모두 실패)",
    )


async def notify_notion_failure(
    notifier: TelegramNotifier,
    announcement_id: int,
    error: str,
) -> None:
    """노션 API 호출 최종 실패 시 관리자에게 알림을 전송한다.

    Args:
        notifier: TelegramNotifier 인스턴스.
        announcement_id: 실패한 공고 ID.
        error: 오류 메시지.

    Validates: Requirements 2.4
    """
    await notify_admin_error(
        notifier=notifier,
        error_type="노션 API 실패",
        error_detail=error,
        context=f"공고 ID: {announcement_id}",
    )


async def notify_job_failure(
    notifier: TelegramNotifier,
    job_name: str,
    error: str,
) -> None:
    """스케줄 작업 전체 실패 시 관리자에게 알림을 전송한다.

    Args:
        notifier: TelegramNotifier 인스턴스.
        job_name: 실패한 작업 이름.
        error: 오류 메시지.
    """
    await notify_admin_error(
        notifier=notifier,
        error_type="스케줄 작업 실패",
        error_detail=error,
        context=f"작업: {job_name}",
    )


def retry_db_operation(
    operation: Callable[[], T],
    operation_name: str,
    max_retries: int = DB_RETRY_MAX,
    retry_interval: float = DB_RETRY_INTERVAL_SECONDS,
) -> T:
    """DB 작업을 재시도 로직으로 감싸서 실행한다.

    Args:
        operation: 실행할 DB 작업 (callable).
        operation_name: 작업 설명 (로깅용).
        max_retries: 최대 재시도 횟수. 기본 3회.
        retry_interval: 재시도 간격(초). 기본 5초.

    Returns:
        operation의 반환값.

    Raises:
        Exception: 모든 재시도 실패 시 마지막 예외를 전파한다.

    Validates: Requirements 6.3
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = operation()
            return result
        except Exception as e:
            last_error = e
            logger.warning(
                "DB 작업 실패 (시도 %d/%d) [%s]: %s",
                attempt,
                max_retries,
                operation_name,
                str(e),
            )
            if attempt < max_retries:
                time.sleep(retry_interval)

    logger.error(
        "DB 작업 최종 실패 [%s]: %s",
        operation_name,
        str(last_error),
    )
    raise last_error  # type: ignore[misc]
