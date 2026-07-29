"""HUG 든든전세주택 크롤러.

KB부동산 API(api.kbland.kr)를 통해 HUG 든든전세주택 모집공고 목록을 수집한다.
모집 기간 중 서울 지역 매물 목록을 가져와 구조화된 데이터로 저장한다.
"""

import logging
from datetime import datetime

import httpx

from src.crawler.base import AnnouncementData, BaseCrawler, ListItem
from src.crawler.parser import parse_date

logger = logging.getLogger(__name__)

# KB부동산 HUG 든든전세주택 API
HUG_API_URL = "https://api.kbland.kr/land-property-suggestion/hugRelRntHouse/getInventoryList"
HUG_KBLAND_URL = "https://kbland.kr/hug"

REQUEST_TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# 모집 기간 외에는 응답에 매물이 0건 → totalCount로 판별
RESULT_CODE_OK = "10000"


class HUGCrawler(BaseCrawler):
    """HUG 든든전세주택 크롤러.

    KB부동산 API를 통해 서울 지역 든든전세주택 매물 목록을 수집한다.
    모집 기간 중에만 데이터가 존재하며, 공고일자 기준으로 신규 공고를 감지한다.
    """

    source_site = "hug"

    def __init__(self, session, client: httpx.Client | None = None) -> None:
        super().__init__(session)
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "accept": "application/json, text/plain, */*",
                "accept-language": "ko-KR,ko;q=0.9",
                "content-type": "application/json",
                "origin": "https://kbland.kr",
                "referer": "https://kbland.kr/",
                "webservice": "1",
            },
            follow_redirects=True,
        )

    @property
    def client(self) -> httpx.Client:
        return self._client

    def _make_headers(self) -> dict:
        """동적 timestamp/traceid 헤더를 생성한다."""
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
        return {
            "timestamp": now,
            "traceid": f"bot_{now[:8]}{now[8:12]}",
        }

    def fetch_list(self) -> str:
        """KB부동산 API를 호출하여 든든전세주택 목록 JSON을 반환한다.

        페이지 크기를 크게 설정하여 전체 목록을 한 번에 가져온다.
        """
        payload = {
            "시도명": "서울",
            "시군구명": "전체",
            "물건종류": "아파트, 오피스텔, 연립주택, 다세대주택",
            "분양시작값": "",
            "분양종료값": "",
            "면적시작값": "",
            "면적종료값": "",
            "정렬기준": "01",  # 낮은가격순
            "페이지목록수": 200,
            "페이지번호": 1,
        }
        logger.info("[HUG] API 호출: %s", HUG_API_URL)
        response = self._client.post(
            HUG_API_URL,
            json=payload,
            headers=self._make_headers(),
        )
        response.raise_for_status()
        return response.text

    def parse_list(self, html: str) -> list[ListItem]:
        """JSON 응답에서 든든전세주택 매물 목록을 파싱한다.

        모집 기간이 아니면 매물목록이 비어있으므로 빈 리스트를 반환한다.
        개별 매물이 아닌 "공고 단위"로 처리하기 위해,
        동일 공고일자의 매물들을 하나의 공고로 묶어 ListItem을 생성한다.
        """
        import json

        try:
            data = json.loads(html)
        except json.JSONDecodeError as e:
            logger.error("[HUG] JSON 파싱 실패: %s", str(e))
            return []

        header = data.get("dataHeader", {})
        if header.get("resultCode") != RESULT_CODE_OK:
            logger.warning("[HUG] API 오류 응답: %s", header.get("message"))
            return []

        body = data.get("dataBody", {}).get("data", {})
        items_raw = body.get("매물목록", [])
        total_count = body.get("totalCount", 0)

        if not items_raw:
            logger.info("[HUG] 현재 모집 중인 든든전세주택 없음 (totalCount=0)")
            return []

        logger.info("[HUG] 든든전세주택 매물 %d건 발견", total_count)

        # 공고일자 기준으로 그룹화 → 공고 단위 처리
        # 같은 공고일자의 매물들 = 같은 모집 차수
        공고일자 = items_raw[0].get("공고일자", "")
        청약시작 = body.get("청약접수시작일시", "")
        청약종료 = body.get("청약접수종료일시", "")

        if not 공고일자:
            logger.warning("[HUG] 공고일자 없음, 건너뜀")
            return []

        # source_id: 공고일자 기반 (차수별 중복 방지)
        # e.g. "2026.07.24" → "20260724"
        source_id = 공고일자.replace(".", "")

        # 공고 제목에 차수 정보 포함
        # 차수는 앞 선 공고와의 비교로 확인이 어려우므로 날짜 기반으로 구성
        title = f"HUG 든든전세주택 서울 입주자 모집 공고 ({공고일자})"

        # 매물 구별 목록 (최대 5개 예시)
        구별_카운트: dict[str, int] = {}
        for item in items_raw:
            구 = item.get("시군구명", "")
            if 구:
                구별_카운트[구] = 구별_카운트.get(구, 0) + 1

        extra = {
            "공고일자": 공고일자,
            "청약시작": 청약시작,
            "청약종료": 청약종료,
            "총매물수": total_count,
            "구별분포": 구별_카운트,
        }

        return [
            ListItem(
                source_id=source_id,
                title=title,
                detail_url=HUG_KBLAND_URL,
                extra=extra,
            )
        ]

    def fetch_detail(self, item: ListItem) -> str:
        """HUG 크롤러는 API에서 목록 단계에서 모든 정보를 가져오므로
        상세 페이지 별도 요청 없이 빈 문자열을 반환한다."""
        return ""

    def parse_detail(self, html: str, item: ListItem) -> AnnouncementData:
        """ListItem의 extra 정보로 AnnouncementData를 구성한다."""
        공고일자 = item.extra.get("공고일자", "")
        청약시작 = item.extra.get("청약시작", "")
        청약종료 = item.extra.get("청약종료", "")
        총매물수 = item.extra.get("총매물수", 0)
        구별분포 = item.extra.get("구별분포", {})

        # 날짜 파싱 (형식: "2026.07.24 10:00" 또는 "2026.07.24")
        start_date = parse_date(청약시작.split(" ")[0] if 청약시작 else 공고일자)
        end_date = parse_date(청약종료.split(" ")[0] if 청약종료 else "")

        # 구별 분포 문자열 (자격요건 요약 대신 활용)
        구별_요약 = ", ".join(
            f"{구} {수}건"
            for 구, 수 in sorted(구별분포.items(), key=lambda x: -x[1])[:5]
        )
        eligibility_summary = (
            f"무주택세대구성원 누구나 신청 가능 (거주지역 제한 없음) | "
            f"서울 총 {총매물수}건 | 주요 지역: {구별_요약}"
        )

        return AnnouncementData(
            source_site=self.source_site,
            source_id=item.source_id,
            title=item.title,
            announcement_category="든든전세",
            housing_type="든든전세주택",
            start_date=start_date,
            end_date=end_date,
            result_date=None,
            target_region="서울",
            eligibility_age="제한 없음",
            eligibility_income="제한 없음",
            eligibility_homeless="무주택세대구성원 전원",
            eligibility_residence="거주지역 제한 없음",
            original_url="https://kbland.kr/hug",
        )
