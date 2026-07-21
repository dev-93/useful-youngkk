# 서울 청년 주거 정보 텔레그램 봇 🏠

서울 청년(만 19~39세)을 위한 공공임대·행복주택 청약 정보를 **텔레그램 채널**로 자동 전달하는 봇입니다.

## 📋 주요 기능

| 기능 | 설명 |
|------|------|
| 🔍 자동 크롤링 | SH공사, LH공사, 마이홈 포털에서 평일 2회 공고 수집 |
| 📢 채널 포스팅 | 새 공고 발견 시 텔레그램 채널에 자동 알림 |
| 📋 자격요건 요약 | 나이·소득·무주택 등 핵심 조건을 한눈에 정리 |
| 📅 노션 캘린더 | 청약 일정을 노션 DB로 자동 관리 |
| 📊 주간 요약 | 매주 월요일 이번 주 마감 공고 정리 |
| ⏰ 마감 리마인더 | 마감 전일 알림으로 신청 기한 안내 |

## 🏗️ 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler (APScheduler)                │
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

## ⚙️ 기술 스택

| 영역 | 기술 | 버전 |
|------|------|------|
| 언어 | Python | 3.11+ |
| 크롤링 | httpx + BeautifulSoup4 | httpx ≥0.27, bs4 ≥4.12 |
| 텔레그램 | python-telegram-bot | ≥21.3 |
| 노션 | notion-client | ≥2.2.1 |
| DB | SQLite + SQLAlchemy | SQLAlchemy ≥2.0 |
| 스케줄러 | APScheduler | ≥3.10 |
| 배포 | Docker + docker-compose | - |


## 🚀 빠른 시작

### 사전 준비

