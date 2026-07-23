"""스케줄 작업 정의.

APScheduler에서 실행되는 크롤링, 포스팅, 주간 요약, 리마인더 작업을 정의한다.

Validates: Requirements 1.1, 2.4, 5.1, 5.4, 6.3
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.calendar.notion_client import NotionCalendarManager
from src.crawler import ApplyHomeAPIClient, LHCrawler, SHCrawler, run_with_retry
from src.db import get_session
from src.db.repository import AnnouncementRepository
from src.notifier.admin import (
    create_notifier,
    notify_crawl_failure,
    notify_db_save_failure,
    notify_job_failure,
    notify_notion_failure,
    retry_db_operation,
)
from src.notifier.telegram import TelegramNotifier
from src.notifier.weekly_summary import WeeklySummaryGenerator

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


async def crawl_and_post(settings: Settings) -> None:
    """크롤링 → 포스팅 → 노션 등록 파이프라인.

    SH, LH, MyHome 순차 크롤링 후 새 공고를 텔레그램에 포스팅하고
    노션 DB에 등록한다. 각 단계 실패 시 관리자에게 알림을 전송한다.

    Args:
        settings: 애플리케이션 설정.

    Validates: Requirements 1.1, 2.4, 6.3
    """
    session = get_session()
    notifier = create_notifier(settings)

    try:
        # 크롤러 순차 실행 (HTML 크롤링)
        crawlers = [
            SHCrawler(session),
            LHCrawler(session),
        ]

        # 노션 DB에서 기존 공고 ID 가져오기 (중복 방지)
        calendar_manager = NotionCalendarManager(
            api_key=settings.notion.access_token,
            database_id=settings.notion.database_id,
            data_source_id=settings.notion.data_source_id,
            calendar_share_url=settings.notion.calendar_share_url,
        )
        try:
            existing_ids = calendar_manager.get_existing_source_ids()
        except Exception as e:
            logger.warning("노션 기존 공고 조회 실패, 중복 체크 없이 진행: %s", str(e))
            existing_ids = set()

        new_announcements = []

        for crawler in crawlers:
            try:
                crawl_log = run_with_retry(crawler, retry_interval=30, max_retries=2)
                if crawl_log.status == "failed":
                    # 3회 재시도 모두 실패 → 관리자 알림
                    await notify_crawl_failure(
                        notifier,
                        source_site=crawler.source_site,
                        error=crawl_log.error_message or "알 수 없는 오류",
                    )
                elif crawl_log.status == "success" and crawl_log.new_count > 0:
                    # 새로 수집된 공고 가져오기
                    repo = AnnouncementRepository(session)
                    active = repo.get_active()
                    # 노션에 이미 등록된 건 제외
                    for ann in active:
                        source_key = f"{ann.source_site}:{ann.source_id}"
                        if source_key not in existing_ids and ann not in new_announcements:
                            new_announcements.append(ann)
            except Exception as e:
                logger.error("[%s] 크롤링 실패: %s", crawler.source_site, str(e))
                await notify_crawl_failure(
                    notifier,
                    source_site=crawler.source_site,
                    error=str(e),
                )
                continue

        # 청약홈 API (민간분양) 수집
        if settings.public_data_api_key:
            try:
                api_client = ApplyHomeAPIClient(api_key=settings.public_data_api_key)
                api_announcements = api_client.fetch_recent_announcements(days_back=7)
                repo = AnnouncementRepository(session)
                for data in api_announcements:
                    source_key = f"{data.source_site}:{data.source_id}"
                    if source_key in existing_ids:
                        continue
                    if not repo.exists(data.source_site, data.source_id):
                        from src.db.models import Announcement

                        ann = Announcement(
                            source_site=data.source_site,
                            source_id=data.source_id,
                            title=data.title,
                            announcement_category=data.announcement_category,
                            housing_type=data.housing_type,
                            start_date=data.start_date,
                            end_date=data.end_date,
                            result_date=data.result_date,
                            target_region=data.target_region,
                            eligibility_age=data.eligibility_age,
                            eligibility_income=data.eligibility_income,
                            eligibility_homeless=data.eligibility_homeless,
                            eligibility_residence=data.eligibility_residence,
                            original_url=data.original_url,
                            status="active",
                        )
                        repo.create(ann)
                        new_announcements.append(ann)
                logger.info("[applyhome] API 수집 완료: 신규 %d건", len([a for a in new_announcements if a.source_site == "applyhome"]))
            except Exception as e:
                logger.error("[applyhome] API 수집 실패: %s", str(e))

        if not new_announcements:
            logger.info("새 공고 없음, 포스팅 건너뜀")
            # DB 커밋도 재시도 로직 적용
            try:
                retry_db_operation(
                    operation=session.commit,
                    operation_name="crawl_and_post 최종 커밋",
                )
            except Exception as e:
                await notify_db_save_failure(
                    notifier,
                    operation="crawl_and_post 최종 커밋",
                    error=str(e),
                )
            return

        # 텔레그램 포스팅 및 노션 등록
        repo = AnnouncementRepository(session)

        # Gemini로 자격요건 보충 (누락된 항목이 있는 경우)
        if settings.gemini_api_key:
            from src.ai.gemini_client import GeminiClient

            gemini = GeminiClient(api_key=settings.gemini_api_key)
            for announcement in new_announcements:
                if not announcement.eligibility_age and not announcement.eligibility_income:
                    try:
                        result = gemini.extract_eligibility(
                            title=announcement.title,
                            housing_type=announcement.housing_type,
                            detail_text=None,  # 상세 텍스트는 이미 파싱 단계에서 사용됨
                            region=announcement.target_region,
                        )
                        if result.age:
                            announcement.eligibility_age = f"{result.age} {'⚠️AI참고' if result.is_general_info else ''}"
                        if result.income:
                            announcement.eligibility_income = f"{result.income} {'⚠️AI참고' if result.is_general_info else ''}"
                        if result.homeless and not announcement.eligibility_homeless:
                            announcement.eligibility_homeless = f"{result.homeless} {'⚠️AI참고' if result.is_general_info else ''}"
                        if result.residence and not announcement.eligibility_residence:
                            announcement.eligibility_residence = f"{result.residence} {'⚠️AI참고' if result.is_general_info else ''}"
                        logger.info("Gemini 자격요건 보충: %s (confidence=%s)", announcement.title[:30], result.confidence)
                    except Exception as e:
                        logger.warning("Gemini 보충 실패: %s", str(e))

        for announcement in new_announcements:
            # 텔레그램 포스팅 (내부적으로 재시도 및 관리자 알림 처리됨)
            try:
                await notifier.send_new_announcement(announcement, session)
            except Exception as e:
                logger.error(
                    "포스팅 실패: announcement_id=%d, error=%s",
                    announcement.id,
                    str(e),
                )

            # 노션 페이지 생성
            try:
                page_id = calendar_manager.create_page(announcement)
                repo.update_notion_page_id(announcement.id, page_id)
            except Exception as e:
                logger.error(
                    "노션 등록 실패: announcement_id=%d, error=%s",
                    announcement.id,
                    str(e),
                )
                await notify_notion_failure(
                    notifier,
                    announcement_id=announcement.id,
                    error=str(e),
                )

        # DB 커밋 (재시도 로직 적용)
        try:
            retry_db_operation(
                operation=session.commit,
                operation_name="crawl_and_post 최종 커밋",
            )
        except Exception as e:
            session.rollback()
            await notify_db_save_failure(
                notifier,
                operation="crawl_and_post 최종 커밋",
                error=str(e),
            )
            raise

        logger.info("크롤링→포스팅→노션 파이프라인 완료: %d건 처리", len(new_announcements))

    except Exception as e:
        session.rollback()
        logger.error("crawl_and_post 작업 실패: %s", str(e))
        await notify_job_failure(notifier, job_name="crawl_and_post", error=str(e))
        raise
    finally:
        session.close()

    # 노션 상태 업데이트 + 마감 리마인더 (crawl_and_post 안에서 함께 실행)
    try:
        from src.notifier.formatter import escape_markdown_v2

        # 마감일 경과 공고 상태 → "마감"
        expired_pages = calendar_manager.query_expired_active()
        updated_count = 0
        for page in expired_pages:
            try:
                calendar_manager.update_status(page["page_id"], "마감")
                updated_count += 1
            except Exception as e:
                logger.error("노션 상태 업데이트 실패: page_id=%s, error=%s", page["page_id"], str(e))
        if updated_count:
            logger.info("노션 마감 상태 업데이트: %d건", updated_count)

        # 내일 마감 리마인더
        tomorrow_deadlines = calendar_manager.query_tomorrow_deadlines()
        if tomorrow_deadlines:
            lines = ["⏰ *내일 마감 청약 공고*", ""]
            for item in tomorrow_deadlines:
                title = escape_markdown_v2(item["title"])
                end_date = escape_markdown_v2(item["end_date"] or "")
                lines.append(f"• *{title}* \\({end_date} 마감\\)")
                if item.get("url"):
                    lines.append(f"  🔗 [원문 보기]({item['url']})")
            lines.append("")
            lines.append(f"📅 [전체 일정 보기]({settings.notion.calendar_share_url})")
            message = "\n".join(lines)
            await notifier.send_channel_message(message)
            logger.info("마감 리마인더 포스팅: %d건", len(tomorrow_deadlines))

    except Exception as e:
        logger.error("상태 업데이트/리마인더 실패: %s", str(e))


async def weekly_summary_job(settings: Settings) -> None:
    """주간 요약 포스팅 작업.

    노션 DB에서 이번 주 마감 예정 공고를 조회하여
    텔레그램 채널에 포스팅한다.

    Args:
        settings: 애플리케이션 설정.

    Validates: Requirements 5.1
    """
    notifier = create_notifier(settings)

    try:
        calendar_manager = NotionCalendarManager(
            api_key=settings.notion.access_token,
            database_id=settings.notion.database_id,
            data_source_id=settings.notion.data_source_id,
            calendar_share_url=settings.notion.calendar_share_url,
        )

        weekly_deadlines = calendar_manager.query_weekly_deadlines()

        from src.notifier.formatter import escape_markdown_v2

        if weekly_deadlines:
            lines = ["📅 *이번 주 마감 예정 청약*", ""]
            for item in weekly_deadlines:
                title = escape_markdown_v2(item["title"])
                end_date = escape_markdown_v2(item["end_date"] or "")
                housing_type = escape_markdown_v2(item.get("housing_type") or "")
                type_str = f" \\({housing_type}\\)" if housing_type else ""
                lines.append(f"• *{title}*{type_str}")
                lines.append(f"  마감: {end_date}")
            lines.append("")
            lines.append(f"📅 [전체 일정 보기]({settings.notion.calendar_share_url})")
            message = "\n".join(lines)
        else:
            message = "📅 *이번 주 마감 예정 청약*\n\n이번 주 마감 예정 청약이 없습니다\\."

        await notifier.send_channel_message(message)
        logger.info("주간 요약 포스팅 완료: %d건 포함", len(weekly_deadlines))

    except Exception as e:
        logger.error("weekly_summary_job 작업 실패: %s", str(e))
        await notify_job_failure(
            notifier, job_name="weekly_summary_job", error=str(e)
        )
        raise


async def reminder_job(settings: Settings) -> None:
    """마감 리마인더 + 노션 상태 업데이트 작업.

    노션 DB에서 직접 내일 마감 공고를 조회하여 텔레그램에 포스팅하고,
    마감일이 경과한 공고의 상태를 "마감"으로 변경한다.

    Args:
        settings: 애플리케이션 설정.

    Validates: Requirements 5.4, 4.3
    """
    notifier = create_notifier(settings)

    try:
        calendar_manager = NotionCalendarManager(
            api_key=settings.notion.access_token,
            database_id=settings.notion.database_id,
            data_source_id=settings.notion.data_source_id,
            calendar_share_url=settings.notion.calendar_share_url,
        )

        # 1. 내일 마감 리마인더 (노션 DB 직접 조회)
        tomorrow_deadlines = calendar_manager.query_tomorrow_deadlines()
        if tomorrow_deadlines:
            from src.notifier.formatter import escape_markdown_v2

            lines = ["⏰ *내일 마감 청약 공고*", ""]
            for item in tomorrow_deadlines:
                title = escape_markdown_v2(item["title"])
                end_date = escape_markdown_v2(item["end_date"] or "")
                lines.append(f"• *{title}* \\({end_date} 마감\\)")
                if item.get("url"):
                    lines.append(f"  🔗 [원문 보기]({item['url']})")
            lines.append("")
            lines.append(f"📅 [전체 일정 보기]({settings.notion.calendar_share_url})")

            message = "\n".join(lines)
            await notifier.send_channel_message(message)
            logger.info("마감 리마인더 포스팅 완료: %d건", len(tomorrow_deadlines))
        else:
            logger.info("내일 마감 공고 없음 — 리마인더 미발송")

        # 2. 마감일 경과 공고 상태 업데이트 (노션 DB 직접 조회 + 업데이트)
        expired_pages = calendar_manager.query_expired_active()
        updated_count = 0
        for page in expired_pages:
            try:
                calendar_manager.update_status(page["page_id"], "마감")
                updated_count += 1
            except Exception as e:
                logger.error("노션 상태 업데이트 실패: page_id=%s, error=%s", page["page_id"], str(e))

        if updated_count:
            logger.info("노션 마감 상태 업데이트: %d건", updated_count)

        logger.info("reminder_job 작업 완료")

    except Exception as e:
        logger.error("reminder_job 작업 실패: %s", str(e))
        await notify_job_failure(notifier, job_name="reminder_job", error=str(e))
        raise


async def notify_admin_error_simple(
    notifier: TelegramNotifier, error_type: str, error_detail: str
) -> None:
    """간단한 관리자 오류 알림 전송 헬퍼."""
    from src.notifier.admin import notify_admin_error

    await notify_admin_error(notifier, error_type, error_detail)
