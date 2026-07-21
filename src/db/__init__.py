"""데이터베이스 초기화 및 세션 관리.

SQLAlchemy 엔진과 세션 팩토리를 제공한다.
"""

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def init_db(database_url: str) -> Engine:
    """데이터베이스를 초기화하고 테이블을 생성한다.

    Args:
        database_url: SQLAlchemy 데이터베이스 URL.

    Returns:
        생성된 SQLAlchemy Engine.
    """
    global _engine, _SessionFactory

    # SQLite 파일 경로의 디렉토리가 없으면 생성
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            Path(db_dir).mkdir(parents=True, exist_ok=True)

    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)

    Base.metadata.create_all(_engine)
    logger.info("데이터베이스 초기화 완료: %s", database_url)

    return _engine


def get_session() -> Session:
    """새 세션을 생성하여 반환한다.

    Returns:
        SQLAlchemy Session 인스턴스.

    Raises:
        RuntimeError: DB가 초기화되지 않은 경우.
    """
    if _SessionFactory is None:
        raise RuntimeError("데이터베이스가 초기화되지 않았습니다. init_db()를 먼저 호출하세요.")
    return _SessionFactory()


def get_session_context() -> Generator[Session, None, None]:
    """컨텍스트 매니저로 세션을 관리한다.

    Yields:
        SQLAlchemy Session. 정상 종료 시 commit, 예외 시 rollback.
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
