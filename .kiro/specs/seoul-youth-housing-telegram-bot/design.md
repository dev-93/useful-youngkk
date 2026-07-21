# Technical Design Document

## Overview

서울 청년 주거 정보 텔레그램 채널 봇의 기술 설계. Python 기반으로 크롤러, 노티파이어, 캘린더 매니저를 구성하고, 텔레그램 채널 포스팅과 노션 DB 연동을 자동화한다.

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler (APScheduler / cron)         │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ 평일 11시 │  │ 평일 17시     │  │ 월요일 09시        │  │
│  │ 평일 17시 │  │ (마감전일 9시) │  │ (마감전일 09시)    │  │
│  └─────┬────┘  └──────┬───────┘  └─────────┬─────────┘  │
└────────┼───────────────┼────────────────────┼────────────┘
         │               │                    │
         ▼               ▼                    ▼
┌─────────────┐  ┌─────────────┐     ┌─────────────────┐
│   Crawler   │  │  Notifier   │     │ Weekly Summary  │
│             │  │             │     │   Generator     │
│ - SH공사    │  │ - 채널포스팅 │     │                 │
│ - LH공사    │  │ - 리마인더   │     │ - 주간요약      │
│ - 마이홈    │  │ - 재시도     │     │ - 마감리마인더  │
└──────┬──────┘  └──────┬──────┘     └────────┬────────┘
       │                │                     │
       ▼                ▼                     │
┌─────────────────────────────┐               │
│        SQLite DB            │               │
│  - announcements            │               │
│  - crawl_logs               │               │
│  - post_history             │               │
└──────────────┬──────────────┘               │
               │                              │
               ▼                              ▼
