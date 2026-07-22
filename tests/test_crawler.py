"""크롤러 모듈 테스트.

BaseCrawler, SHCrawler, LHCrawler, MyHomeCrawler, parser 유틸리티, 재시도 로직을 테스트한다.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.crawler.base import (
    AnnouncementData,
    BaseCrawler,
    ListItem,
    run_with_retry,
)
from src.crawler.lh_crawler import LHCrawler
from src.crawler.myhome_crawler import MyHomeCrawler
from src.crawler.parser import EligibilityInfo, parse_date, parse_eligibility
from src.crawler.sh_crawler import SHCrawler
from src.db.models import Announcement, Base, CrawlLog


# ──────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """인메모리 SQLite DB 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    yield session
    session.close()


class ConcreteCrawler(BaseCrawler):
    """테스트용 구체 크롤러."""

    source_site = "test"

    def __init__(self, session, list_html="", detail_html="", should_fail=False):
        super().__init__(session)
        self._list_html = list_html
        self._detail_html = detail_html
        self._should_fail = should_fail

    def fetch_list(self) -> str:
        if self._should_fail:
            raise ConnectionError("네트워크 오류")
        return self._list_html

    def parse_list(self, html: str) -> list[ListItem]:
        return [
            ListItem(source_id="1", title="테스트 공고", detail_url="http://example.com/1"),
        ]

    def fetch_detail(self, item: ListItem) -> str:
        return self._detail_html

    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        return AnnouncementData(
            source_site=self.source_site,
            source_id=item.source_id,
            title=item.title,
            housing_type="행복주택",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
            original_url=item.detail_url,
        )


# ──────────────────────────────────────────────────────────
# Parser Tests
# ──────────────────────────────────────────────────────────


class TestParseDate:
    """날짜 파싱 테스트."""

    def test_dot_format(self):
        assert parse_date("2024.06.15") == date(2024, 6, 15)

    def test_dash_format(self):
        assert parse_date("2024-06-15") == date(2024, 6, 15)

    def test_slash_format(self):
        assert parse_date("2024/06/15") == date(2024, 6, 15)

    def test_korean_format(self):
        assert parse_date("2024년 6월 15일") == date(2024, 6, 15)

    def test_empty_string(self):
        assert parse_date("") is None

    def test_none_like(self):
        assert parse_date("   ") is None

    def test_invalid_date(self):
        assert parse_date("2024.13.45") is None


class TestParseEligibility:
    """자격요건 파싱 테스트."""

    def test_age_range(self):
        text = "입주자격: 만 19세 이상 ~ 만 39세 이하인 자"
        result = parse_eligibility(text)
        assert result.age is not None
        assert "19" in result.age
        assert "39" in result.age

    def test_income(self):
        text = "도시근로자 월평균 소득 100% 이하"
        result = parse_eligibility(text)
        assert result.income is not None
        assert "100" in result.income

    def test_income_median(self):
        text = "기준 중위소득 150% 이하에 해당하는 자"
        result = parse_eligibility(text)
        assert result.income is not None
        assert "150" in result.income

    def test_homeless(self):
        text = "무주택 세대구성원으로서 주택을 소유하지 않은 자"
        result = parse_eligibility(text)
        assert result.homeless is not None
        assert "무주택" in result.homeless

    def test_residence_period(self):
        text = "서울 거주 1년 이상인 자"
        result = parse_eligibility(text)
        assert result.residence_period is not None
        assert "1" in result.residence_period

    def test_all_missing(self):
        text = "일반적인 텍스트입니다."
        result = parse_eligibility(text)
        assert result.age is None
        assert result.income is None
        assert result.homeless is None
        assert result.residence_period is None

    def test_combined_text(self):
        text = """
        입주자격
        - 만 19세 이상 39세 이하
        - 도시근로자 월평균 소득 100% 이하
        - 무주택 세대구성원
        - 서울 거주 1년 이상
        """
        result = parse_eligibility(text)
        assert result.age is not None
        assert result.income is not None
        assert result.homeless is not None
        assert result.residence_period is not None


# ──────────────────────────────────────────────────────────
# BaseCrawler Tests
# ──────────────────────────────────────────────────────────


