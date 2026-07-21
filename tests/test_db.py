"""데이터베이스 모델 및 리포지토리 단위 테스트."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.db import init_db, get_session, get_session_context
from src.db.models import Announcement, Base, CrawlLog, PostHistory
from src.db.repository import (
    AnnouncementRepository,
    CrawlLogRepository,
    PostHistoryRepository,
)


@pytest.fixture
def engine():
    """인메모리 SQLite 엔진을 생성한다."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """테스트용 세션을 생성한다."""
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def sample_announcement() -> Announcement:
    """테스트용 공고 객체를 반환한다."""
    return Announcement(
        source_site="sh",
        source_id="2024-001",
        title="행복주택 신규 모집",
        housing_type="행복주택",
        start_date=date(2024, 6, 1),
        end_date=date(2024, 6, 30),
        result_date=date(2024, 7, 15),
        target_region="서울",
        eligibility_age="만 19~39세",
        eligibility_income="중위소득 100% 이하",
        eligibility_homeless="무주택자",
        eligibility_residence="서울 거주 1년 이상",
        original_url="https://www.i-sh.co.kr/example",
        status="active",
    )


class TestModels:
    """모델 정의 테스트."""

    def test_announcements_table_created(self, engine):
        """announcements 테이블이 생성되는지 확인한다."""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "announcements" in tables

    def test_crawl_logs_table_created(self, engine):
        """crawl_logs 테이블이 생성되는지 확인한다."""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "crawl_logs" in tables

    def test_post_history_table_created(self, engine):
        """post_history 테이블이 생성되는지 확인한다."""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "post_history" in tables

    def test_unique_constraint_source_site_source_id(self, session):
        """(source_site, source_id) 복합 유니크 제약조건을 확인한다."""
        a1 = Announcement(
            source_site="sh",
            source_id="001",
            title="첫번째 공고",
            status="active",
        )
        a2 = Announcement(
            source_site="sh",
            source_id="001",
            title="중복 공고",
            status="active",
        )
        session.add(a1)
        session.commit()

        session.add(a2)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_different_source_site_same_id_allowed(self, session):
        """다른 source_site의 동일 source_id는 허용된다."""
        a1 = Announcement(
            source_site="sh",
            source_id="001",
            title="SH 공고",
            status="active",
        )
        a2 = Announcement(
            source_site="lh",
            source_id="001",
            title="LH 공고",
            status="active",
        )
        session.add_all([a1, a2])
        session.commit()
        assert a1.id is not None
        assert a2.id is not None

    def test_post_history_foreign_key(self, session, sample_announcement):
        """post_history의 announcement_id FK가 동작하는지 확인한다."""
        session.add(sample_announcement)
        session.flush()

        history = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="new",
            status="success",
            telegram_message_id="123",
        )
        session.add(history)
        session.commit()
        assert history.announcement_id == sample_announcement.id

    def test_announcement_defaults(self, session):
        """기본값이 올바르게 설정되는지 확인한다."""
        a = Announcement(
            source_site="myhome",
            source_id="999",
            title="테스트 공고",
            status="active",
        )
        session.add(a)
        session.commit()
        assert a.created_at is not None
        assert a.status == "active"


class TestAnnouncementRepository:
    """AnnouncementRepository 테스트."""

    def test_create(self, session, sample_announcement):
        """공고 생성이 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        created = repo.create(sample_announcement)
        session.commit()
        assert created.id is not None
        assert created.title == "행복주택 신규 모집"

    def test_get_by_id(self, session, sample_announcement):
        """ID로 공고 조회가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        repo.create(sample_announcement)
        session.commit()

        found = repo.get_by_id(sample_announcement.id)
        assert found is not None
        assert found.source_site == "sh"

    def test_get_by_id_not_found(self, session):
        """존재하지 않는 ID 조회 시 None을 반환한다."""
        repo = AnnouncementRepository(session)
        assert repo.get_by_id(9999) is None

    def test_exists_true(self, session, sample_announcement):
        """존재하는 공고에 대해 True를 반환한다."""
        repo = AnnouncementRepository(session)
        repo.create(sample_announcement)
        session.commit()

        assert repo.exists("sh", "2024-001") is True

    def test_exists_false(self, session):
        """존재하지 않는 공고에 대해 False를 반환한다."""
        repo = AnnouncementRepository(session)
        assert repo.exists("sh", "nonexistent") is False

    def test_get_by_source(self, session, sample_announcement):
        """(source_site, source_id)로 조회가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        repo.create(sample_announcement)
        session.commit()

        found = repo.get_by_source("sh", "2024-001")
        assert found is not None
        assert found.title == "행복주택 신규 모집"

    def test_get_active(self, session):
        """활성 공고 목록 조회가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        a1 = Announcement(
            source_site="sh", source_id="001", title="활성1",
            status="active", end_date=date(2024, 7, 1),
        )
        a2 = Announcement(
            source_site="sh", source_id="002", title="아카이브",
            status="archived", end_date=date(2024, 5, 1),
        )
        a3 = Announcement(
            source_site="lh", source_id="003", title="활성2",
            status="active", end_date=date(2024, 6, 15),
        )
        repo.create(a1)
        repo.create(a2)
        repo.create(a3)
        session.commit()

        active = repo.get_active()
        assert len(active) == 2
        # end_date 오름차순 정렬 확인
        assert active[0].title == "활성2"
        assert active[1].title == "활성1"

    def test_get_ending_between(self, session):
        """기간 내 마감 예정 공고 조회가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        a1 = Announcement(
            source_site="sh", source_id="001", title="이번주 마감",
            status="active", end_date=date(2024, 6, 5),
        )
        a2 = Announcement(
            source_site="sh", source_id="002", title="다음주 마감",
            status="active", end_date=date(2024, 6, 15),
        )
        repo.create(a1)
        repo.create(a2)
        session.commit()

        result = repo.get_ending_between(date(2024, 6, 3), date(2024, 6, 9))
        assert len(result) == 1
        assert result[0].title == "이번주 마감"

    def test_get_ending_on(self, session):
        """특정 날짜 마감 공고 조회가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        a1 = Announcement(
            source_site="sh", source_id="001", title="내일 마감",
            status="active", end_date=date(2024, 6, 5),
        )
        a2 = Announcement(
            source_site="sh", source_id="002", title="다른날 마감",
            status="active", end_date=date(2024, 6, 10),
        )
        repo.create(a1)
        repo.create(a2)
        session.commit()

        result = repo.get_ending_on(date(2024, 6, 5))
        assert len(result) == 1
        assert result[0].title == "내일 마감"

    def test_update_status(self, session, sample_announcement):
        """공고 상태 업데이트가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        repo.create(sample_announcement)
        session.commit()

        updated = repo.update_status(sample_announcement.id, "archived")
        session.commit()
        assert updated is not None
        assert updated.status == "archived"

    def test_update_notion_page_id(self, session, sample_announcement):
        """노션 페이지 ID 업데이트가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        repo.create(sample_announcement)
        session.commit()

        updated = repo.update_notion_page_id(sample_announcement.id, "page-123")
        session.commit()
        assert updated is not None
        assert updated.notion_page_id == "page-123"

    def test_archive_expired(self, session):
        """90일 경과 공고 아카이브 처리가 동작하는지 확인한다."""
        repo = AnnouncementRepository(session)
        old_date = date.today() - timedelta(days=91)
        recent_date = date.today() - timedelta(days=30)

        a1 = Announcement(
            source_site="sh", source_id="old", title="오래된 공고",
            status="active", end_date=old_date,
        )
        a2 = Announcement(
            source_site="sh", source_id="recent", title="최근 공고",
            status="active", end_date=recent_date,
        )
        repo.create(a1)
        repo.create(a2)
        session.commit()

        archived_count = repo.archive_expired(days=90)
        session.commit()

        assert archived_count == 1
        assert repo.get_by_id(a1.id).status == "archived"
        assert repo.get_by_id(a2.id).status == "active"


class TestCrawlLogRepository:
    """CrawlLogRepository 테스트."""

    def test_create(self, session):
        """크롤링 로그 생성이 동작하는지 확인한다."""
        repo = CrawlLogRepository(session)
        log = CrawlLog(
            source_site="sh",
            started_at=datetime(2024, 6, 1, 11, 0, 0),
            status="running",
        )
        created = repo.create(log)
        session.commit()
        assert created.id is not None

    def test_update_finished(self, session):
        """크롤링 완료 업데이트가 동작하는지 확인한다."""
        repo = CrawlLogRepository(session)
        log = CrawlLog(
            source_site="sh",
            started_at=datetime(2024, 6, 1, 11, 0, 0),
            status="running",
        )
        repo.create(log)
        session.commit()

        updated = repo.update_finished(log.id, status="success", new_count=3)
        session.commit()
        assert updated is not None
        assert updated.status == "success"
        assert updated.new_count == 3
        assert updated.finished_at is not None

    def test_get_latest_by_site(self, session):
        """사이트별 최근 로그 조회가 동작하는지 확인한다."""
        repo = CrawlLogRepository(session)
        log1 = CrawlLog(
            source_site="sh",
            started_at=datetime(2024, 6, 1, 11, 0, 0),
            status="success",
        )
        log2 = CrawlLog(
            source_site="sh",
            started_at=datetime(2024, 6, 2, 11, 0, 0),
            status="success",
        )
        repo.create(log1)
        repo.create(log2)
        session.commit()

        latest = repo.get_latest_by_site("sh")
        assert latest is not None
        assert latest.started_at == datetime(2024, 6, 2, 11, 0, 0)


class TestPostHistoryRepository:
    """PostHistoryRepository 테스트."""

    def test_create(self, session, sample_announcement):
        """포스팅 이력 생성이 동작하는지 확인한다."""
        session.add(sample_announcement)
        session.flush()

        repo = PostHistoryRepository(session)
        history = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="new",
            status="success",
            telegram_message_id="msg-001",
        )
        created = repo.create(history)
        session.commit()
        assert created.id is not None

    def test_get_by_announcement(self, session, sample_announcement):
        """공고별 포스팅 이력 조회가 동작하는지 확인한다."""
        session.add(sample_announcement)
        session.flush()

        repo = PostHistoryRepository(session)
        h1 = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="new",
            posted_at=datetime(2024, 6, 1, 12, 0),
            status="success",
        )
        h2 = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="reminder",
            posted_at=datetime(2024, 6, 28, 9, 0),
            status="success",
        )
        repo.create(h1)
        repo.create(h2)
        session.commit()

        histories = repo.get_by_announcement(sample_announcement.id)
        assert len(histories) == 2

    def test_has_been_posted_true(self, session, sample_announcement):
        """이미 포스팅된 경우 True를 반환한다."""
        session.add(sample_announcement)
        session.flush()

        repo = PostHistoryRepository(session)
        h = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="new",
            status="success",
        )
        repo.create(h)
        session.commit()

        assert repo.has_been_posted(sample_announcement.id, "new") is True

    def test_has_been_posted_false(self, session, sample_announcement):
        """포스팅되지 않은 경우 False를 반환한다."""
        session.add(sample_announcement)
        session.flush()
        session.commit()

        repo = PostHistoryRepository(session)
        assert repo.has_been_posted(sample_announcement.id, "new") is False

    def test_has_been_posted_failed_not_counted(self, session, sample_announcement):
        """실패한 포스팅은 포스팅 완료로 카운트되지 않는다."""
        session.add(sample_announcement)
        session.flush()

        repo = PostHistoryRepository(session)
        h = PostHistory(
            announcement_id=sample_announcement.id,
            post_type="new",
            status="failed",
            error_message="API timeout",
        )
        repo.create(h)
        session.commit()

        assert repo.has_been_posted(sample_announcement.id, "new") is False


class TestInitDb:
    """DB 초기화 함수 테스트."""

    def test_init_db_creates_tables(self, tmp_path):
        """init_db가 테이블을 생성하는지 확인한다."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"

        engine = init_db(db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        assert "announcements" in tables
        assert "crawl_logs" in tables
        assert "post_history" in tables

    def test_get_session_after_init(self, tmp_path):
        """init_db 이후 get_session이 동작하는지 확인한다."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        init_db(db_url)

        session = get_session()
        assert session is not None
        session.close()

    def test_get_session_context_commit(self, tmp_path):
        """get_session_context가 정상 종료 시 commit하는지 확인한다."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"
        init_db(db_url)

        gen = get_session_context()
        session = next(gen)
        a = Announcement(
            source_site="sh", source_id="ctx-001", title="컨텍스트 테스트",
            status="active",
        )
        session.add(a)
        try:
            gen.send(None)
        except StopIteration:
            pass

        # 새 세션으로 확인
        new_session = get_session()
        found = new_session.query(Announcement).filter_by(source_id="ctx-001").first()
        assert found is not None
        new_session.close()
