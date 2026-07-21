"""LH한국토지주택공사 크롤러.

LH공사 청약 공고 목록 및 상세 페이지를 크롤링하여 구조화된 데이터로 저장한다.
"""

import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from src.crawler.base import AnnouncementData, BaseCrawler, ListItem
from src.crawler.parser import parse_date, parse_eligibility

logger = logging.getLogger(__name__)

# LH공사 기본 URL
LH_BASE_URL = "https://www.lh.or.kr"
LH_LIST_URL = f"{LH_BASE_URL}/LH/contents/CON_02_02_01.do"
LH_DETAIL_URL = f"{LH_BASE_URL}/LH/contents/CON_02_02_01_view.do"

# HTTP 요청 설정
REQUEST_TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class LHCrawler(BaseCrawler):
    """LH한국토지주택공사 크롤러.

    청약센터 > 공고문 게시판에서 공고 목록을 가져온 후,
    개별 상세 페이지에서 자격요건 등 상세 정보를 추출한다.
    """

    source_site = "lh"

    def __init__(self, session, client: httpx.Client | None = None) -> None:
        super().__init__(session)
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    @property
    def client(self) -> httpx.Client:
        """HTTP 클라이언트를 반환한다."""
        return self._client

    def fetch_list(self) -> str:
        """LH공사 공고 목록 페이지 HTML을 가져온다."""
        logger.info("[LH] 목록 페이지 요청: %s", LH_LIST_URL)
        response = self._client.get(LH_LIST_URL)
        response.raise_for_status()
        return response.text

    def parse_list(self, html: str) -> list[ListItem]:
        """목록 페이지 HTML에서 공고 항목을 파싱한다.

        LH공사 게시판은 테이블 형태로 공고 목록을 제공한다.
        각 행에서 제목, 링크(source_id 포함)를 추출한다.
        """
        soup = BeautifulSoup(html, "html.parser")
        items: list[ListItem] = []

        # 게시판 테이블의 각 행을 탐색
        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.select(".board_list .list_item, .bbs_list tbody tr")

        for row in rows:
            try:
                item = self._parse_list_row(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug("[LH] 목록 행 파싱 실패: %s", str(e))
                continue

        return items

    def _parse_list_row(self, row) -> ListItem | None:
        """테이블 행에서 ListItem을 추출한다."""
        link = row.select_one("a[href]")
        if not link:
            return None

        title = link.get_text(strip=True)
        if not title:
            return None

        href = link.get("href", "")

        # source_id 추출
        source_id = self._extract_source_id(href)
        if not source_id:
            return None

        # 상세 페이지 URL 구성
        detail_url = self._build_detail_url(href, source_id)

        # 추가 정보 추출
        extra = self._extract_row_extra(row)

        return ListItem(
            source_id=source_id,
            title=title,
            detail_url=detail_url,
            extra=extra,
        )

    def _extract_source_id(self, href: str) -> str | None:
        """URL에서 공고 고유 ID를 추출한다.

        LH공사 URL 파라미터: not_sn, nttId, seq, bbs_sn 등
        """
        patterns = [
            r"[?&]not_sn=(\d+)",
            r"[?&]nttId=(\d+)",
            r"[?&]seq=(\d+)",
            r"[?&]bbs_sn=(\d+)",
            r"[?&]pblancNo=([A-Za-z0-9]+)",
            r"/view/(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, href)
            if match:
                return match.group(1)

        # JavaScript 함수 호출에서 추출
        js_match = re.search(r"(?:fn_view|goView|detail)\s*\(\s*['\"]?(\d+)", href)
        if js_match:
            return js_match.group(1)

        return None

    def _build_detail_url(self, href: str, source_id: str) -> str:
        """상세 페이지 URL을 구성한다."""
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{LH_BASE_URL}{href}"
        return f"{LH_DETAIL_URL}?not_sn={source_id}"

    def _extract_row_extra(self, row) -> dict:
        """테이블 행에서 추가 정보를 추출한다."""
        extra = {}
        cells = row.select("td")
        if len(cells) >= 3:
            for cell in cells:
                text = cell.get_text(strip=True)
                if re.match(r"\d{4}[.\-/]\d{2}[.\-/]\d{2}", text):
                    extra["date"] = text
        return extra

    def fetch_detail(self, item: ListItem) -> str:
        """공고 상세 페이지 HTML을 가져온다."""
        logger.info("[LH] 상세 페이지 요청: %s", item.detail_url)
        response = self._client.get(item.detail_url)
        response.raise_for_status()
        return response.text

    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        """상세 페이지 HTML에서 공고 상세 정보를 파싱한다."""
        soup = BeautifulSoup(html, "html.parser")

        # 본문 텍스트 추출
        content_area = soup.select_one(
            ".view_cont, .bbs_view, .board_view, .content_view, #content, .detail_cont"
        )
        body_text = content_area.get_text(separator="\n") if content_area else soup.get_text()

        # 자격요건 추출
        eligibility = parse_eligibility(body_text)

        # 모집 기간 추출
        start_date, end_date = self._extract_period(soup, body_text)

        # 모집 유형 추출
        housing_type = self._extract_housing_type(soup, body_text, item.title)

        # 대상 지역 추출
        target_region = self._extract_region(body_text)

        # 당첨 발표일 추출
        result_date = self._extract_result_date(body_text)

        return AnnouncementData(
            source_site=self.source_site,
            source_id=item.source_id,
            title=item.title,
            announcement_category="공공임대",
            housing_type=housing_type,
            start_date=start_date,
            end_date=end_date,
            result_date=result_date,
            target_region=target_region,
            eligibility_age=eligibility.age,
            eligibility_income=eligibility.income,
            eligibility_homeless=eligibility.homeless,
            eligibility_residence=eligibility.residence_period,
            original_url=item.detail_url,
        )

    def _extract_period(self, soup, body_text: str) -> tuple[date | None, date | None]:
        """모집 기간(시작일, 마감일)을 추출한다."""
        start_date = None
        end_date = None

        period_patterns = [
            r"(?:모집|접수|신청)\s*기간\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~\-]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
            r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~\-]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        ]

        for pattern in period_patterns:
            match = re.search(pattern, body_text)
            if match:
                start_date = parse_date(match.group(1))
                end_date = parse_date(match.group(2))
                if start_date and end_date:
                    return start_date, end_date

        # 테이블 기반 추출
        table_cells = soup.select("th, dt, .tit")
        for cell in table_cells:
            label = cell.get_text(strip=True)
            if any(kw in label for kw in ["모집기간", "접수기간", "신청기간"]):
                value_cell = cell.find_next_sibling("td") or cell.find_next_sibling("dd")
                if value_cell:
                    value_text = value_cell.get_text(strip=True)
                    dates = re.findall(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}", value_text)
                    if len(dates) >= 2:
                        start_date = parse_date(dates[0])
                        end_date = parse_date(dates[1])
                    elif len(dates) == 1:
                        start_date = parse_date(dates[0])

        return start_date, end_date

    def _extract_housing_type(self, soup, body_text: str, title: str) -> str | None:
        """모집 유형을 추출한다."""
        housing_types = [
            "행복주택",
            "공공임대",
            "국민임대",
            "영구임대",
            "장기전세",
            "매입임대",
            "공공분양",
            "신혼희망타운",
            "역세권청년주택",
            "통합공공임대",
        ]
        for housing_type in housing_types:
            if housing_type in title:
                return housing_type

        for housing_type in housing_types:
            if housing_type in body_text:
                return housing_type

        return None

    def _extract_region(self, body_text: str) -> str | None:
        """대상 지역을 추출한다."""
        # 서울 구 이름 패턴
        match = re.search(
            r"(서울\s*(?:특별시\s*)?(?:[가-힣]+구))",
            body_text,
        )
        if match:
            return match.group(1)

        # 광역시/도 패턴
        region_match = re.search(
            r"((?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
            r"(?:\s*(?:특별시|광역시|특별자치시|도|특별자치도))?)",
            body_text,
        )
        if region_match:
            return region_match.group(1)

        return None

    def _extract_result_date(self, body_text: str) -> date | None:
        """당첨자 발표일을 추출한다."""
        patterns = [
            r"(?:당첨자?\s*)?발표\s*(?:일|일자|예정일)?\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
            r"합격자?\s*발표\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                return parse_date(match.group(1))
        return None