1. [텔레그램 봇 생성](#-텔레그램-봇-생성-가이드)
2. [노션 데이터베이스 설정](#-노션-데이터베이스-설정-가이드)
3. Docker 및 docker-compose 설치

### Docker로 실행

```bash
# 1. 저장소 클론
git clone https://github.com/your-repo/seoul-youth-housing-bot.git
cd seoul-youth-housing-bot

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 편집하여 실제 값 입력 (아래 환경변수 섹션 참고)

# 3. Docker로 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f bot
```

### 로컬 개발 환경

```bash
# 1. Python 3.11+ 설치 확인
python --version

# 2. 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 3. 의존성 설치
pip install -e ".[dev]"

# 4. 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 5. 실행
python -m src.main
```

---

## 🤖 텔레그램 봇 생성 가이드

### Step 1: BotFather로 봇 생성

1. 텔레그램에서 [@BotFather](https://t.me/BotFather)를 검색하여 대화 시작
2. `/newbot` 명령어 입력
3. 봇 이름 입력 (예: `서울 청년 주거 알리미`)
4. 봇 username 입력 (예: `seoul_youth_housing_bot`) — `_bot`으로 끝나야 함
5. 발급된 **Bot Token**을 안전하게 보관

```
예시 토큰: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Step 2: 텔레그램 채널 생성

1. 텔레그램에서 "새 채널" 생성
2. 채널 이름 입력 (예: `서울 청년 주거 정보`)
3. **공개** 또는 **비공개** 채널 선택
4. 채널 생성 완료

### Step 3: 봇을 채널에 관리자로 추가

1. 채널 설정 → "관리자" → "관리자 추가"
2. 생성한 봇의 username 검색하여 추가 (예: `@seoul_youth_housing_bot`)
3. 권한 부여: **"메시지 게시"** 권한 필수 활성화
4. 저장

### Step 4: 채널 ID 확인

**공개 채널인 경우:**
- 채널 ID = `@채널username` (예: `@seoul_youth_housing`)

**비공개 채널인 경우:**
1. 채널에 아무 메시지 게시
2. 웹 브라우저에서 `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates` 접속
3. 응답에서 `"chat": {"id": -100xxxxxxxxxx}` 형태의 채널 ID 확인

### Step 5: 관리자 Chat ID 확인

1. 텔레그램에서 [@userinfobot](https://t.me/userinfobot)에게 메시지 전송
2. 응답으로 받는 숫자가 본인의 Chat ID

---

## 📅 노션 데이터베이스 설정 가이드

### Step 1: 노션 데이터베이스 생성

노션에서 새로운 **전체 페이지 데이터베이스**를 생성하고, 아래 속성을 추가합니다:

| 속성명 | 타입 | 설명 |
|--------|------|------|
| 공고명 | Title | 청약 공고 제목 (기본 Title 속성) |
| 모집유형 | Select | 행복주택, 공공임대, 매입임대 등 |
| 시작일 | Date | 모집 시작일 |
| 마감일 | Date | 모집 마감일 |
| 발표일 | Date | 당첨자 발표일 |
| 상태 | Select | 예정 / 진행중 / 마감 |
| 원문링크 | URL | 원본 공고 링크 |

> 💡 **Tip**: "모집유형" Select 옵션에 `행복주택`, `공공임대`, `매입임대`, `전세임대`, `국민임대`를 미리 추가해 두면 편리합니다.

> 💡 **Tip**: "상태" Select 옵션에 `예정`, `진행중`, `마감`을 추가하세요.

### Step 2: 노션 API 통합 생성

1. [노션 개발자 포털](https://www.notion.so/my-integrations)에 접속
2. **"새 통합(New integration)"** 클릭
3. 통합 이름 입력 (예: `청년주거봇`)
4. 관련 워크스페이스 선택
5. 기능(Capabilities) 설정:
   - ✅ 콘텐츠 읽기 (Read content)
   - ✅ 콘텐츠 업데이트 (Update content)
   - ✅ 콘텐츠 삽입 (Insert content)
6. **"제출"** 클릭
7. 발급된 **Internal Integration Secret**을 복사하여 보관

```
예시 키: secret_ABCDefghIJKLmnopQRSTuvwxyz1234567890
```

### Step 3: 데이터베이스에 통합 연결

1. 생성한 노션 데이터베이스 페이지로 이동
2. 우측 상단 **"···"** 메뉴 클릭
3. **"연결(Connections)"** → **"연결 추가(Add connections)"**
4. 위에서 생성한 통합 이름 검색 및 선택
5. **"확인"** 클릭

### Step 4: 데이터베이스 ID 확인

1. 노션 데이터베이스를 브라우저에서 열기
2. URL에서 데이터베이스 ID 추출:
   ```
   https://www.notion.so/workspace/[DATABASE_ID]?v=...
                                    ^^^^^^^^^^^^
   ```
   - 32자리 영문+숫자 조합 (하이픈 제외)

### Step 5: 공유 링크 생성

1. 데이터베이스 페이지에서 **"공유"** 클릭
2. **"웹에 게시"** 활성화 또는 **"링크 복사"**
3. 복사한 링크를 `NOTION_CALENDAR_SHARE_URL`에 설정

---

## 🔧 환경변수 설정

`.env.example`을 `.env`로 복사한 후 아래 값을 설정합니다:

```env
# ─── 텔레그램 ───────────────────────────────────
TELEGRAM_BOT_TOKEN=<BotFather에서 발급받은 토큰>
TELEGRAM_CHANNEL_ID=<채널 ID (@username 또는 -100xxxxxxxxxx)>
TELEGRAM_ADMIN_CHAT_ID=<관리자 개인 Chat ID (오류 알림 수신용)>

# ─── 노션 ───────────────────────────────────────
NOTION_API_KEY=<노션 Internal Integration Secret>
NOTION_DATABASE_ID=<노션 데이터베이스 ID (32자리)>
NOTION_CALENDAR_SHARE_URL=<노션 캘린더 공유 링크>

# ─── 데이터베이스 ────────────────────────────────
DATABASE_URL=sqlite:///data/bot.db

# ─── 스케줄러 ────────────────────────────────────
CRAWL_SCHEDULE_HOURS=11,17          # 크롤링 실행 시각 (쉼표 구분)
WEEKLY_SUMMARY_DAY=mon              # 주간 요약 요일 (mon~sun)
WEEKLY_SUMMARY_HOUR=9               # 주간 요약 시각

# ─── 로깅 ───────────────────────────────────────
LOG_LEVEL=INFO                      # DEBUG, INFO, WARNING, ERROR
LOG_DIR=./logs                      # 로그 파일 저장 경로
```

### 환경변수 상세 설명

| 변수명 | 필수 | 기본값 | 설명 |
|--------|:----:|--------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | - | 텔레그램 봇 API 토큰 |
| `TELEGRAM_CHANNEL_ID` | ✅ | - | 포스팅 대상 텔레그램 채널 ID |
| `TELEGRAM_ADMIN_CHAT_ID` | ✅ | - | 오류 알림을 받을 관리자 Chat ID |
| `NOTION_API_KEY` | ✅ | - | 노션 통합 API 시크릿 키 |
| `NOTION_DATABASE_ID` | ✅ | - | 노션 캘린더 데이터베이스 ID |
| `NOTION_CALENDAR_SHARE_URL` | ✅ | - | 노션 캘린더 공유 링크 (채널 메시지에 포함) |
| `DATABASE_URL` | ❌ | `sqlite:///data/bot.db` | SQLite 데이터베이스 파일 경로 |
| `CRAWL_SCHEDULE_HOURS` | ❌ | `11,17` | 크롤링 실행 시각 (24시간, 쉼표 구분) |
| `WEEKLY_SUMMARY_DAY` | ❌ | `mon` | 주간 요약 포스팅 요일 |
| `WEEKLY_SUMMARY_HOUR` | ❌ | `9` | 주간 요약 포스팅 시각 |
| `LOG_LEVEL` | ❌ | `INFO` | 로깅 레벨 |
| `LOG_DIR` | ❌ | `./logs` | 로그 파일 디렉토리 |

---

## 🐳 Docker 배포

### Docker 빌드 및 실행

```bash
# 이미지 빌드
docker build -t seoul-youth-housing-bot .

# 단독 실행
docker run -d \
  --name seoul-youth-housing-bot \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e TZ=Asia/Seoul \
  --restart unless-stopped \
  seoul-youth-housing-bot
```

### docker-compose로 실행 (권장)

```bash
# 빌드 및 시작
docker-compose up -d --build

# 상태 확인
docker-compose ps

# 로그 실시간 확인
docker-compose logs -f bot

# 중지
docker-compose down
```

### docker-compose.yml 구성

```yaml
services:
  bot:
    build: .
    container_name: seoul-youth-housing-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data    # SQLite DB 영속성
      - ./logs:/app/logs    # 로그 파일 보관
    environment:
      - TZ=Asia/Seoul       # 한국 시간대 설정
```

### 볼륨 마운트 설명

| 호스트 경로 | 컨테이너 경로 | 용도 |
|------------|--------------|------|
| `./data` | `/app/data` | SQLite 데이터베이스 파일 영속 저장 |
| `./logs` | `/app/logs` | 일별 로그 파일 보관 (7일 로테이션) |

---

## 📁 프로젝트 구조

```
seoul-youth-housing-bot/
├── src/
│   ├── __init__.py
│   ├── main.py                 # 진입점 — 스케줄러 초기화 및 실행
│   ├── config.py               # 환경변수 로드 및 검증
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseCrawler 추상 클래스 (공통 인터페이스)
│   │   ├── sh_crawler.py       # SH서울주택도시공사 크롤러
│   │   ├── lh_crawler.py       # LH한국토지주택공사 크롤러
│   │   ├── myhome_crawler.py   # 마이홈 포털 크롤러
│   │   └── parser.py           # 자격요건 파싱 유틸리티
│   ├── notifier/
│   │   ├── __init__.py
│   │   ├── telegram.py         # 텔레그램 채널 포스팅 (재시도 로직 포함)
│   │   ├── formatter.py        # 메시지 포맷팅 (Markdown v2)
│   │   ├── weekly_summary.py   # 주간 요약 및 리마인더 생성
│   │   └── admin.py            # 관리자 알림 및 오류 통보
│   ├── calendar/
│   │   ├── __init__.py
│   │   └── notion_client.py    # 노션 API 연동 (캘린더 관리)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy 모델 정의
│   │   ├── repository.py       # 데이터 접근 레이어 (CRUD)
│   │   └── migrations/         # DB 마이그레이션 파일
│   └── scheduler/
│       ├── __init__.py
│       └── jobs.py             # 스케줄 작업 정의 (크롤링, 포스팅, 요약)
├── tests/
│   ├── test_crawler.py         # 크롤러 단위 테스트
│   ├── test_notifier.py        # 포스팅/포맷터 테스트
│   ├── test_calendar.py        # 노션 연동 테스트
│   ├── test_scheduler.py       # 스케줄러 테스트
│   ├── test_db.py              # DB 리포지토리 테스트
│   ├── test_admin.py           # 관리자 알림 테스트
│   └── test_config.py          # 설정 로드 테스트
├── .env.example                # 환경변수 템플릿
├── .gitignore
├── pyproject.toml              # 프로젝트 메타데이터 및 의존성
├── Dockerfile                  # Docker 이미지 빌드 설정
├── docker-compose.yml          # 서비스 오케스트레이션
└── README.md                   # 프로젝트 문서
```

---

## 🧪 테스트

### 테스트 실행

```bash
# 전체 테스트 실행
pytest

# 상세 출력
pytest -v

# 커버리지 포함
pytest --cov=src --cov-report=term-missing

# 특정 모듈 테스트
pytest tests/test_crawler.py
pytest tests/test_notifier.py
pytest tests/test_db.py
```

### 테스트 구조

- `tests/test_crawler.py` — 크롤러 파싱 로직 및 중복 체크
- `tests/test_notifier.py` — 메시지 포맷팅 및 자격요건 표시
- `tests/test_calendar.py` — 노션 페이지 생성 및 상태 변경
- `tests/test_db.py` — 데이터 저장/조회/아카이브
- `tests/test_scheduler.py` — 스케줄 작업 등록 및 실행
- `tests/test_admin.py` — 관리자 알림 전송
- `tests/test_config.py` — 환경변수 로드 및 검증

---

## ⏰ 스케줄 설정

봇은 APScheduler를 사용하여 다음 작업을 자동 실행합니다:

| 작업 | 스케줄 | 설명 |
|------|--------|------|
| 크롤링 + 포스팅 | 평일 11:00, 17:00 | 3개 사이트 크롤링 → 새 공고 포스팅 → 노션 등록 |
| 주간 요약 | 매주 월요일 09:00 | 이번 주 마감 예정 공고 요약 |
| 마감 리마인더 | 매일 09:00 | 내일 마감 공고 알림 + 노션 상태 업데이트 |
| 아카이브 | 매일 09:00 | 마감 90일 경과 공고 아카이브 처리 |

### 스케줄 커스터마이징

`.env` 파일에서 크롤링 시간을 변경할 수 있습니다:

```env
# 오전 9시, 오후 1시, 오후 6시에 크롤링
CRAWL_SCHEDULE_HOURS=9,13,18

# 주간 요약을 금요일에 발송
WEEKLY_SUMMARY_DAY=fri
WEEKLY_SUMMARY_HOUR=10
```

> ⚠️ 모든 시간은 한국 시간대(Asia/Seoul) 기준입니다.

---

## 🔧 트러블슈팅

### 봇이 채널에 메시지를 보내지 않는 경우

1. **봇이 채널 관리자인지 확인** — 채널 설정에서 봇이 관리자로 등록되어 있고 "메시지 게시" 권한이 있는지 확인
2. **채널 ID 형식 확인** — 공개 채널: `@채널명`, 비공개 채널: `-100`으로 시작하는 숫자
3. **봇 토큰 유효성** — `https://api.telegram.org/bot<TOKEN>/getMe`로 토큰이 유효한지 확인

### 노션 연동이 동작하지 않는 경우

1. **통합 연결 확인** — 데이터베이스에 통합이 연결되어 있는지 확인 (페이지 ··· → 연결)
2. **API 키 확인** — `secret_`으로 시작하는 Internal Integration Secret을 사용하는지 확인
3. **데이터베이스 ID 확인** — URL에서 추출한 32자리 ID가 정확한지 확인
4. **속성명 일치** — 노션 DB 속성명이 코드에서 사용하는 이름과 정확히 일치하는지 확인

### 크롤링이 실패하는 경우

1. **네트워크 연결 확인** — 컨테이너에서 외부 사이트에 접근 가능한지 확인
2. **로그 확인** — `docker-compose logs bot` 또는 `./logs/bot.log` 파일 확인
3. **사이트 구조 변경** — 대상 사이트의 HTML 구조가 변경된 경우 파서 업데이트 필요

### Docker 관련 문제

```bash
# 컨테이너 재시작
docker-compose restart bot

# 컨테이너 로그 확인 (최근 100줄)
docker-compose logs --tail 100 bot

# 컨테이너 내부 접속
docker-compose exec bot /bin/bash

# 이미지 재빌드 (코드 변경 후)
docker-compose up -d --build
```

### 데이터베이스 관련

```bash
# SQLite DB 파일 위치
ls -la ./data/bot.db

# DB 내용 직접 확인 (sqlite3 필요)
sqlite3 ./data/bot.db ".tables"
sqlite3 ./data/bot.db "SELECT COUNT(*) FROM announcements;"
```

---

## 📊 운영 모니터링

### 로그 확인

```bash
# 실시간 로그
tail -f ./logs/bot.log

# 오류만 필터링
grep "ERROR" ./logs/bot.log

# 특정 날짜 로그
cat ./logs/bot.log.2024-01-15
```

### 관리자 알림

봇은 다음 상황에서 관리자에게 텔레그램 DM을 자동 전송합니다:

- 크롤링 3회 재시도 실패
- 텔레그램 포스팅 3회 재시도 실패
- 데이터베이스 저장 실패
- 노션 API 호출 실패

---

## 📄 라이선스

MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