┌─────────────────────┐         ┌─────────────────────┐
│   Notion API        │         │  Telegram Bot API   │
│   (Calendar DB)     │         │  (Channel Post)     │
└─────────────────────┘         └─────────────────────┘
```

## Components and Interfaces

#### 1. Crawler Module (`src/crawler/`)
- **역할**: 외부 사이트에서 청약 공고를 수집하여 구조화된 데이터로 저장
- **기술**: Python + requests/httpx + BeautifulSoup4
- **사이트별 파서**: 각 사이트(SH, LH, 마이홈)별 파싱 로직을 개별 클래스로 구현
- **중복 판별**: `(source_site, source_id)` 복합키로 판별

#### 2. Notifier Module (`src/notifier/`)
- **역할**: 텔레그램 채널에 메시지 포스팅
- **기술**: python-telegram-bot 라이브러리
- **메시지 포맷**: Markdown v2 형식으로 구조화된 메시지 생성
- **재시도**: 30초 간격, 최대 3회

#### 3. Calendar Manager (`src/calendar/`)
- **역할**: 노션 DB에 일정 자동 등록 및 상태 관리
- **기술**: notion-client (공식 Python SDK)
- **상태 관리**: 예정 → 진행중 → 마감 자동 전환

#### 4. Scheduler (`src/scheduler/`)
- **역할**: 크롤링, 포스팅, 요약 작업 스케줄링
- **기술**: APScheduler 또는 시스템 cron
- **스케줄**:
  - 평일 11:00, 17:00 → 크롤링 실행
  - 크롤링 완료 후 즉시 → 새 공고 포스팅 + 노션 등록
  - 월요일 09:00 → 주간 요약 포스팅
  - 매일 09:00 → 마감 전일 리마인더 체크

#### 5. Database (`src/db/`)
- **기술**: SQLite (초기 단순 운영, 필요시 PostgreSQL 마이그레이션)
- **테이블**: announcements, crawl_logs, post_history

## Data Models

### announcements 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 ID |
| source_site | TEXT | 출처 (sh, lh, myhome) |
| source_id | TEXT | 출처 사이트 내 고유 ID |
| title | TEXT | 공고명 |
| housing_type | TEXT | 모집 유형 (행복주택, 공공임대 등) |
| start_date | DATE | 모집 시작일 |
| end_date | DATE | 모집 마감일 |
| result_date | DATE | 당첨자 발표일 (nullable) |
| target_region | TEXT | 대상 지역 |
| eligibility_age | TEXT | 나이 조건 |
| eligibility_income | TEXT | 소득 기준 |
| eligibility_homeless | TEXT | 무주택 요건 |
| eligibility_residence | TEXT | 거주 기간 요건 |
| original_url | TEXT | 원문 링크 |
| status | TEXT | 상태 (incomplete, active, archived) |
| created_at | DATETIME | 수집 시각 |
| notion_page_id | TEXT | 노션 페이지 ID (nullable) |

### crawl_logs 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 ID |
| source_site | TEXT | 크롤링 대상 사이트 |
| started_at | DATETIME | 크롤링 시작 시각 |
| finished_at | DATETIME | 크롤링 완료 시각 |
| status | TEXT | 성공/실패 |
| new_count | INTEGER | 신규 공고 수 |
| error_message | TEXT | 오류 메시지 (nullable) |
| retry_count | INTEGER | 재시도 횟수 |

### post_history 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 ID |
| announcement_id | INTEGER FK | 공고 ID |
| post_type | TEXT | 유형 (new, weekly, reminder) |
| posted_at | DATETIME | 포스팅 시각 |
| status | TEXT | 성공/실패 |
| telegram_message_id | TEXT | 텔레그램 메시지 ID |
| error_message | TEXT | 오류 메시지 (nullable) |

## Project Structure

```
seoul-youth-housing-telegram-bot/
├── src/
│   ├── __init__.py
│   ├── main.py                 # 진입점, 스케줄러 초기화
│   ├── config.py               # 환경변수, 설정값 관리
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseCrawler 추상 클래스
│   │   ├── sh_crawler.py       # SH서울주택도시공사 크롤러
│   │   ├── lh_crawler.py       # LH한국토지주택공사 크롤러
│   │   ├── myhome_crawler.py   # 마이홈 포털 크롤러
│   │   └── parser.py           # 자격요건 파싱 유틸
│   ├── notifier/
│   │   ├── __init__.py
│   │   ├── telegram.py         # 텔레그램 채널 포스팅
│   │   ├── formatter.py        # 메시지 포맷팅 (Markdown v2)
│   │   └── weekly_summary.py   # 주간 요약 생성
│   ├── calendar/
│   │   ├── __init__.py
│   │   └── notion_client.py    # 노션 API 연동
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy 모델
│   │   ├── repository.py       # 데이터 접근 레이어
│   │   └── migrations/         # DB 마이그레이션
│   └── scheduler/
│       ├── __init__.py
│       └── jobs.py             # 스케줄 작업 정의
├── tests/
│   ├── test_crawler.py
│   ├── test_notifier.py
│   ├── test_calendar.py
│   └── test_scheduler.py
├── .env.example                # 환경변수 템플릿
├── requirements.txt
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Configuration

### 환경변수 (.env)

```
# Telegram
TELEGRAM_BOT_TOKEN=<봇 토큰>
TELEGRAM_CHANNEL_ID=<채널 ID>
TELEGRAM_ADMIN_CHAT_ID=<관리자 채팅 ID>

# Notion
NOTION_API_KEY=<노션 API 키>
NOTION_DATABASE_ID=<노션 DB ID>
NOTION_CALENDAR_SHARE_URL=<공유 링크>

# Database
DATABASE_URL=sqlite:///data/bot.db

# Scheduler
CRAWL_SCHEDULE_HOURS=11,17
WEEKLY_SUMMARY_DAY=mon
WEEKLY_SUMMARY_HOUR=9

# Logging
LOG_LEVEL=INFO
LOG_DIR=./logs
```

## Key Flows

### 크롤링 → 포스팅 플로우

