"""청약홈 분양정보 API 클라이언트.

공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스' API를 활용하여
민간분양(로또청약) 공고를 수집한다. 서울 지역 필터링 적용.
"""

import logging
import re
from datetime import date, timedelta
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

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
        self.client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

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

    def fetch_eligibility_text(self, announcement: AnnouncementData) -> str | None:
        """공식 상세 링크에서 자격요건 본문 또는 PDF 첨부 텍스트를 가져온다.

        청약홈 상세 화면의 URL 구조를 고정하지 않고 API가 반환한 원문 링크를
        따라간 뒤, 페이지 본문과 모집공고문으로 보이는 PDF 링크를 탐색한다.
        """
        if not announcement.original_url:
            return None

        try:
            response = self.client.get(announcement.original_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("[applyhome] 상세 링크 접근 실패 (%s): %s", announcement.title, exc)
            return None

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or response.content.startswith(b"%PDF"):
            text = self._extract_pdf_text(response.content)
            return text if self._looks_like_eligibility_text(text) else None

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text("\n", strip=True)
        if self._looks_like_eligibility_text(page_text):
            return page_text

        for link in self._find_notice_pdf_links(soup, str(response.url)):
            try:
                pdf_response = self.client.get(link)
                pdf_response.raise_for_status()
                if (
                    "pdf" in pdf_response.headers.get("content-type", "").lower()
                    or pdf_response.content.startswith(b"%PDF")
                ):
                    text = self._extract_pdf_text(pdf_response.content)
                    if self._looks_like_eligibility_text(text):
                        return text
            except httpx.HTTPError as exc:
                logger.debug("[applyhome] 공고문 첨부 다운로드 실패: %s", exc)

        return None

    @staticmethod
    def _find_notice_pdf_links(soup: BeautifulSoup, page_url: str) -> list[str]:
        """상세 페이지에서 공고문일 가능성이 높은 PDF 링크를 찾는다."""
        candidates: list[tuple[int, str]] = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            label = anchor.get_text(" ", strip=True)
            onclick = anchor.get("onclick", "")
            raw_urls = [href]
            raw_urls.extend(re.findall(r"['\"]([^'\"]+\.pdf(?:\?[^'\"]*)?)['\"]", onclick, re.I))

            for raw_url in raw_urls:
                if not raw_url or raw_url.lower().startswith(("javascript:", "mailto:")):
                    continue
                candidate = urljoin(page_url, raw_url)
                parsed = urlparse(candidate)
                if parsed.scheme not in {"http", "https"}:
                    continue
                looks_like_pdf = re.search(r"\.pdf(?:$|\?)", candidate, re.I)
                looks_like_notice_download = any(
                    word in label for word in ("공고문", "모집공고", "입주자모집", "공급안내")
                ) and any(
                    word in candidate.lower() for word in ("file", "down", "atch", "attach")
                )
                if not looks_like_pdf and not looks_like_notice_download:
                    continue

                score = 1
                if any(word in label for word in ("공고문", "모집공고", "입주자모집", "공급안내")):
                    score += 10
                if "첨부" in label or "다운로드" in label:
                    score += 3
                candidates.append((score, candidate))

        return list(dict.fromkeys(url for _, url in sorted(candidates, reverse=True)))

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        """PDF에 내장된 텍스트를 추출한다. 이미지 PDF OCR은 별도 처리한다."""
        try:
            reader = PdfReader(BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as exc:
            logger.info("[applyhome] PDF 텍스트 추출 실패: %s", exc)
            return ""

    @staticmethod
    def _looks_like_eligibility_text(text: str) -> bool:
        return len(text) >= 200 and any(
            keyword in text
            for keyword in (
                "신청자격",
                "청약자격",
                "입주자격",
                "공급대상",
                "신청 요건",
                "청약신청",
            )
        )

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

            pblanc_no = str(item.get("PBLANC_NO", "") or "")
            house_manage_no = str(item.get("HOUSE_MANAGE_NO", "") or "")
            source_id = pblanc_no or house_manage_no
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
                # 청약홈 상세 화면은 주택관리번호와 공고번호를 함께 사용한다.
                query = f"houseManageNo={house_manage_no or source_id}"
                if pblanc_no:
                    query += f"&pblancNo={pblanc_no}"
                pblanc_url = (
                    "https://www.applyhome.co.kr/ai/aia/"
                    f"selectAPTLttotPblancDetail.do?{query}"
                )

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
                    # MVNG_BLNK_AT은 무주택 자격요건 필드가 아니다.
                    eligibility_homeless=None,
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
