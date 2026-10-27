# useful-youngkk — AI 작업 규칙

서울 청년(만 19~39세)용 공공임대·청약 공고를 수집해서 텔레그램 채널과 노션 캘린더에 전달하는 봇입니다. 실행 구조, 환경 변수, 텔레그램·노션 설정은 [README.md](./README.md)를 참고합니다.

## 상세 규칙 위치

| 파일 | 내용 |
| --- | --- |
| [.kiro/steering/target-audience.md](./.kiro/steering/target-audience.md) | 타겟, 수집 대상·제외 공고 유형, 수집 소스, 자격요건 참고 자료 |
| [.kiro/steering/task-management.md](./.kiro/steering/task-management.md) | 노션 Task Board 사용 규칙 |

## 스택과 명령

- Python 3.11 이상, httpx + BeautifulSoup4, python-telegram-bot, notion-client, SQLAlchemy(SQLite)
- 운영: GitHub Actions `.github/workflows/crawl.yml`(평일 09:00 KST, cron은 UTC로 작성)

```bash
pip install -e ".[dev]"            # 또는 uv 사용
pytest                             # 테스트 (기본)
pytest -m snapshot                 # 실제 사이트 구조 변경 감지 (네트워크 필요, 느림)
python -m src.cli test             # 채널 게시 없이 관리자 DM으로 수집 결과 확인
python -m src.cli crawl            # 운영 파이프라인 (채널 게시·노션 쓰기 발생)
```

`python -m src.cli crawl`은 실제 채널에 게시하고 노션에 씁니다. 사용자가 요청할 때만 실행합니다. 검증은 `pytest`와 `src.cli test`로 합니다.

## 수집 규칙 요약

- 대상: SH공사, LH공사(서울특별시 필터), 청약홈 API(서울 필터). 서울 지역만 다룹니다.
- 제외 유형: 영구임대(기초수급자 대상), 집주인임대, 가정어린이집
- 민간분양은 오피스텔·도시형생활주택·공공지원 민간임대 위주로 수집합니다. 분양가 6억 이상 APT는 제외를 검토합니다.
- 자격요건 수치(소득·자산 기준)는 매년 바뀝니다. 코드나 메시지에 넣을 때는 공식 출처로 연도를 확인합니다.
- 노션 캘린더 속성 이름·타입은 코드 정의와 일치해야 합니다. 속성을 임의로 추가하거나 이름을 바꾸지 않습니다.

## 작업 관리

- 작업은 노션 Task Board(사이드비즈 프로젝트)로 관리합니다. 노션 갱신은 사용자가 승인한 범위만 합니다.
- 태스크는 의미 있는 단위로 나누고, 기능 태그는 Feature / Bug를 씁니다.

## 보안

- `.env`와 `data/bot.db`는 커밋하지 않습니다. 토큰 값을 출력하지 않습니다.