class TestBaseCrawlerSave:
    """BaseCrawler.save() 메서드 테스트."""

    def test_save_new_announcement(self, db_session):
        """새 공고를 성공적으로 저장한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="123",
            title="테스트 공고",
            housing_type="행복주택",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
            original_url="http://example.com/123",
        )
        result = crawler.save(data)
        assert result is not None
        assert result.title == "테스트 공고"
        assert result.status == "active"

    def test_save_duplicate_returns_none(self, db_session):
        """중복 공고 저장 시 None을 반환한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="123",
            title="테스트 공고",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
        )
        crawler.save(data)
        db_session.commit()
        result = crawler.save(data)
        assert result is None

    def test_save_incomplete_no_title(self, db_session):
        """공고명 누락 시 불완전 상태로 저장한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="456",
            title="",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
        )
        result = crawler.save(data)
        assert result is not None
        assert result.status == "incomplete"

    def test_save_incomplete_no_dates(self, db_session):
        """모집 기간(시작일, 마감일 모두) 누락 시 불완전 상태로 저장한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="789",
            title="기간 없는 공고",
            start_date=None,
            end_date=None,
        )
        result = crawler.save(data)
        assert result is not None
        assert result.status == "incomplete"

    def test_save_incomplete_no_start_date(self, db_session):
        """시작일만 누락 시 불완전 상태로 저장한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="101",
            title="시작일 없는 공고",
            start_date=None,
            end_date=date(2024, 6, 30),
        )
        result = crawler.save(data)
        assert result is not None
        assert result.status == "incomplete"

    def test_save_incomplete_no_end_date(self, db_session):
        """마감일만 누락 시 불완전 상태로 저장한다."""
        crawler = ConcreteCrawler(db_session)
        data = AnnouncementData(
            source_site="test",
            source_id="102",
            title="마감일 없는 공고",
            start_date=date(2024, 6, 1),
            end_date=None,
        )
        result = crawler.save(data)
        assert result is not None
        assert result.status == "incomplete"


class TestBaseCrawlerRun:
    """BaseCrawler.run() 메서드 테스트."""

    def test_run_success(self, db_session):
        """정상 실행 시 신규 공고 수를 반환한다."""
        crawler = ConcreteCrawler(db_session)
        count = crawler.run()
        assert count == 1

    def test_run_skips_duplicates(self, db_session):
        """중복 공고는 건너뛴다."""
        crawler = ConcreteCrawler(db_session)
        # 먼저 한 번 실행하여 데이터 저장
        crawler.run()
        db_session.commit()
        # 두 번째 실행 시 중복이므로 0건
        count = crawler.run()
        assert count == 0


# ──────────────────────────────────────────────────────────
# Retry Logic Tests
# ──────────────────────────────────────────────────────────


class TestRunWithRetry:
    """run_with_retry() 재시도 로직 테스트."""

    def test_success_first_attempt(self, db_session):
        """첫 시도에 성공하면 재시도 없이 완료한다."""
        crawler = ConcreteCrawler(db_session)
        log = run_with_retry(crawler, retry_interval=0, max_retries=3)
        assert log.status == "success"
        assert log.retry_count == 0
        assert log.new_count == 1

    def test_failure_then_success(self, db_session):
        """실패 후 재시도에서 성공한다."""
        crawler = ConcreteCrawler(db_session, should_fail=True)
        call_count = 0
        original_fetch = crawler.fetch_list

        def fetch_with_failure():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ConnectionError("첫 시도 실패")
            crawler._should_fail = False
            return ""

        crawler.fetch_list = fetch_with_failure
        log = run_with_retry(crawler, retry_interval=0, max_retries=3)
        assert log.status == "success"
        assert log.retry_count == 1

    def test_all_retries_fail(self, db_session):
        """모든 재시도가 실패하면 failed 상태를 기록한다."""
        crawler = ConcreteCrawler(db_session, should_fail=True)
        log = run_with_retry(crawler, retry_interval=0, max_retries=3)
        assert log.status == "failed"
        assert log.retry_count == 3
        assert log.error_message is not None

    def test_crawl_log_created(self, db_session):
        """크롤링 로그가 DB에 기록된다."""
        crawler = ConcreteCrawler(db_session)
        log = run_with_retry(crawler, retry_interval=0, max_retries=3)
        assert log.id is not None
        assert log.source_site == "test"
        assert log.started_at is not None
        assert log.finished_at is not None


# ──────────────────────────────────────────────────────────
# SH Crawler Tests
# ──────────────────────────────────────────────────────────


SAMPLE_SH_LIST_HTML = """
<html>
<body>
<table>
<tr><th>검색</th><td>검색폼</td></tr>
</table>
<table>
<tr><th>번호</th><th>제목</th><th>담당부서</th><th>등록일</th><th>조회수</th></tr>
<tr>
    <td>100</td>
    <td><a href="#" onclick="javascript:getDetailView('12345');return false;">2024년 행복주택 입주자 모집공고</a></td>
    <td>맞춤주택공급부</td>
    <td>2024-06-01</td>
    <td>100</td>
