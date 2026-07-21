"""서울 청년 주거 정보 텔레그램 봇 진입점.

APScheduler를 초기화하고, 크롤링·포스팅·주간 요약·리마인더 작업을 등록한 뒤
asyncio 이벤트 루프에서 스케줄러를 실행한다.
"""

import asyncio
import logging
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import Settings, load_settings, setup_logging
from src.db import init_db
from src.scheduler.jobs import crawl_and_post, reminder_job, weekly_summary_job

logger = logging.getLogger(__name__)


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    """APScheduler를 생성하고 작업을 등록한다.

    Args:
        settings: 애플리케이션 설정.

    Returns:
        설정이 완료된 AsyncIOScheduler 인스턴스.
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # 평일 크롤링 작업 (예: 11시, 17시)
    for hour in settings.scheduler.crawl_hours:
        scheduler.add_job(
            crawl_and_post,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=0,
                timezone="Asia/Seoul",
            ),
            args=[settings],
            id=f"crawl_and_post_{hour:02d}",
            name=f"크롤링+포스팅 (매 평일 {hour}시)",
            replace_existing=True,
        )

    # 주간 요약 (매주 월요일 09시)
    scheduler.add_job(
        weekly_summary_job,
        trigger=CronTrigger(
            day_of_week=settings.scheduler.weekly_summary_day,
            hour=settings.scheduler.weekly_summary_hour,
            minute=0,
            timezone="Asia/Seoul",
        ),
        args=[settings],
        id="weekly_summary",
        name="주간 요약 포스팅 (매주 월요일 9시)",
        replace_existing=True,
    )

    # 마감 리마인더 + 상태 업데이트 (매일 09시)
    scheduler.add_job(
        reminder_job,
        trigger=CronTrigger(
            hour=9,
            minute=0,
            timezone="Asia/Seoul",
        ),
        args=[settings],
        id="reminder",
        name="마감 리마인더 + 노션 상태 업데이트 (매일 9시)",
        replace_existing=True,
    )

    return scheduler


def main() -> None:
    """애플리케이션을 시작한다."""
    # 1. 설정 로드
    settings = load_settings()

    # 2. 로깅 설정
    setup_logging(settings.logging)

    logger.info("서울 청년 주거 정보 텔레그램 봇 시작")

    # 3. DB 초기화
    init_db(settings.database.url)

    # 4. 스케줄러 생성 및 작업 등록
    scheduler = create_scheduler(settings)

    # 5. 스케줄러 시작
    scheduler.start()
    logger.info("스케줄러 시작 완료 — 등록된 작업: %d개", len(scheduler.get_jobs()))

    for job in scheduler.get_jobs():
        logger.info("  [%s] %s → 다음 실행: %s", job.id, job.name, job.next_run_time)

    # 6. 이벤트 루프 실행
    loop = asyncio.get_event_loop()

    def shutdown(signum, frame):
        logger.info("종료 신호 수신 (signal=%d), 스케줄러 종료 중...", signum)
        scheduler.shutdown(wait=False)
        loop.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("서울 청년 주거 정보 텔레그램 봇 종료")


if __name__ == "__main__":
    main()
