"""CLI 엔트리포인트.

GitHub Actions에서 전체 파이프라인을 실행한다.

사용법:
    python -m src.cli crawl   # 크롤링 + 포스팅 + 노션 등록 + 상태 업데이트 + 리마인더
"""

import asyncio
import logging
import sys

from src.config import load_settings, setup_logging
from src.db import init_db
from src.scheduler.jobs import crawl_and_post

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI 진입점."""
    if len(sys.argv) < 2:
        print("사용법: python -m src.cli <command>")
        print("  crawl — 크롤링 + 포스팅 + 노션 등록 + 상태 업데이트 + 리마인더")
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
    else:
        print(f"알 수 없는 명령: {command}")
        sys.exit(1)

    logger.info("CLI 완료: %s", command)


if __name__ == "__main__":
    main()