</tr>
<tr>
    <td>99</td>
    <td><a href="#" onclick="javascript:getDetailView('12346');return false;">2024년 공공임대 입주자 모집공고</a></td>
    <td>매입주택공급부</td>
    <td>2024-05-15</td>
    <td>200</td>
</tr>
</table>
</body>
</html>
"""

SAMPLE_SH_DETAIL_HTML = """
<html>
<body>
<div class="contents">
    <h3>2024년 행복주택 입주자 모집공고</h3>
    <table>
        <tr><th>모집기간</th><td>2024.06.01 ~ 2024.06.30</td></tr>
        <tr><th>모집유형</th><td>행복주택</td></tr>
        <tr><th>대상지역</th><td>서울특별시 강남구</td></tr>
    </table>
    <div class="content">
        <p>입주자격</p>
        <p>- 만 19세 이상 39세 이하인 청년</p>
        <p>- 도시근로자 월평균 소득 100% 이하</p>
        <p>- 무주택 세대구성원</p>
        <p>- 서울 거주 1년 이상</p>
        <p>당첨자 발표일: 2024.07.15</p>
    </div>
</div>
</body>
</html>
"""


class TestSHCrawlerParseList:
    """SHCrawler.parse_list() 테스트."""

    def test_parse_list_items(self, db_session):
        """목록 페이지에서 공고 항목을 파싱한다."""
        crawler = SHCrawler(db_session)
        items = crawler.parse_list(SAMPLE_SH_LIST_HTML)
        assert len(items) == 2
        assert items[0].source_id == "12345"
        assert items[0].title == "2024년 행복주택 입주자 모집공고"
        assert items[1].source_id == "12346"

    def test_parse_list_empty_table(self, db_session):
        """빈 테이블이면 빈 리스트를 반환한다."""
        crawler = SHCrawler(db_session)
        items = crawler.parse_list("<html><body><table><tbody></tbody></table></body></html>")
        assert items == []


class TestSHCrawlerParseDetail:
    """SHCrawler.parse_detail() 테스트."""

    def test_parse_detail_full(self, db_session):
        """상세 페이지에서 모든 정보를 추출한다."""
        crawler = SHCrawler(db_session)
        item = ListItem(
            source_id="12345",
            title="2024년 행복주택 입주자 모집공고",
            detail_url="http://example.com/12345",
        )
        data = crawler.parse_detail(SAMPLE_SH_DETAIL_HTML, item)

        assert data.source_site == "sh"
        assert data.source_id == "12345"
        assert data.title == "2024년 행복주택 입주자 모집공고"
        assert data.housing_type == "행복주택"
        assert data.start_date == date(2024, 6, 1)
        assert data.end_date == date(2024, 6, 30)
        assert data.result_date == date(2024, 7, 15)
        assert data.target_region is not None
        assert "강남" in data.target_region
        assert data.eligibility_age is not None
        assert data.eligibility_income is not None
        assert data.eligibility_homeless is not None
        assert data.eligibility_residence is not None

    def test_parse_detail_minimal(self, db_session):
        """최소 HTML에서도 파싱이 동작한다."""
        crawler = SHCrawler(db_session)
        item = ListItem(
            source_id="99999",
            title="최소 공고",
            detail_url="http://example.com/99999",
        )
        html = "<html><body><div class='view_cont'>간단한 내용</div></body></html>"
        data = crawler.parse_detail(html, item)

        assert data.source_id == "99999"
        assert data.title == "최소 공고"
        # 정보 부족 시 None
        assert data.start_date is None
        assert data.end_date is None


class TestSHCrawlerIntegration:
    """SHCrawler 통합 테스트 (HTTP 모킹)."""

    def test_full_run_with_mock_client(self, db_session):
        """전체 크롤링 플로우를 모킹하여 테스트한다."""
        mock_client = MagicMock()

        # 목록 페이지 응답
        list_response = MagicMock()
        list_response.text = SAMPLE_SH_LIST_HTML
        list_response.raise_for_status = MagicMock()

        # 상세 페이지 응답
        detail_response = MagicMock()
        detail_response.text = SAMPLE_SH_DETAIL_HTML
        detail_response.raise_for_status = MagicMock()

        mock_client.get = MagicMock(side_effect=[list_response, detail_response, detail_response])

        crawler = SHCrawler(db_session, client=mock_client)
        count = crawler.run()

        assert count == 2
        # DB에 저장 확인
        db_session.commit()
        announcements = db_session.query(Announcement).all()
        assert len(announcements) == 2


# ──────────────────────────────────────────────────────────
# LH Crawler Tests
# ──────────────────────────────────────────────────────────


SAMPLE_LH_LIST_HTML = """
<html>
<body>
<table>
<tbody>
<tr>
    <td>1</td>
    <td><a href="/LH/contents/CON_02_02_01_view.do?not_sn=20240601">2024년 국민임대주택 입주자 모집공고</a></td>
    <td>2024.06.01</td>
    <td>150</td>
