"""자격요건 파싱 유틸리티.

공고 본문에서 나이, 소득, 무주택, 거주 기간 요건을 추출한다.
"""

import re
from dataclasses import dataclass
from datetime import date


@dataclass
class EligibilityInfo:
    """자격요건 파싱 결과."""

    age: str | None = None
    income: str | None = None
    homeless: str | None = None
    residence_period: str | None = None


def parse_eligibility(text: str) -> EligibilityInfo:
    """공고 텍스트에서 자격요건 정보를 추출한다.

    Args:
        text: 공고 상세 페이지 본문 텍스트.

    Returns:
        추출된 자격요건 정보.
    """
    info = EligibilityInfo()
    info.age = _extract_age(text)
    info.income = _extract_income(text)
    info.homeless = _extract_homeless(text)
    info.residence_period = _extract_residence_period(text)
    return info


def _extract_age(text: str) -> str | None:
    """나이 조건을 추출한다."""
    patterns = [
        r"만\s*(\d+)\s*세\s*[~이상]*\s*(?:~|이상|부터)\s*(?:만\s*)?(\d+)\s*세\s*(?:이하|미만|까지)?",
        r"만\s*(\d+)\s*세\s*(?:이상|부터)\s*(?:만\s*)?(\d+)\s*세\s*(?:이하|미만|까지)",
        r"(\d+)\s*세\s*[~\-]\s*(\d+)\s*세",
        r"만\s*(\d+)\s*세\s*(?:이상|이하|미만|초과)",
        r"(\d+)\s*세\s*(?:이상|이하|미만|초과)",
        r"청년.*?(\d+)\s*세",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return None


def _extract_income(text: str) -> str | None:
    """소득 기준을 추출한다."""
    patterns = [
        r"(?:도시근로자\s*)?(?:월평균\s*)?소득\s*(\d+)\s*%\s*(?:이하|이내)",
        r"중위소득\s*(\d+)\s*%\s*(?:이하|이내)",
        r"기준\s*중위소득\s*(\d+)\s*%",
        r"소득\s*\d+[만원,\s]*(?:이하|이내|미만)",
        r"(\d+)\s*%\s*(?:이하|이내).*?소득",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return None


def _extract_homeless(text: str) -> str | None:
    """무주택 요건을 추출한다."""
    patterns = [
        r"무주택\s*(?:세대구성원|자|기간|요건|조건)?(?:\s*\d+\s*년)?",
        r"주택\s*(?:미소유|미보유)(?:\s*\d+\s*년)?",
        r"무주택\s*(?:기간\s*)?(\d+)\s*년\s*(?:이상)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return None


def _extract_residence_period(text: str) -> str | None:
    """거주 기간 요건을 추출한다."""
    patterns = [
        r"(?:서울|수도권|해당\s*지역)\s*(?:거주|거주기간)\s*(\d+)\s*(?:년|개월)\s*(?:이상)?",
        r"(?:거주|거주기간)\s*(\d+)\s*(?:년|개월)\s*(?:이상)?",
        r"(\d+)\s*(?:년|개월)\s*(?:이상)?\s*(?:거주|계속\s*거주)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return None


def parse_date(text: str) -> date | None:
    """날짜 문자열을 date 객체로 변환한다.

    지원 형식:
    - YYYY.MM.DD
    - YYYY-MM-DD
    - YYYY/MM/DD
    - YYYY년 MM월 DD일

    Args:
        text: 날짜 문자열.

    Returns:
        파싱된 date 객체 또는 None.
    """
    if not text:
        return None

    text = text.strip()

    patterns = [
        (r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", None),
        (r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", None),
    ]

    for pattern, _ in patterns:
        match = re.search(pattern, text)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                continue

    return None
