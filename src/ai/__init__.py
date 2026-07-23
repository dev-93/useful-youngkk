"""AI 모듈.

Gemini API를 활용한 공고 자격요건 추출 및 보충.
"""

from src.ai.gemini_client import EligibilityResult, GeminiClient

__all__ = ["EligibilityResult", "GeminiClient"]