</tr>
<tr>
    <td>2</td>
    <td><a href="/LH/contents/CON_02_02_01_view.do?not_sn=20240602">2024년 행복주택 입주자 모집공고 (수도권)</a></td>
    <td>2024.05.20</td>
    <td>300</td>
</tr>
<tr>
    <td>3</td>
    <td><span>공지사항 (링크 없음)</span></td>
    <td>2024.05.10</td>
    <td>50</td>
</tr>
</tbody>
</table>
</body>
</html>
"""

SAMPLE_LH_DETAIL_HTML = """
<html>
<body>
<div class="view_cont">
    <h3>2024년 국민임대주택 입주자 모집공고</h3>
    <table>
        <tr><th>모집기간</th><td>2024.06.10 ~ 2024.06.25</td></tr>
        <tr><th>모집유형</th><td>국민임대</td></tr>
        <tr><th>공급위치</th><td>경기도 화성시</td></tr>
    </table>
    <div class="content">
        <p>입주자격</p>
        <p>- 만 19세 이상인 자</p>
        <p>- 도시근로자 월평균 소득 70% 이하</p>
        <p>- 무주택 세대구성원</p>
        <p>- 거주기간 2년 이상</p>
        <p>당첨자 발표일: 2024.07.10</p>
    </div>
</div>
</body>
</html>
"""

SAMPLE_LH_EMPTY_LIST_HTML = """
<html>
<body>
<table>
<tbody>
</tbody>
</table>
</body>
</html>
"""


class TestLHCrawlerParseList:
    """LHCrawler.parse_list() 테스트."""

    def test_parse_list_items(self, db_session):
        """목록 페이지에서 공고 항목을 파싱한다."""
        crawler = LHCrawler(db_session)
        items = crawler.parse_list(SAMPLE_LH_LIST_HTML)
        assert len(items) == 2
        assert items[0].source_id == "20240601"
        assert items[0].title == "2024년 국민임대주택 입주자 모집공고"
        assert items[1].source_id == "20240602"
        assert items[1].title == "2024년 행복주택 입주자 모집공고 (수도권)"

    def test_parse_list_empty_table(self, db_session):
        """빈 테이블이면 빈 리스트를 반환한다."""
        crawler = LHCrawler(db_session)
        items = crawler.parse_list(SAMPLE_LH_EMPTY_LIST_HTML)
        assert items == []

    def test_parse_list_skips_rows_without_links(self, db_session):
        """링크 없는 행은 건너뛴다."""
        crawler = LHCrawler(db_session)
        items = crawler.parse_list(SAMPLE_LH_LIST_HTML)
        # 3번째 행은 링크가 없으므로 2개만 파싱됨
        assert len(items) == 2

    def test_source_id_extraction_various_params(self, db_session):
        """다양한 URL 파라미터에서 source_id를 추출한다."""
        crawler = LHCrawler(db_session)
        # nttId 파라미터
        assert crawler._extract_source_id("?nttId=99999") == "99999"
        # seq 파라미터
        assert crawler._extract_source_id("?seq=12345") == "12345"
        # bbs_sn 파라미터
        assert crawler._extract_source_id("?bbs_sn=55555") == "55555"
        # pblancNo 파라미터
        assert crawler._extract_source_id("?pblancNo=ABC123") == "ABC123"
        # 파라미터 없는 경우
        assert crawler._extract_source_id("/some/path") is None


class TestLHCrawlerParseDetail:
    """LHCrawler.parse_detail() 테스트."""

    def test_parse_detail_full(self, db_session):
        """상세 페이지에서 모든 정보를 추출한다."""
        crawler = LHCrawler(db_session)
        item = ListItem(
            source_id="20240601",
            title="2024년 국민임대주택 입주자 모집공고",
            detail_url="https://www.lh.or.kr/LH/contents/CON_02_02_01_view.do?not_sn=20240601",
        )
        data = crawler.parse_detail(SAMPLE_LH_DETAIL_HTML, item)

        assert data.source_site == "lh"
        assert data.source_id == "20240601"
        assert data.title == "2024년 국민임대주택 입주자 모집공고"
        assert data.housing_type == "국민임대"
        assert data.start_date == date(2024, 6, 10)
        assert data.end_date == date(2024, 6, 25)
        assert data.result_date == date(2024, 7, 10)
        assert data.eligibility_age is not None
        assert data.eligibility_income is not None
        assert data.eligibility_homeless is not None
        assert data.eligibility_residence is not None

    def test_parse_detail_minimal(self, db_session):
        """최소 HTML에서도 파싱이 동작한다."""
        crawler = LHCrawler(db_session)
        item = ListItem(
            source_id="88888",
            title="최소 공고",
            detail_url="http://example.com/88888",
        )
        html = "<html><body><div class='view_cont'>간단한 내용</div></body></html>"
        data = crawler.parse_detail(html, item)

        assert data.source_site == "lh"
        assert data.source_id == "88888"
        assert data.title == "최소 공고"
        assert data.start_date is None
        assert data.end_date is None

    def test_parse_detail_housing_type_from_title(self, db_session):
        """제목에서 모집 유형을 추출한다."""
        crawler = LHCrawler(db_session)
        item = ListItem(
            source_id="77777",
            title="2024년 행복주택 모집",
            detail_url="http://example.com/77777",
        )
        html = "<html><body><div class='view_cont'>일반 내용</div></body></html>"
        data = crawler.parse_detail(html, item)
        assert data.housing_type == "행복주택"


class TestLHCrawlerIntegration:
    """LHCrawler 통합 테스트 (HTTP 모킹)."""

    def test_full_run_with_mock_client(self, db_session):
        """전체 크롤링 플로우를 모킹하여 테스트한다."""
        mock_client = MagicMock()

        # 목록 페이지 응답
        list_response = MagicMock()
        list_response.text = SAMPLE_LH_LIST_HTML
        list_response.raise_for_status = MagicMock()

        # 상세 페이지 응답
        detail_response = MagicMock()
        detail_response.text = SAMPLE_LH_DETAIL_HTML
        detail_response.raise_for_status = MagicMock()

        mock_client.get = MagicMock(
            side_effect=[list_response, detail_response, detail_response]
        )

        crawler = LHCrawler(db_session, client=mock_client)
        count = crawler.run()

        assert count == 2
        db_session.commit()
        announcements = db_session.query(Announcement).filter_by(source_site="lh").all()
        assert len(announcements) == 2

    def test_run_handles_fetch_error(self, db_session):
        """HTTP 요청 실패 시 빈 결과를 반환하고 예외를 던진다."""
        mock_client = MagicMock()
        mock_client.get = MagicMock(side_effect=httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        ))

        crawler = LHCrawler(db_session, client=mock_client)
        with pytest.raises(httpx.HTTPStatusError):
            crawler.fetch_list()


# ──────────────────────────────────────────────────────────
# MyHome Crawler Tests
# ──────────────────────────────────────────────────────────


SAMPLE_MYHOME_LIST_HTML = """
<html>
<body>
<table>
<tbody>
<tr>
    <td>1</td>
    <td><a href="/hws/portal/sch/selectRsdtRcritNtcDetailView.do?pblancId=PB2024001">서울 강서구 행복주택 입주자 모집</a></td>
    <td>서울</td>
    <td>2024.07.01</td>
    <td>50</td>
