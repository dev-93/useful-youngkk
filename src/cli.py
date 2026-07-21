"""CLI 엔트리포인트.

GitHub Actions 등에서 개별 작업을 실행할 수 있도록 CLI 명령을 제공한다.

사용법:
    python -m src.cli crawl       # 크롤링 + 포스팅 + 노션 등록
    python -m src.cli weekly      # 주간 요약 포스팅
    python -m src.cli reminder    # 마감 리마인더 + 노션 상태 업데이트
"""

import asyncio
import logging
import sys

from src.config import load_settings, setup_logging
from src.db import init_db
from src.scheduler.jobs import crawl_and_post, reminder_job, weekly_summary_job

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI 진입점."""
    if len(sys.argv) < 2:
        print("사용법: python -m src.cli <command>")
        print("  crawl     — 크롤링 + 텔레그램 포스팅 + 노션 등록")
        print("  weekly    — 주간 요약 포스팅")
        print("  reminder  — 마감 리마인더 + 노션 상태 업데이트")
        sys.exit(1)

    command = sys.argv[1]

    # 설정 로드
    settings = load_settings()
    setup_logging(settings.logging)

    # DB 초기화
    init_db(settings.database.url)

    logger.info("CLI 실행: %s", command)

    if command == "crawl":
        asyncio.run(crawl_and_post(settings))
    elif command == "weekly":
        asyncio.run(weekly_summary_job(settings))
    elif command == "reminder":
        asyncio.run(reminder_job(settings))
    else:
        print(f"알 수 없는 명령: {command}")
        sys.exit(1)

    logger.info("CLI 완료: %s", command)


if __name__ == "__main__":
    main()
