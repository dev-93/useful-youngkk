"""LH한국토지주택공사 크롤러.

LH청약플러스(apply.lh.or.kr) 임대주택 공고를 크롤링하여 구조화된 데이터로 저장한다.
서울특별시 공고만 필터링하여 수집한다.
"""

import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from src.crawler.base import AnnouncementData, BaseCrawler, ListItem
from src.crawler.parser import parse_date, parse_eligibility

logger = logging.getLogger(__name__)

# LH청약플러스 URL
LH_BASE_URL = "https://apply.lh.or.kr"
LH_LIST_URL = f"{LH_BASE_URL}/lhapply/apply/wt/wrtanc/selectWrtancList.do"
LH_DETAIL_URL = f"{LH_BASE_URL}/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"

# 임대주택 메뉴 ID
LH_MENU_ID = "1026"

# HTTP 요청 설정
REQUEST_TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class LHCrawler(BaseCrawler):
    """LH한국토지주택공사 크롤러.

    LH청약플러스 임대주택 공고문 페이지에서 서울 지역 공고를 수집한다.
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
        """LH 임대주택 공고 목록 페이지 HTML을 가져온다."""
        logger.info("[LH] 목록 페이지 요청: %s?mi=%s", LH_LIST_URL, LH_MENU_ID)
        response = self._client.get(LH_LIST_URL, params={"mi": LH_MENU_ID})
        response.raise_for_status()
        return response.text

    def parse_list(self, html: str) -> list[ListItem]:
        """목록 HTML에서 서울 지역 공고를 파싱한다.

        테이블 구조: 번호 | 유형 | 공고명 | 지역 | 첨부 | 게시일 | 마감일 | 상태 | 조회수
        서울특별시 공고만 필터링한다.
        """
        soup = BeautifulSoup(html, "html.parser")
        items: list[ListItem] = []

        table = soup.select_one("table")
        if not table:
            logger.warning("[LH] 테이블을 찾을 수 없음")
            return items

        rows = table.select("tr")[1:]  # 헤더 제외

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
        """테이블 행에서 서울 공고만 ListItem으로 추출한다."""
        cells = row.select("td")
        if len(cells) < 9:
            return None

        # 지역 필터 (서울만)
        region = cells[3].get_text(strip=True)
        if "서울" not in region:
            return None

        # 유형 필터 (청년 무관 유형 제외)
        housing_type = cells[1].get_text(strip=True)
        excluded_types = {"영구임대", "집주인임대", "가정어린이집"}
        if housing_type in excluded_types:
            return None

        # 공고명 + 링크 데이터
        title_cell = cells[2]
        link = title_cell.select_one("a.wrtancInfoBtn")
        if not link:
            link = title_cell.select_one("a")
        if not link:
            return None

        title = link.get_text(strip=True)
        # "N일전" 텍스트 제거
        title = re.sub(r"\d+일전$", "", title).strip()
        if not title:
            return None

        # data 속성에서 상세 페이지 파라미터 추출
        pan_id = link.get("data-id1", "")
        ccr_cnnt_sys_ds_cd = link.get("data-id2", "")
        upp_ais_tp_cd = link.get("data-id3", "")
        ais_tp_cd = link.get("data-id4", "")

        if not pan_id:
            return None

        # 유형
        housing_type = cells[1].get_text(strip=True)

        # 날짜
        start_date_str = cells[5].get_text(strip=True)
        end_date_str = cells[6].get_text(strip=True)

        # 상태
        status = cells[7].get_text(strip=True)

        extra = {
            "pan_id": pan_id,
            "ccr_cnnt_sys_ds_cd": ccr_cnnt_sys_ds_cd,
            "upp_ais_tp_cd": upp_ais_tp_cd,
            "ais_tp_cd": ais_tp_cd,
            "housing_type": housing_type,
            "region": region,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "status": status,
        }

        return ListItem(
            source_id=pan_id,
            title=title,
            detail_url=LH_DETAIL_URL,
            extra=extra,
        )

    def fetch_detail(self, item: ListItem) -> str:
        """공고 상세 페이지를 POST로 요청한다."""
        logger.info("[LH] 상세 페이지 요청: panId=%s", item.source_id)
        data = {
            "mi": LH_MENU_ID,
            "panId": item.extra.get("pan_id", item.source_id),
            "ccrCnntSysDsCd": item.extra.get("ccr_cnnt_sys_ds_cd", ""),
            "uppAisTpCd": item.extra.get("upp_ais_tp_cd", ""),
            "aisTpCd": item.extra.get("ais_tp_cd", ""),
        }
        response = self._client.post(LH_DETAIL_URL, data=data)
        response.raise_for_status()
        return response.text

    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        """상세 페이지에서 공고 정보를 파싱한다."""
        soup = BeautifulSoup(html, "html.parser")
        body_text = soup.get_text(separator="\n")

        # 목록에서 이미 가져온 정보 활용
        housing_type = item.extra.get("housing_type")
        region = item.extra.get("region", "서울특별시")
        start_date = parse_date(item.extra.get("start_date", ""))
        end_date = parse_date(item.extra.get("end_date", ""))

        # 본문에서 자격요건 추출 시도
        eligibility = parse_eligibility(body_text)

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
            target_region=region,
            eligibility_age=eligibility.age,
            eligibility_income=eligibility.income,
            eligibility_homeless=eligibility.homeless,
            eligibility_residence=eligibility.residence_period,
            original_url=f"{LH_DETAIL_URL}?panId={item.source_id}&mi={LH_MENU_ID}",
        )

    def _extract_result_date(self, body_text: str) -> date | None:
        """당첨자 발표일을 추출한다."""
        patterns = [
            r"(?:당첨자?\s*)?발표\s*(?:일|일자)?\s*[:\s]*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                return parse_date(match.group(1))
        return None
