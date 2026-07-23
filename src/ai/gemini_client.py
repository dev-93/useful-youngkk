"""Gemini API를 활용한 공고 자격요건 추출 모듈.

크롤링으로 파싱하기 어려운 자격요건 정보를 Gemini AI로 보충한다.
공고 상세 페이지 텍스트를 기반으로 추출하여 환각을 최소화한다.
"""

import json
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

EXTRACTION_PROMPT = """아래는 공공주택 청약 공고 텍스트입니다. 이 공고에서 자격요건 정보를 정확히 추출해주세요.

반드시 공고 텍스트에 명시된 정보만 추출하세요. 텍스트에 없는 정보는 null로 응답하세요.
추측하거나 일반 지식으로 채우지 마세요.

JSON 형식으로만 응답하세요:
{
  "age": "나이 조건 (예: 만 19~39세) 또는 null",
  "income": "소득 기준 (예: 도시근로자 월평균소득 100% 이하) 또는 null",
  "homeless": "무주택 요건 (예: 무주택 세대구성원) 또는 null",
  "residence": "거주 기간 요건 (예: 서울 거주 1년 이상) 또는 null",
  "confidence": "high/medium/low - 정보 추출 확신도"
}

---
공고 제목: {title}
공고 유형: {housing_type}
---
공고 텍스트:
{text}
"""

FALLBACK_PROMPT = """아래 공공주택 청약 공고의 자격요건을 알려주세요.
공고 상세 텍스트가 없어서 해당 주택 유형의 일반적인 자격요건을 알려주세요.

반드시 JSON 형식으로만 응답하세요:
{{
  "age": "나이 조건 또는 null",
  "income": "소득 기준 또는 null",
  "homeless": "무주택 요건 또는 null",
  "residence": "거주 기간 요건 또는 null",
  "confidence": "low",
  "is_general_info": true
}}

공고 제목: {title}
공고 유형: {housing_type}
공급 지역: {region}
"""


@dataclass
class EligibilityResult:
    """Gemini에서 추출한 자격요건 결과."""

    age: str | None = None
    income: str | None = None
    homeless: str | None = None
    residence: str | None = None
    confidence: str = "low"
    is_general_info: bool = False


class GeminiClient:
    """Gemini API 클라이언트.

    공고 텍스트에서 자격요건을 추출하거나,
    텍스트가 부족한 경우 일반 지식 기반 보충을 수행한다.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.client = httpx.Client(timeout=30.0)

    def extract_eligibility(
        self,
        title: str,
        housing_type: str | None,
        detail_text: str | None,
        region: str | None = None,
    ) -> EligibilityResult:
        """공고에서 자격요건을 추출한다.

        detail_text가 있으면 텍스트 기반 추출 (정확도 높음).
        없으면 일반 지식 기반 보충 (confidence=low 표시).

        Args:
            title: 공고 제목.
            housing_type: 주택 유형.
            detail_text: 공고 상세 페이지 텍스트 (있으면 우선 사용).
            region: 공급 지역.

        Returns:
            추출된 자격요건 결과.
        """
        if detail_text and len(detail_text.strip()) > 100:
            return self._extract_from_text(title, housing_type, detail_text)
        else:
            return self._fallback_general(title, housing_type, region)

    def _extract_from_text(
        self, title: str, housing_type: str | None, text: str
    ) -> EligibilityResult:
        """공고 텍스트에서 직접 추출한다."""
        # 텍스트가 너무 길면 앞부분만 (토큰 절약)
        truncated_text = text[:3000]

        prompt = EXTRACTION_PROMPT.format(
            title=title,
            housing_type=housing_type or "미정",
            text=truncated_text,
        )

        response_text = self._call_gemini(prompt)
        return self._parse_response(response_text)

    def _fallback_general(
        self, title: str, housing_type: str | None, region: str | None
    ) -> EligibilityResult:
        """일반 지식 기반으로 보충한다."""
        prompt = FALLBACK_PROMPT.format(
            title=title,
            housing_type=housing_type or "미정",
            region=region or "서울",
        )

        response_text = self._call_gemini(prompt)
        result = self._parse_response(response_text)
        result.is_general_info = True
        result.confidence = "low"
        return result

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API를 호출한다."""
        url = f"{GEMINI_API_URL}?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,  # 낮은 temperature로 환각 최소화
                "topP": 0.8,
                "maxOutputTokens": 500,
            },
        }

        try:
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")

            logger.warning("Gemini 응답에 텍스트 없음")
            return ""

        except Exception as e:
            logger.error("Gemini API 호출 실패: %s", str(e))
            return ""

    def _parse_response(self, response_text: str) -> EligibilityResult:
        """Gemini 응답을 파싱한다."""
        if not response_text:
            return EligibilityResult()

        try:
            # JSON 블록 추출 (```json ... ``` 형태 처리)
            text = response_text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())

            return EligibilityResult(
                age=data.get("age") if data.get("age") != "null" else None,
                income=data.get("income") if data.get("income") != "null" else None,
                homeless=data.get("homeless") if data.get("homeless") != "null" else None,
                residence=data.get("residence") if data.get("residence") != "null" else None,
                confidence=data.get("confidence", "low"),
                is_general_info=data.get("is_general_info", False),
            )

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("Gemini 응답 파싱 실패: %s / 응답: %s", str(e), response_text[:200])
            return EligibilityResult()
