"""청약홈 크롤러.

청약홈(applyhome.co.kr) 민간분양(로또청약) 공고를 크롤링하여 구조화된 데이터로 저장한다.
서울 지역 APT 분양 공고를 대상으로 한다.
"""

import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from src.crawler.base import AnnouncementData, BaseCrawler, ListItem
from src.crawler.parser import parse_date, parse_eligibility

logger = logging.getLogger(__name__)

# 청약홈 기본 URL
APPLYHOME_BASE_URL = "https://www.applyhome.co.kr"
# APT 분양 공고 목록 (서울)
APPLYHOME_LIST_URL = (
    f"{APPLYHOME_BASE_URL}/ai/aia/selectAPTLttotPblancList.do"
)
APPLYHOME_DETAIL_URL = (
    f"{APPLYHOME_BASE_URL}/ai/aia/selectAPTLttotPblancDetail.do"
)

# HTTP 요청 설정
REQUEST_TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class ApplyHomeCrawler(BaseCrawler):
    """청약홈 크롤러.

    민간분양(로또청약) APT 공고를 서울 지역 한정으로 수집한다.
    """

    source_site = "applyhome"

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
        """청약홈 APT 분양 공고 목록 페이지 HTML을 가져온다.

        서울 지역 필터를 적용하여 요청한다.
        """
        logger.info("[applyhome] 목록 페이지 요청: %s", APPLYHOME_LIST_URL)
        # 청약홈은 POST 방식으로 목록 요청
        params = {
            "hssplyPblancAt": "Y",  # 공급 공고 여부
            "suplyTyCode": "",  # 공급유형 (전체)
            "sido": "서울",  # 서울 지역
            "pageIndex": "1",
            "pageSize": "20",
        }
        response = self._client.post(APPLYHOME_LIST_URL, data=params)
        response.raise_for_status()
        return response.text

    def parse_list(self, html: str) -> list[ListItem]:
        """목록 페이지 HTML에서 APT 분양 공고 항목을 파싱한다."""
        soup = BeautifulSoup(html, "html.parser")
        items: list[ListItem] = []

        # 테이블 기반 목록 탐색
        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.select(".tbl_st tbody tr, .board_list tbody tr")

        for row in rows:
            try:
                item = self._parse_list_row(row)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug("[applyhome] 목록 행 파싱 실패: %s", str(e))
                continue

        return items

    def _parse_list_row(self, row) -> ListItem | None:
        """테이블 행에서 ListItem을 추출한다."""
        link = row.select_one("a[href], a[onclick]")
        if not link:
            return None

        title = link.get_text(strip=True)
        if not title:
            return None

        # source_id 추출
        href = link.get("href", "") or link.get("onclick", "")
        source_id = self._extract_source_id(href)
        if not source_id:
            return None

        detail_url = f"{APPLYHOME_DETAIL_URL}?pblancNo={source_id}"

        extra = self._extract_row_extra(row)

        return ListItem(
            source_id=source_id,
            title=title,
            detail_url=detail_url,
            extra=extra,
        )

    def _extract_source_id(self, href: str) -> str | None:
        """URL 또는 onclick에서 공고 고유 ID를 추출한다."""
        patterns = [
            r"pblancNo[='\s]*['\"]?(\d+)",
            r"[?&]no=(\d+)",
            r"detail\s*\(\s*['\"]?(\d+)",
            r"goDetail\s*\(\s*['\"]?(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, href)
            if match:
                return match.group(1)
        return None

    def _extract_row_extra(self, row) -> dict:
        """행에서 추가 정보 추출."""
        extra = {}
        cells = row.select("td")
        for cell in cells:
            text = cell.get_text(strip=True)
            if re.match(r"\d{4}[.\-/]\d{2}[.\-/]\d{2}", text):
                extra["date"] = text
            elif "서울" in text:
                extra["region"] = text
        return extra

    def fetch_detail(self, item: ListItem) -> str:
        """공고 상세 페이지 HTML을 가져온다."""
        logger.info("[applyhome] 상세 페이지 요청: %s", item.detail_url)
        response = self._client.get(item.detail_url)
        response.raise_for_status()
        return response.text

    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        """상세 페이지에서 민간분양 공고 정보를 파싱한다."""
        soup = BeautifulSoup(html, "html.parser")

        content_area = soup.select_one(
            ".view_cont, .content_view, #content, .board_view"
        )
        body_text = (
            content_area.get_text(separator="\n") if content_area else soup.get_text()
        )

        # 자격요건 추출
        eligibility = parse_eligibility(body_text)

        # 모집 기간 추출
        start_date, end_date = self._extract_period(soup, body_text)

        # 주택 유형 추출
        housing_type = self._extract_housing_type(body_text, item.title)

        # 대상 지역
        target_region = self._extract_region(body_text)

        # 당첨 발표일
        result_date = self._extract_result_date(body_text)

        return AnnouncementData(
            source_site=self.source_site,
            source_id=item.source_id,
            title=item.title,
            announcement_category="민간분양",
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
        """청약 접수 기간을 추출한다."""
        start_date = None
        end_date = None

        period_patterns = [
            r"(?:청약|접수|신청)\s*기간\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~\-]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
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
        table_cells = soup.select("th, dt")
        for cell in table_cells:
            label = cell.get_text(strip=True)
            if any(kw in label for kw in ["청약접수", "접수기간", "청약기간"]):
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

    def _extract_housing_type(self, body_text: str, title: str) -> str | None:
        """분양 유형을 추출한다."""
        housing_types = [
            "민간분양",
            "공공분양",
            "민영주택",
            "국민주택",
            "도시형생활주택",
            "오피스텔",
            "아파트",
        ]
        for housing_type in housing_types:
            if housing_type in title:
                return housing_type
        for housing_type in housing_types:
            if housing_type in body_text:
                return housing_type
        return "민간분양"

    def _extract_region(self, body_text: str) -> str | None:
        """대상 지역을 추출한다."""
        match = re.search(
            r"(서울\s*(?:특별시\s*)?(?:[가-힣]+구))",
            body_text,
        )
        if match:
            return match.group(1)
        if "서울" in body_text:
            return "서울"
        return None

    def _extract_result_date(self, body_text: str) -> date | None:
        """당첨자 발표일을 추출한다."""
        patterns = [
            r"(?:당첨자?\s*)?발표\s*(?:일|일자)?\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
            r"당첨\s*발표\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                return parse_date(match.group(1))
        return None
