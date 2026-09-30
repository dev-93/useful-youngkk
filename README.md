# 서울 청년 주거 정보 텔레그램 봇 🏠

서울 청년(만 19~39세)을 위한 공공임대·행복주택 청약 정보를 수집해 텔레그램 채널과 노션 캘린더에 전달합니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| 자동 수집 | SH공사, LH공사, HUG 및 청약홈 API에서 공고 수집 |
| 채널 포스팅 | 새 공고 발견 시 텔레그램 채널에 자동 게시 |
| 자격요건 보충 | Gemini API가 설정된 경우 누락된 자격요건 보충 |
| 노션 캘린더 | 새 공고 등록 및 마감된 공고 상태 업데이트 |
| 마감 리마인더 | 각 수집 실행에서 다음 날 마감 공고를 채널에 안내 |
| 관리자 알림 | 수집 및 외부 API 처리 실패와 실행 결과 요약을 DM으로 전달 |

## 실행 구조

GitHub Actions의 `.github/workflows/crawl.yml`이 평일 오전 10시, 오전 11시, 오후 5시(KST)에 실행됩니다. 각 실행은 다음 단일 명령으로 수집, 새 공고 게시, 노션 등록, 상태 업데이트, 다음 날 마감 리마인더를 순서대로 처리합니다.

```bash
python -m src.cli crawl
```

새 공고가 없는 실행에서도 노션 마감 상태 업데이트와 다음 날 마감 리마인더는 계속 수행됩니다. 수동 실행은 GitHub Actions의 `workflow_dispatch`로도 가능합니다.

```text
GitHub Actions (평일 10:00, 11:00, 17:00 KST)
  └─ python -m src.cli crawl
       ├─ SH / LH / HUG / 청약홈 수집
       ├─ 새 공고 텔레그램 게시
       ├─ 새 공고 노션 등록
       ├─ 노션 마감 상태 업데이트
       └─ 다음 날 마감 리마인더 게시
```

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 크롤링 | httpx, BeautifulSoup4 |
| 텔레그램 | python-telegram-bot |
| 노션 | notion-client |
| 데이터베이스 | SQLite, SQLAlchemy |
| 실행 스케줄 | GitHub Actions cron |

## 로컬 설정

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

다음 환경변수를 `.env` 또는 GitHub Actions secrets에 설정합니다.

```env
TELEGRAM_BOT_TOKEN=<BotFather에서 발급받은 토큰>
TELEGRAM_CHANNEL_ID=<채널 ID>
TELEGRAM_ADMIN_CHAT_ID=<관리자 개인 Chat ID>

NOTION_ACCESS_TOKEN=<노션 Internal Integration Secret>
NOTION_DATABASE_ID=<노션 데이터베이스 ID>
NOTION_DATA_SOURCE_ID=<노션 데이터 소스 ID>
NOTION_CALENDAR_SHARE_URL=<노션 캘린더 공유 링크>

DATABASE_URL=sqlite:///data/bot.db
PUBLIC_DATA_API_KEY=<공공데이터포털 API 키, 선택>
GEMINI_API_KEY=<Gemini API 키, 선택>

LOG_LEVEL=INFO
LOG_DIR=./logs
```

실제 자격 증명이 든 `.env`는 저장소에 커밋하지 않습니다.

## 실행

전체 수집 및 알림 파이프라인:

```bash
python -m src.cli crawl
```

채널에 게시하지 않고 수집 결과를 관리자 DM으로 확인하는 테스트 명령:

```bash
python -m src.cli test
```

운영 스케줄을 변경하려면 애플리케이션 환경변수가 아니라 `.github/workflows/crawl.yml`의 cron 표현식을 수정합니다. GitHub Actions cron은 UTC 기준이므로 KST와의 시차를 반영해야 합니다.

## 텔레그램 설정

1. 텔레그램에서 [@BotFather](https://t.me/BotFather)를 열고 `/newbot`으로 봇을 생성합니다.
2. 대상 채널을 만든 뒤 봇을 관리자로 추가하고 메시지 게시 권한을 부여합니다.
3. 공개 채널은 `@channel_name`, 비공개 채널은 `-100`으로 시작하는 ID를 `TELEGRAM_CHANNEL_ID`로 사용합니다.
4. 관리자 개인 Chat ID를 `TELEGRAM_ADMIN_CHAT_ID`에 설정합니다.

## 노션 설정

1. 노션에 캘린더용 데이터베이스를 생성합니다.
2. 노션 Integration을 만들고 콘텐츠 읽기, 업데이트, 삽입 권한을 부여합니다.
3. 데이터베이스에 Integration을 연결합니다.
4. 데이터베이스 ID와 data source ID를 각각 `NOTION_DATABASE_ID`, `NOTION_DATA_SOURCE_ID`에 설정합니다.
5. 공유 링크를 `NOTION_CALENDAR_SHARE_URL`에 설정합니다.

코드는 공고명, 공고 구분, 모집 유형, 시작일, 마감일, 발표일, 상태, 원문 링크, 출처ID, 출처, 자격요건 요약, 대상 지역 속성을 사용합니다. 노션 속성 이름과 타입이 코드의 정의와 일치해야 합니다.

## 프로젝트 구조

```text
seoul-youth-housing-bot/
├── .github/workflows/       # 예약 및 수동 GitHub Actions 실행
├── src/
│   ├── cli.py               # GitHub Actions CLI 진입점
│   ├── config.py            # 환경변수 로드 및 로깅 설정
│   ├── crawler/             # 공고 수집기
│   ├── notifier/            # 텔레그램 메시지 및 요약 생성기
│   ├── calendar/            # 노션 캘린더 연동
│   ├── db/                  # SQLAlchemy 모델과 저장소
│   └── scheduler/jobs.py    # 통합 수집·알림 파이프라인
├── tests/
├── pyproject.toml
└── README.md
```

`src/notifier/weekly_summary.py`의 `WeeklySummaryGenerator`는 독립적인 메시지 생성 모듈로 유지되지만 현재 GitHub Actions 운영 경로에서 예약 실행되지는 않습니다.

## 테스트

```bash
pytest
pytest --cov=src --cov-report=term-missing
```

## 문제 해결

- 텔레그램 게시 실패: 봇의 채널 관리자 권한, 채널 ID, 봇 토큰을 확인합니다.
- 노션 연동 실패: Integration 연결, API 토큰, database/data source ID, 속성 이름을 확인합니다.
- 수집 실패: GitHub Actions 실행 로그 또는 로컬 `./logs/bot.log`에서 대상 사이트 응답과 오류를 확인합니다.
- 로컬 DB 확인: 기본 파일은 `./data/bot.db`이며 `DATABASE_URL`로 경로를 변경할 수 있습니다.

## 라이선스

MIT License
