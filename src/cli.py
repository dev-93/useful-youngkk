"""CLI 엔트리포인트.

GitHub Actions에서 전체 파이프라인을 실행한다.

사용법:
    python -m src.cli crawl   # 크롤링 + 포스팅 + 노션 등록 + 상태 업데이트 + 리마인더
    python -m src.cli test    # 크롤링 테스트 (포스팅 안 함, 봇 DM으로 리포트)
"""

import asyncio
import logging
import sys

from src.config import load_settings, setup_logging
from src.db import init_db
from src.scheduler.jobs import crawl_and_post

logger = logging.getLogger(__name__)


async def run_test(settings) -> None:
    """크롤링 테스트 — 수집 결과를 채널이 아닌 봇 DM으로 리포트."""
    from src.crawler import SHCrawler, LHCrawler, run_with_retry
    from src.crawler.applyhome_crawler import ApplyHomeAPIClient
    from src.db import get_session
    from src.notifier.telegram import TelegramNotifier

    session = get_session()
    notifier = TelegramNotifier(
        bot_token=settings.telegram.bot_token,
        channel_id=settings.telegram.channel_id,
        admin_chat_id=settings.telegram.admin_chat_id,
    )

    report_lines = ["🧪 *크롤링 테스트 리포트*", ""]

    # SH 테스트
    try:
        sh_crawler = SHCrawler(session)
        html = sh_crawler.fetch_list()
        items = sh_crawler.parse_list(html)
        report_lines.append(f"📌 *SH공사*: {len(items)}건 수집")
        for item in items[:5]:
            report_lines.append(f"  • {item.title[:40]}")
        if not items:
            report_lines.append("  ⚠️ 수집된 공고 없음")
    except Exception as e:
        report_lines.append(f"📌 *SH공사*: ❌ 실패 - {str(e)[:50]}")

    report_lines.append("")

    # LH 테스트
    try:
        lh_crawler = LHCrawler(session)
        html = lh_crawler.fetch_list()
        items = lh_crawler.parse_list(html)
        report_lines.append(f"📌 *LH공사*: {len(items)}건 수집 (서울)")
        for item in items[:5]:
            ht = item.extra.get("housing_type", "")
            report_lines.append(f"  • [{ht}] {item.title[:35]}")
        if not items:
            report_lines.append("  ⚠️ 서울 공고 없음 (정상일 수 있음)")
    except Exception as e:
        report_lines.append(f"📌 *LH공사*: ❌ 실패 - {str(e)[:50]}")

    report_lines.append("")

    # 청약홈 API 테스트
    if settings.public_data_api_key:
        try:
            api_client = ApplyHomeAPIClient(api_key=settings.public_data_api_key)
            announcements = api_client.fetch_recent_announcements(days_back=30)
            report_lines.append(f"📌 *청약홈 API*: {len(announcements)}건 수집 (서울)")
            for ann in announcements[:5]:
                report_lines.append(f"  • [{ann.housing_type}] {ann.title[:30]}")
            if not announcements:
                report_lines.append("  ⚠️ 서울 공고 없음")
        except Exception as e:
            report_lines.append(f"📌 *청약홈 API*: ❌ 실패 - {str(e)[:50]}")
    else:
        report_lines.append("📌 *청약홈 API*: ⏭️ API 키 미설정")

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("포스팅 안 함 (테스트 모드)")

    message = "\n".join(report_lines)

    # 봇 DM으로 전송
    await notifier.send_admin_notification(message)
    logger.info("테스트 리포트 전송 완료")
    print(message)

    session.close()


def main() -> None:
    """CLI 진입점."""
    if len(sys.argv) < 2:
        print("사용법: python -m src.cli <command>")
        print("  crawl — 크롤링 + 포스팅 + 노션 등록 + 상태 업데이트 + 리마인더")
        print("  test  — 크롤링 테스트 (봇 DM으로 리포트, 포스팅 안 함)")
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
    elif command == "test":
        asyncio.run(run_test(settings))
    else:
        print(f"알 수 없는 명령: {command}")
        sys.exit(1)

    logger.info("CLI 완료: %s", command)


if __name__ == "__main__":
    main()
