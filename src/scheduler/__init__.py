"""GitHub Actions에서 호출하는 수집 파이프라인."""

from src.scheduler.jobs import crawl_and_post

__all__ = ["crawl_and_post"]
