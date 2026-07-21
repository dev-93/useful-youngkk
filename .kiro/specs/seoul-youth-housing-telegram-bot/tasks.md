# Implementation Plan: Seoul Youth Housing Telegram Bot

## Overview

서울 청년 주거 정보 텔레그램 채널 봇을 구현하기 위한 단계별 작업 목록. Python 기반으로 크롤러, 텔레그램 포스팅, 노션 캘린더 연동을 구축한다.

## Tasks

- [x] 1. 프로젝트 초기 설정 및 구조 생성
  - Requirements: 6.1, 6.4
  - 프로젝트 디렉토리 구조 생성, pyproject.toml 의존성 정의(httpx, beautifulsoup4, python-telegram-bot, notion-client, sqlalchemy, apscheduler), .env.example 환경변수 템플릿, src/config.py 설정 관리 모듈, Dockerfile 및 docker-compose.yml 작성, 기본 로깅 설정(일별 파일 로테이션)

- [x] 2. 데이터베이스 모델 및 리포지토리 구현
  - Requirements: 1.2, 1.4, 6.1, 6.2
  - SQLAlchemy 모델 정의(announcements, crawl_logs, post_history 테이블), DB 초기화 스크립트, 데이터 접근 레이어 구현(CRUD, 중복 체크, 아카이브), (source_site, source_id) 복합 유니크 제약조건 설정

- [x] 3. 크롤러 베이스 클래스 및 SH공사 크롤러 구현
  - Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
  - BaseCrawler 추상 클래스(fetch, parse, save 인터페이스), 자격요건 파싱 유틸리티, SH서울주택도시공사 크롤러(목록 페이지 파싱, 상세 크롤링), 재시도 로직(30분 간격, 최대 3회), 불완전 공고 처리

- [x] 4. LH공사 및 마이홈 포털 크롤러 구현
  - Requirements: 1.1, 1.2
  - LH한국토지주택공사 크롤러, 마이홈 포털 크롤러, 사이트별 고유 ID 추출 로직

- [x] 5. 텔레그램 채널 포스팅 모듈 구현
  - Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3
  - 텔레그램 Bot API 채널 메시지 전송, 새 공고 메시지 포맷팅(Markdown v2 — 공고명, 유형, 기간, 자격요건 섹션, 링크), 자격요건 항목별 포맷팅(누락 시 안내 문구), 재시도 로직(30초 간격, 최대 3회, 관리자 DM 알림), post_history 기록

- [x] 6. 노션 캘린더 연동 구현
  - Requirements: 4.1, 4.2, 4.3, 4.4
  - 노션 API 클라이언트 초기화, 새 공고→노션 DB 페이지 생성(공고명, 유형, 시작일, 마감일, 발표일, 상태, 링크), 상태 자동 변경(마감일 경과 시 "마감"), 재시도 로직(최대 3회), announcement 테이블 notion_page_id 연동

- [x] 7. 주간 요약 및 리마인더 구현
  - Requirements: 5.1, 5.2, 5.3, 5.4
  - 주간(월~일) 마감 예정 공고 조회, 주간 요약 메시지 포맷팅(공고명, 마감일, 유형 + 노션 링크), 마감 전일 리마인더 조회 및 메시지 생성, 공고 없을 시 안내 메시지 처리

- [x] 8. 스케줄러 설정 및 전체 통합
  - Requirements: 1.1, 5.1, 5.4
  - APScheduler 작업 정의(크롤링, 포스팅, 주간 요약, 리마인더), main.py 진입점(스케줄러 초기화, 작업 등록), 크롤링→포스팅→노션 등록 파이프라인 연결, 평일 판별 로직, 마감 전일 리마인더 + 노션 상태 업데이트 배치

- [x] 9. 관리자 알림 및 운영 로그
  - Requirements: 2.4, 6.3, 6.4
  - 관리자 텔레그램 DM 알림(오류 메시지 전송), 크롤링 결과 로그(crawl_logs 테이블), 일별 로그 파일 로테이션(7일 보관), 90일 경과 공고 아카이브 배치

- [x] 10. 배포 및 README 작성
  - Requirements: All
  - Docker 이미지 빌드 테스트, docker-compose 전체 서비스 동작 확인, README.md(프로젝트 소개, 설정, 실행, 아키텍처), 텔레그램 봇 생성 및 채널 연결 가이드, 노션 DB 템플릿 및 API 설정 가이드

## Task Dependency Graph

```json
{
  "waves": [
    {
      "tasks": [1],
      "description": "프로젝트 초기 설정"
    },
    {
      "tasks": [2],
      "description": "DB 모델 및 리포지토리"
    },
    {
      "tasks": [3, 5, 6],
      "description": "SH 크롤러, 텔레그램 포스팅, 노션 캘린더 (병렬)"
    },
    {
      "tasks": [4, 7],
      "description": "추가 크롤러, 주간 요약/리마인더"
    },
    {
      "tasks": [8, 9],
      "description": "스케줄러 통합, 관리자 알림/로그"
    },
    {
      "tasks": [10],
      "description": "배포 및 문서화"
    }
  ]
}
```

## Notes

- Task 3~4(크롤러)와 Task 5(포스팅), Task 6(노션)은 Task 2 이후 병렬 개발 가능
- 각 크롤러는 사이트 구조 변경에 민감하므로 파서를 독립적으로 유지
- 초기 배포는 단일 서버(VPS)에서 docker-compose로 운영, 이후 필요시 클라우드 마이그레이션
