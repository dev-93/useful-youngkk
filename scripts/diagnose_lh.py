"""Read-only LH endpoint probe. No credentials or notification APIs are used."""
import json
import socket
import sys
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE = "https://apply.lh.or.kr"
LIST = BASE + "/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026"
DETAIL = BASE + "/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": BASE + "/lhapply/main.do",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def probe(client, label, method, url, **kwargs):
    started = time.monotonic()
    events = []

    def trace(name, info):
        event = {"stage": name, "seconds": round(time.monotonic() - started, 4)}
        if name.endswith(".failed"):
            error = info.get("exception")
            event["error_type"] = type(error).__name__
            event["error"] = str(error)
        events.append(event)

    try:
        response = client.request(method, url, extensions={"trace": trace}, **kwargs)
        soup = BeautifulSoup(response.text, "html.parser")
        emit({
            "label": label, "url": str(response.url), "status": response.status_code,
            "seconds": round(time.monotonic() - started, 4), "bytes": len(response.content),
            "title": soup.title.get_text(" ", strip=True) if soup.title else None,
            "redirects": [{"status": item.status_code, "url": str(item.url)} for item in response.history],
            "soft_404": any(text in response.text for text in ("페이지가 삭제", "잘못된 경로")),
            "events": events,
        })
        return response
    except Exception as error:
        emit({"label": label, "seconds": round(time.monotonic() - started, 4),
              "error_type": type(error).__name__, "error": str(error), "events": events})
        return None


def main():
    emit({"python": sys.version.split()[0], "httpx": httpx.__version__})
    try:
        emit({"dns": sorted({item[4][0] for item in socket.getaddrinfo("apply.lh.or.kr", 443, type=socket.SOCK_STREAM)})})
    except Exception as error:
        emit({"dns_error_type": type(error).__name__, "dns_error": str(error)})

    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        response = probe(client, "direct_list", "GET", LIST)
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            links = sorted({urljoin(BASE, link.get("href", "")) for link in soup.select("a[href]")
                            if "selectWrtancList.do?mi=1026" in link.get("href", "")})
            seoul = []
            table = soup.select_one("table")
            for row in table.select("tr") if table else []:
                cells = row.select("td")
                link = row.select_one("a.wrtancInfoBtn")
                if len(cells) >= 9 and link and "서울" in cells[3].get_text():
                    seoul.append({"panId": link.get("data-id1"), "ccrCnntSysDsCd": link.get("data-id2"),
                                  "uppAisTpCd": link.get("data-id3"), "aisTpCd": link.get("data-id4"), "mi": "1026"})
            emit({"menu_list_links": links, "same_as_code": LIST in links,
                  "table_rows": len(table.select("tr")) if table else 0, "seoul_rows": len(seoul),
                  "detail_action_matches_code": "/lhapply/apply/wt/wrtanc/selectWrtancInfo.do" in response.text})
            if seoul:
                probe(client, "detail_post", "POST", DETAIL, data=seoul[0])

    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        response = probe(client, "main", "GET", BASE + "/lhapply/main.do")
        if response is not None:
            soup = BeautifulSoup(response.text, "html.parser")
            emit({"main_menu_same_as_code": any(urljoin(BASE, link.get("href", "")) == LIST for link in soup.select("a[href]"))})
        probe(client, "list_after_main", "GET", LIST)


if __name__ == "__main__":
    main()
