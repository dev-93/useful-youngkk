"""config 모듈 테스트."""

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import (
    LoggingConfig,
    Settings,
    load_settings,
    setup_logging,
)


@pytest.fixture
def env_vars():
    """테스트용 환경변수를 설정한다."""
    env = {
        "TELEGRAM_BOT_TOKEN": "test-token-123",
        "TELEGRAM_CHANNEL_ID": "@test_channel",
        "TELEGRAM_ADMIN_CHAT_ID": "123456789",
        "NOTION_ACCESS_TOKEN": "secret_test_key",
        "NOTION_DATABASE_ID": "test-db-id",
        "NOTION_DATA_SOURCE_ID": "test-ds-id",
        "NOTION_CALENDAR_SHARE_URL": "https://notion.so/test",
        "DATABASE_URL": "sqlite:///test.db",
        "CRAWL_SCHEDULE_HOURS": "11,17",
        "WEEKLY_SUMMARY_DAY": "mon",
        "WEEKLY_SUMMARY_HOUR": "9",
        "LOG_LEVEL": "DEBUG",
        "LOG_DIR": "./test_logs",
    }
    with patch.dict(os.environ, env, clear=False):
        yield env


class TestLoadSettings:
    """load_settings 함수 테스트."""

    def test_loads_all_settings(self, env_vars):
        """모든 설정이 환경변수에서 올바르게 로드되는지 확인한다."""
        settings = load_settings()

        assert isinstance(settings, Settings)
        assert settings.telegram.bot_token == "test-token-123"
        assert settings.telegram.channel_id == "@test_channel"
        assert settings.telegram.admin_chat_id == "123456789"
        assert settings.notion.access_token == "secret_test_key"
        assert settings.notion.database_id == "test-db-id"
        assert settings.notion.calendar_share_url == "https://notion.so/test"
        assert settings.database.url == "sqlite:///test.db"
        assert settings.scheduler.crawl_hours == [11, 17]
        assert settings.scheduler.weekly_summary_day == "mon"
        assert settings.scheduler.weekly_summary_hour == 9
        assert settings.logging.level == "DEBUG"
        assert settings.logging.log_dir == "./test_logs"

    def test_raises_on_missing_required_env(self):
        """필수 환경변수가 없으면 ValueError를 발생시킨다."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
                load_settings()

    def test_uses_defaults_for_optional_env(self, env_vars):
        """선택적 환경변수는 기본값을 사용한다."""
        env_without_optional = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHANNEL_ID": "@ch",
            "TELEGRAM_ADMIN_CHAT_ID": "123",
            "NOTION_ACCESS_TOKEN": "key",
            "NOTION_DATABASE_ID": "db",
        "NOTION_DATA_SOURCE_ID": "test-ds-id",
            "NOTION_CALENDAR_SHARE_URL": "url",
        }
        with patch.dict(os.environ, env_without_optional, clear=True):
            settings = load_settings()

        assert settings.database.url == "sqlite:///data/bot.db"
        assert settings.scheduler.crawl_hours == [11, 17]
        assert settings.scheduler.weekly_summary_day == "mon"
        assert settings.scheduler.weekly_summary_hour == 9
        assert settings.logging.level == "INFO"
        assert settings.logging.log_dir == "./logs"

    def test_parses_crawl_hours(self, env_vars):
        """CRAWL_SCHEDULE_HOURS를 정수 리스트로 파싱한다."""
        with patch.dict(os.environ, {**env_vars, "CRAWL_SCHEDULE_HOURS": "9,12,18"}):
            settings = load_settings()

        assert settings.scheduler.crawl_hours == [9, 12, 18]


class TestSetupLogging:
    """setup_logging 함수 테스트."""

    def test_creates_log_directory(self):
        """로그 디렉토리가 없으면 생성한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "new_logs"
            config = LoggingConfig(level="INFO", log_dir=str(log_dir))

            setup_logging(config)

            assert log_dir.exists()

    def test_configures_root_logger(self):
        """루트 로거가 올바르게 설정된다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LoggingConfig(level="WARNING", log_dir=tmpdir)

            setup_logging(config)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.WARNING
            # 콘솔 + 파일 핸들러 2개
            assert len(root_logger.handlers) == 2

    def test_creates_log_file(self):
        """로그 파일이 생성된다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LoggingConfig(level="INFO", log_dir=tmpdir)

            setup_logging(config)
            logging.info("테스트 로그 메시지")

            log_file = Path(tmpdir) / "bot.log"
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8")
            assert "테스트 로그 메시지" in content
