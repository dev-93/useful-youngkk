"""설정 관리 모듈.

환경변수에서 애플리케이션 설정을 로드하고 검증한다.
"""

import logging
import os
from dataclasses import dataclass, field
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TelegramConfig:
    """텔레그램 봇 설정."""

    bot_token: str
    channel_id: str
    admin_chat_id: str


@dataclass(frozen=True)
class NotionConfig:
    """노션 API 설정."""

    access_token: str
    database_id: str  # 원본 database ID (pages.create용)
    data_source_id: str  # data source ID (data_sources.query용)
    calendar_share_url: str


@dataclass(frozen=True)
class DatabaseConfig:
    """데이터베이스 설정."""

    url: str


@dataclass(frozen=True)
class SchedulerConfig:
    """스케줄러 설정."""

    crawl_hours: list[int] = field(default_factory=lambda: [11, 17])
    weekly_summary_day: str = "mon"
    weekly_summary_hour: int = 9


@dataclass(frozen=True)
class LoggingConfig:
    """로깅 설정."""

    level: str = "INFO"
    log_dir: str = "./logs"


@dataclass(frozen=True)
class Settings:
    """전체 애플리케이션 설정."""

    telegram: TelegramConfig
    notion: NotionConfig
    database: DatabaseConfig
    scheduler: SchedulerConfig
    logging: LoggingConfig
    public_data_api_key: str | None = None


def _get_env(key: str, default: str | None = None) -> str:
    """환경변수를 가져온다. 필수 변수가 없으면 ValueError를 발생시킨다."""
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"필수 환경변수 '{key}'가 설정되지 않았습니다.")
    return value.strip()


def load_settings() -> Settings:
    """환경변수에서 설정을 로드한다."""
    crawl_hours_str = _get_env("CRAWL_SCHEDULE_HOURS", "11,17")
    crawl_hours = [int(h.strip()) for h in crawl_hours_str.split(",")]

    return Settings(
        telegram=TelegramConfig(
            bot_token=_get_env("TELEGRAM_BOT_TOKEN"),
            channel_id=_get_env("TELEGRAM_CHANNEL_ID"),
            admin_chat_id=_get_env("TELEGRAM_ADMIN_CHAT_ID"),
        ),
        notion=NotionConfig(
            access_token=_get_env("NOTION_ACCESS_TOKEN"),
            database_id=_get_env("NOTION_DATABASE_ID"),
            data_source_id=_get_env("NOTION_DATA_SOURCE_ID"),
            calendar_share_url=_get_env("NOTION_CALENDAR_SHARE_URL"),
        ),
        database=DatabaseConfig(
            url=_get_env("DATABASE_URL", "sqlite:///data/bot.db"),
        ),
        scheduler=SchedulerConfig(
            crawl_hours=crawl_hours,
            weekly_summary_day=_get_env("WEEKLY_SUMMARY_DAY", "mon"),
            weekly_summary_hour=int(_get_env("WEEKLY_SUMMARY_HOUR", "9")),
        ),
        logging=LoggingConfig(
            level=_get_env("LOG_LEVEL", "INFO"),
            log_dir=_get_env("LOG_DIR", "./logs"),
        ),
        public_data_api_key=os.environ.get("PUBLIC_DATA_API_KEY"),
    )


def setup_logging(config: LoggingConfig | None = None) -> None:
    """로깅을 설정한다. 일별 파일 로테이션(7일 보관) + 콘솔 출력."""
    if config is None:
        config = LoggingConfig()

    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.level.upper(), logging.INFO)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 기존 핸들러 제거
    root_logger.handlers.clear()

    # 포맷터
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 파일 핸들러 (일별 로테이션, 7일 보관)
    file_handler = TimedRotatingFileHandler(
        filename=log_dir / "bot.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(file_handler)

    logging.info("로깅 설정 완료: level=%s, dir=%s", config.level, config.log_dir)
