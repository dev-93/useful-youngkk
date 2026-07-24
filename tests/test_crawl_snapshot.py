"""크롤링 스냅샷 테스트.

실제 사이트 HTML 구조가 변경되면 이 테스트가 실패하여 감지한다.
URL 변경, 테이블 구조 변경, 필터링 로직 검증.

※ 이 테스트는 실제 네트워크 요청을 하므로 CI에서는 별도 실행.
   pytest -m snapshot
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.crawler.sh_crawler import SHCrawler
from src.crawler.lh_crawler import LHCrawler
from src.db.models import Base


@pytest.fixture
def db_session():
    """스냅샷 테스트용 임시 DB 세션."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.mark.snapshot
class TestSHCrawlerSnapshot:
    """SH공사 사이트 구조 스냅샷 테스트."""

    def test_list_page_accessible(self, db_session):
        """SH 목록 페이지에 접근 가능하다."""
        crawler = SHCrawler(db_session)
        html = crawler.fetch_list()
        assert len(html) > 1000
        assert "주택임대" in html or "SH" in html or "sh" in html

    def test_list_page_has_table(self, db_session):
        """SH 목록 페이지에 데이터 테이블이 있다."""
        crawler = SHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        # 최소 0건 이상 파싱 가능해야 (빈 결과도 구조는 정상)
        assert isinstance(items, list)

    def test_parse_produces_valid_items(self, db_session):
        """파싱된 항목이 올바른 구조를 가진다."""
        crawler = SHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            assert item.source_id.isdigit(), f"source_id가 숫자가 아님: {item.source_id}"
            assert len(item.title) > 5, f"제목이 너무 짧음: {item.title}"
            assert "모집" in item.title, f"모집공고 필터 실패: {item.title}"

    def test_filter_excludes_non_recruitment(self, db_session):
        """당첨자 발표, 서류제출 등이 필터링된다."""
        crawler = SHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            assert "당첨자 발표" not in item.title
            assert "당첨자발표" not in item.title
            assert "서류제출" not in item.title
            assert "계약안내" not in item.title


@pytest.mark.snapshot
class TestLHCrawlerSnapshot:
    """LH공사 사이트 구조 스냅샷 테스트."""

    def test_list_page_accessible(self, db_session):
        """LH 목록 페이지에 접근 가능하다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        assert len(html) > 1000
        assert "임대주택" in html or "LH" in html or "공고문" in html

    def test_list_page_has_table(self, db_session):
        """LH 목록 페이지에 테이블이 있다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        assert isinstance(items, list)

    def test_items_are_seoul_only(self, db_session):
        """파싱된 항목이 모두 서울 지역이다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            region = item.extra.get("region", "")
            assert "서울" in region, f"서울이 아닌 공고 포함: {region} - {item.title}"

    def test_items_exclude_irrelevant_types(self, db_session):
        """영구임대, 집주인임대, 가정어린이집이 제외된다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            ht = item.extra.get("housing_type", "")
            assert ht not in ("영구임대", "집주인임대", "가정어린이집"), f"제외 유형 포함: {ht}"

    def test_items_have_valid_source_id(self, db_session):
        """source_id(panId)가 유효하다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            assert len(item.source_id) > 5, f"source_id가 너무 짧음: {item.source_id}"

    def test_items_are_active(self, db_session):
        """수집된 공고가 진행중 상태인지 확인한다."""
        crawler = LHCrawler(db_session)
        html = crawler.fetch_list()
        items = crawler.parse_list(html)
        for item in items:
            status = item.extra.get("status", "")
            # 공고중 또는 접수중이어야 함 (마감은 제외되어야)
            assert status in ("공고중", "접수중", ""), f"마감된 공고 포함: {status} - {item.title}"