</tr>
<tr>
    <td>2</td>
    <td><a href="/hws/portal/sch/selectRsdtRcritNtcDetailView.do?pblancId=PB2024002">경기 성남시 공공임대 모집공고</a></td>
    <td>경기</td>
    <td>2024.06.20</td>
    <td>120</td>
</tr>
</tbody>
</table>
</body>
</html>
"""

SAMPLE_MYHOME_DETAIL_HTML = """
<html>
<body>
<div class="view_cont">
    <h3>서울 강서구 행복주택 입주자 모집</h3>
    <table>
        <tr><th>접수기간</th><td>2024.07.01 ~ 2024.07.15</td></tr>
        <tr><th>모집유형</th><td>행복주택</td></tr>
        <tr><th>소재지</th><td>서울특별시 강서구</td></tr>
    </table>
    <div class="content">
        <p>입주자격 안내</p>
        <p>- 만 19세 이상 39세 이하 청년</p>
        <p>- 기준 중위소득 150% 이하에 해당하는 자</p>
        <p>- 무주택 세대구성원</p>
        <p>- 서울 거주 1년 이상</p>
        <p>당첨자 발표 예정일: 2024.08.01</p>
    </div>
</div>
</body>
</html>
"""

SAMPLE_MYHOME_EMPTY_LIST_HTML = """
<html>
<body>
<table>
<tbody>
</tbody>
</table>
</body>
</html>
"""


class TestMyHomeCrawlerParseList:
    """MyHomeCrawler.parse_list() 테스트."""

    def test_parse_list_items(self, db_session):
        """목록 페이지에서 공고 항목을 파싱한다."""
        crawler = MyHomeCrawler(db_session)
        items = crawler.parse_list(SAMPLE_MYHOME_LIST_HTML)
        assert len(items) == 2
        assert items[0].source_id == "PB2024001"
        assert items[0].title == "서울 강서구 행복주택 입주자 모집"
        assert items[1].source_id == "PB2024002"
        assert items[1].title == "경기 성남시 공공임대 모집공고"

    def test_parse_list_empty_table(self, db_session):
        """빈 테이블이면 빈 리스트를 반환한다."""
        crawler = MyHomeCrawler(db_session)
        items = crawler.parse_list(SAMPLE_MYHOME_EMPTY_LIST_HTML)
        assert items == []

    def test_source_id_extraction_various_params(self, db_session):
        """다양한 URL 파라미터에서 source_id를 추출한다."""
        crawler = MyHomeCrawler(db_session)
        # pblancId 파라미터
        assert crawler._extract_source_id("?pblancId=PB2024001") == "PB2024001"
        # ntcSn 파라미터
        assert crawler._extract_source_id("?ntcSn=12345") == "12345"
        # rcritId 파라미터
        assert crawler._extract_source_id("?rcritId=RC001") == "RC001"
        # sn 파라미터
        assert crawler._extract_source_id("?sn=99999") == "99999"
        # 파라미터 없는 경우
        assert crawler._extract_source_id("/some/path") is None

    def test_detail_url_construction(self, db_session):
        """상세 페이지 URL을 올바르게 구성한다."""
        crawler = MyHomeCrawler(db_session)
        # 절대 경로
        url = crawler._build_detail_url("/hws/portal/view.do?sn=1", "1")
        assert url == "https://www.myhome.go.kr/hws/portal/view.do?sn=1"
        # 완전 URL
        url = crawler._build_detail_url("https://www.myhome.go.kr/view?sn=1", "1")
        assert url == "https://www.myhome.go.kr/view?sn=1"
        # 기본 URL 구성
        url = crawler._build_detail_url("relative/path", "ABC123")
        assert "pblancId=ABC123" in url


class TestMyHomeCrawlerParseDetail:
    """MyHomeCrawler.parse_detail() 테스트."""

    def test_parse_detail_full(self, db_session):
        """상세 페이지에서 모든 정보를 추출한다."""
        crawler = MyHomeCrawler(db_session)
        item = ListItem(
            source_id="PB2024001",
            title="서울 강서구 행복주택 입주자 모집",
            detail_url="https://www.myhome.go.kr/hws/portal/sch/selectRsdtRcritNtcDetailView.do?pblancId=PB2024001",
        )
        data = crawler.parse_detail(SAMPLE_MYHOME_DETAIL_HTML, item)

        assert data.source_site == "myhome"
        assert data.source_id == "PB2024001"
        assert data.title == "서울 강서구 행복주택 입주자 모집"
        assert data.housing_type == "행복주택"
        assert data.start_date == date(2024, 7, 1)
        assert data.end_date == date(2024, 7, 15)
        assert data.result_date == date(2024, 8, 1)
        assert data.target_region is not None
        assert "강서" in data.target_region
        assert data.eligibility_age is not None
        assert data.eligibility_income is not None
        assert data.eligibility_homeless is not None
        assert data.eligibility_residence is not None

    def test_parse_detail_minimal(self, db_session):
        """최소 HTML에서도 파싱이 동작한다."""
        crawler = MyHomeCrawler(db_session)
        item = ListItem(
            source_id="PB9999",
            title="최소 공고",
            detail_url="http://example.com/PB9999",
        )
        html = "<html><body><div class='view_cont'>간단한 내용</div></body></html>"
        data = crawler.parse_detail(html, item)

        assert data.source_site == "myhome"
        assert data.source_id == "PB9999"
        assert data.title == "최소 공고"
        assert data.start_date is None
        assert data.end_date is None

    def test_parse_detail_housing_type_from_title(self, db_session):
        """제목에서 모집 유형을 추출한다."""
        crawler = MyHomeCrawler(db_session)
        item = ListItem(
            source_id="PB8888",
            title="2024년 공공임대 모집",
            detail_url="http://example.com/PB8888",
        )
        html = "<html><body><div class='view_cont'>일반 내용</div></body></html>"
        data = crawler.parse_detail(html, item)
        assert data.housing_type == "공공임대"


class TestMyHomeCrawlerIntegration:
    """MyHomeCrawler 통합 테스트 (HTTP 모킹)."""

    def test_full_run_with_mock_client(self, db_session):
        """전체 크롤링 플로우를 모킹하여 테스트한다."""
        mock_client = MagicMock()

        # 목록 페이지 응답
        list_response = MagicMock()
        list_response.text = SAMPLE_MYHOME_LIST_HTML
        list_response.raise_for_status = MagicMock()

        # 상세 페이지 응답
        detail_response = MagicMock()
        detail_response.text = SAMPLE_MYHOME_DETAIL_HTML
        detail_response.raise_for_status = MagicMock()

        mock_client.get = MagicMock(
            side_effect=[list_response, detail_response, detail_response]
        )

        crawler = MyHomeCrawler(db_session, client=mock_client)
        count = crawler.run()

        assert count == 2
        db_session.commit()
        announcements = db_session.query(Announcement).filter_by(source_site="myhome").all()
        assert len(announcements) == 2

    def test_run_handles_fetch_error(self, db_session):
        """HTTP 요청 실패 시 예외를 던진다."""
        mock_client = MagicMock()
        mock_client.get = MagicMock(side_effect=httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock()
        ))

        crawler = MyHomeCrawler(db_session, client=mock_client)
        with pytest.raises(httpx.HTTPStatusError):
            crawler.fetch_list()

    def test_run_skips_duplicates(self, db_session):
        """중복 공고는 건너뛴다."""
        mock_client = MagicMock()

        list_response = MagicMock()
        list_response.text = SAMPLE_MYHOME_LIST_HTML
        list_response.raise_for_status = MagicMock()

        detail_response = MagicMock()
        detail_response.text = SAMPLE_MYHOME_DETAIL_HTML
        detail_response.raise_for_status = MagicMock()

        mock_client.get = MagicMock(
            side_effect=[list_response, detail_response, detail_response]
        )

        crawler = MyHomeCrawler(db_session, client=mock_client)
        count = crawler.run()
        assert count == 2
        db_session.commit()

        # 두 번째 실행 - 목록 다시 가져오지만 중복이므로 0건
        mock_client.get = MagicMock(
            side_effect=[list_response]
        )
        count = crawler.run()
        assert count == 0
