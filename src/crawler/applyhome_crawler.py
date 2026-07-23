"""청약홈 분양정보 API 클라이언트.

공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스' API를 활용하여
민간분양(로또청약) 공고를 수집한다. 서울 지역 필터링 적용.
"""

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from src.crawler.base import AnnouncementData

logger = logging.getLogger(__name__)

# 공공데이터포털 API
BASE_URL = "https://api.odcloud.kr/api"

# API 경로 (APT 분양 제외 — 청년 타겟에 비합리적 가격)
API_PATHS = {
    "urbty": "/ApplyhomeInfoDetailSvc/v1/getUrbtyOfctlLttotPblancDetail",
    "public_rent": "/ApplyhomeInfoDetailSvc/v1/getPblPvtRentLttotPblancDetail",
}

REQUEST_TIMEOUT = 30.0


class ApplyHomeAPIClient:
    """청약홈 분양정보 API 클라이언트.

    공공데이터포털 API를 통해 민간분양 공고를 조회한다.
    서울 지역 공고만 필터링하여 반환한다.
    """

    source_site = "applyhome"

    def __init__(self, api_key: str) -> None:
        """API 클라이언트를 초기화한다.

        Args:
            api_key: 공공데이터포털 API 인증키.
        """
        self.api_key = api_key
        self.client = httpx.Client(timeout=REQUEST_TIMEOUT)

    def fetch_recent_announcements(
        self, days_back: int = 30
    ) -> list[AnnouncementData]:
        """최근 N일간의 서울 지역 분양 공고를 가져온다.

        Args:
            days_back: 조회할 과거 일수 (기본 30일).

        Returns:
            파싱된 공고 데이터 목록.
        """
        all_announcements: list[AnnouncementData] = []

        for api_type, path in API_PATHS.items():
            try:
                items = self._fetch_api(path, days_back)
                announcements = self._parse_items(items, api_type)
                all_announcements.extend(announcements)
                logger.info(
                    "[applyhome] %s: %d건 조회, 서울 %d건",
                    api_type,
                    len(items),
                    len(announcements),
                )
            except Exception as e:
                logger.error("[applyhome] %s API 호출 실패: %s", api_type, str(e))

        logger.info("[applyhome] 총 %d건 수집", len(all_announcements))
        return all_announcements

    def _fetch_api(self, path: str, days_back: int) -> list[dict[str, Any]]:
        """API를 호출하여 결과를 반환한다."""
        today = date.today()
        start_date = today - timedelta(days=days_back)

        params = {
            "serviceKey": self.api_key,
            "page": "1",
            "perPage": "100",
            "cond[RCRIT_PBLANC_DE::GTE]": start_date.isoformat(),
            "cond[RCRIT_PBLANC_DE::LTE]": today.isoformat(),
        }

        url = f"{BASE_URL}{path}"
        response = self.client.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if "data" in data:
            return data["data"]
        elif "body" in data:
            return data["body"].get("items", [])
        else:
            return []

    def _parse_items(
        self, items: list[dict], api_type: str
    ) -> list[AnnouncementData]:
        """API 응답 항목을 AnnouncementData로 변환한다. 서울만 필터."""
        results: list[AnnouncementData] = []

        for item in items:
            # 서울 지역 필터
            region = item.get("SIDO_NM", "") or item.get("SUBSCRPT_AREA_CODE_NM", "")
            if "서울" not in region:
                continue

            source_id = str(
                item.get("PBLANC_NO", "") or item.get("HOUSE_MANAGE_NO", "")
            )
            if not source_id:
                continue

            title = item.get("HOUSE_NM", "") or item.get("BSNS_MBY_NM", "") or ""
            if not title:
                continue

            # 주택 유형 결정
            housing_type = self._determine_housing_type(item, api_type)

            # 날짜 파싱
            start_date = self._parse_date(
                item.get("RCEPT_BGNDE", "") or item.get("SUBSCRPT_RCEPT_BGNDE", "")
            )
            end_date = self._parse_date(
                item.get("RCEPT_ENDDE", "") or item.get("SUBSCRPT_RCEPT_ENDDE", "")
            )
            result_date = self._parse_date(
                item.get("PRZWNER_PRESNATN_DE", "")
            )

            # 지역 상세
            target_region = region
            if item.get("HSSPLY_ADRES"):
                target_region = item["HSSPLY_ADRES"]

            # 원문 링크
            pblanc_url = item.get("PBLANC_URL", "")
            if not pblanc_url:
                pblanc_url = f"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo={source_id}"

            results.append(
                AnnouncementData(
                    source_site=self.source_site,
                    source_id=source_id,
                    title=title,
                    announcement_category="민간분양",
                    housing_type=housing_type,
                    start_date=start_date,
                    end_date=end_date,
                    result_date=result_date,
                    target_region=target_region,
                    eligibility_age=None,
                    eligibility_income=None,
                    eligibility_homeless=item.get("MVNG_BLNK_AT", None),
                    eligibility_residence=None,
                    original_url=pblanc_url,
                )
            )

        return results

    def _determine_housing_type(self, item: dict, api_type: str) -> str:
        """API 유형과 항목 데이터에서 주택 유형을 결정한다."""
        if api_type == "urbty":
            house_secd = item.get("HOUSE_SECD_NM", "")
            if "오피스텔" in house_secd:
                return "오피스텔"
            elif "도시형" in house_secd:
                return "도시형생활주택"
            elif "민간임대" in house_secd:
                return "민간임대"
            return house_secd or "오피스텔/도시형"
        elif api_type == "public_rent":
            return "공공지원 민간임대"
        return "민간분양"

    def _parse_date(self, date_str: str) -> date | None:
        """날짜 문자열을 date 객체로 변환한다."""
        if not date_str:
            return None
        # 여러 포맷 시도
        date_str = date_str.strip().replace("/", "-").replace(".", "-")
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass
        # YYYYMMDD 형식
        if len(date_str) == 8 and date_str.isdigit():
            try:
                return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            except ValueError:
                pass
        return None