1. Scheduler가 평일 11시/17시에 크롤링 작업 트리거
2. Crawler가 3개 사이트 순차 크롤링 실행
3. 새 공고 감지 시 DB에 저장 (중복 체크)
4. Notifier가 새 공고를 텔레그램 채널에 포스팅
5. Calendar Manager가 노션 DB에 일정 등록
6. 모든 결과를 crawl_logs, post_history에 기록

### 주간 요약 플로우

1. Scheduler가 월요일 09시에 주간 요약 작업 트리거
2. DB에서 해당 주(월~일) 마감 예정 공고 조회
3. 포맷팅된 요약 메시지 생성
4. 텔레그램 채널에 포스팅

### 마감 리마인더 플로우

1. Scheduler가 매일 09시에 마감 리마인더 체크 작업 트리거
2. DB에서 내일 마감 예정인 공고 조회
3. "내일 마감" 리마인더 메시지 생성
4. 텔레그램 채널에 포스팅

## Technology Stack

| 영역 | 기술 | 이유 |
|------|------|------|
| 언어 | Python 3.11+ | 크롤링/봇 생태계 풍부, 빠른 개발 |
| 크롤링 | httpx + BeautifulSoup4 | 비동기 HTTP + HTML 파싱 |
| 텔레그램 | python-telegram-bot | 공식 지원, 안정적 |
| 노션 | notion-client | 공식 SDK |
| DB | SQLite + SQLAlchemy | 초기 단순 운영, ORM 사용 |
| 스케줄러 | APScheduler | Python 내장 스케줄링 |
| 배포 | Docker + docker-compose | 환경 일관성 |
| 로깅 | Python logging + 파일 로테이션 | 운영 로그 관리 |

## Error Handling

- **크롤링 실패**: 30분 후 재시도, 최대 3회. 모든 실패 로그 기록.
- **포스팅 실패**: 30초 간격 재시도, 최대 3회. 최종 실패 시 관리자 알림.
- **노션 API 실패**: 즉시 재시도, 최대 3회. DB 저장은 독립적으로 성공 처리.
- **전체 장애**: 관리자 텔레그램 DM으로 알림 전송.

## Testing Strategy

- **Unit Tests**: 각 크롤러 파서, 메시지 포맷터, DB 리포지토리 단위 테스트
- **Integration Tests**: 크롤링→저장→포스팅 전체 플로우 통합 테스트 (모킹 활용)
- **E2E Tests**: 실제 텔레그램 테스트 채널 + 노션 테스트 DB로 전체 동작 확인

## Correctness Properties

### Property 1: 중복 공고 방지
동일 공고는 `(source_site, source_id)` 복합키 유니크 제약조건으로 중복 저장을 방지한다.

**Validates: Requirements 1.4**

### Property 2: 모듈 독립성
크롤링 실패가 기존 데이터에 영향을 주지 않으며, 노션 API 실패가 텔레그램 포스팅을 차단하지 않는다. 각 외부 서비스 호출은 독립적으로 실행된다.

**Validates: Requirements 1.3, 2.3, 4.4**

### Property 3: 마감 공고 자동 제외
마감일이 경과한 공고는 주간 요약 및 리마인더 대상에서 자동으로 제외되며, 노션 DB 상태가 "마감"으로 변경된다.

**Validates: Requirements 4.3, 6.2**

### Property 4: 재시도 상한
모든 재시도 로직은 최대 3회로 제한하여 무한 루프를 방지하며, 최종 실패 시 로그 기록 후 다음 스케줄로 넘어간다.

**Validates: Requirements 1.3, 2.3, 6.3**

## Deployment

- Docker 컨테이너로 패키징
- docker-compose로 로컬/서버 배포
- 초기에는 단일 서버(VPS 또는 클라우드 인스턴스)에서 운영
- 데이터 볼륨 마운트로 DB 파일 영속성 보장
