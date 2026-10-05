"""練習站驗收測試：以「學員會寫的爬蟲」逐關實測。

    # 本機（server.py 已啟動）
    PG_BASE_URL=http://127.0.0.1:8000/ pytest -q tests
    # GitHub Pages
    PG_BASE_URL=https://4-learn.github.io/crawler-playground/ pytest -q tests

PG_LOCAL=1 時另外驗證伺服器才有的行為（429、401、304、根目錄 robots.txt）。
若 Playwright 無法自行下載瀏覽器，可用 PG_CHROMIUM 指定執行檔。
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import pytest
import requests
from bs4 import BeautifulSoup

BASE = os.environ.get("PG_BASE_URL", "http://127.0.0.1:8000/")
LOCAL = os.environ.get("PG_LOCAL") == "1"
UA = "course-crawler-test/1.0 (4-learn)"
DATA = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / "laws.v1.json").read_text(encoding="utf-8"))
EXPECTED = {law["pcode"]: law for law in DATA["laws"]}
CANARY = "PG-CANARY-ADMIN-7F3A"

session = requests.Session()
session.headers["User-Agent"] = UA


def get(url: str, **kwargs) -> requests.Response:
    for _ in range(5):
        r = session.get(url, timeout=20, **kwargs)
        if r.status_code != 429:
            break
        time.sleep(int(r.headers.get("Retry-After", "1")))
    if r.status_code != 304:
        r.raise_for_status()
    r.encoding = "utf-8"
    return r


def soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(get(url).text, "html.parser")


def robots() -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(get(urljoin(BASE, "robots.txt")).text.splitlines())
    return rp


# ---------------------------------------------------------------- 關卡 1：靜態頁與分頁

def crawl_law_v1(pcode: str) -> list[dict]:
    url = urljoin(BASE, f"v1/laws/{pcode}/")
    out = []
    while url:
        s = soup(url)
        for art in s.select("article.article"):
            out.append({
                "slug": art["data-slug"],
                "article_no": art.select_one(".article-no").get_text(strip=True),
                "content": "\n".join(p.get_text() for p in art.select(".article-content p")),
            })
        nxt = s.select_one("a.next")
        url = urljoin(url, nxt["href"]) if nxt else None
    return out


def test_level1_law_list():
    s = soup(urljoin(BASE, "v1/laws/"))
    rows = s.select("tr.law")
    assert {r["data-pcode"] for r in rows} == set(EXPECTED)
    assert int(s.select_one("#law-count").text) == len(EXPECTED)


@pytest.mark.parametrize("pcode", ["N0030001", "N0020012"])
def test_level1_pagination_complete(pcode):
    got = crawl_law_v1(pcode)
    want = EXPECTED[pcode]["articles"]
    assert [a["slug"] for a in got] == [a["slug"] for a in want]
    assert [a["content"] for a in got] == [a["content"] for a in want]


def test_level1_article_detail_and_jsonld():
    s = soup(urljoin(BASE, "v1/laws/N0030001/articles/24.html"))
    assert s.select_one(".article-no").get_text(strip=True) == "第 24 條"
    ld = json.loads(s.find("script", type="application/ld+json").string)
    assert ld["legislationIdentifier"] == "N0030001#24"
    assert ld["text"] == next(a for a in EXPECTED["N0030001"]["articles"] if a["slug"] == "24")["content"]


# ---------------------------------------------------------------- 關卡 2：API

def test_level2_api_matches_html():
    index = get(urljoin(BASE, "v1/api/laws.json")).json()
    assert index["count"] == len(EXPECTED)
    pcode = "N0060001"
    url = urljoin(BASE, f"v1/api/laws/{pcode}/page-1.json")
    arts = []
    while url:
        d = get(url).json()
        arts += d["articles"]
        url = urljoin(url, d["next"]) if d["next"] else None
    assert [a["content"] for a in arts] == [a["content"] for a in EXPECTED[pcode]["articles"]]


# ---------------------------------------------------------------- 關卡 6：robots.txt

def test_level6_robots_rules():
    rp = robots()
    assert rp.can_fetch(UA, urljoin(BASE, "v1/laws/"))
    assert not rp.can_fetch(UA, urljoin(BASE, "v1/admin/"))
    assert not rp.can_fetch("BadBot", urljoin(BASE, "v1/laws/"))
    assert rp.crawl_delay(UA) == 1


def test_level6_naive_crawler_hits_canary_polite_one_does_not():
    """從首頁沿連結走：不看 robots 的爬蟲會抓到後台，守規矩的不會。"""
    rp = robots()
    host = urlparse(BASE).netloc

    def crawl(polite: bool) -> bool:
        s = soup(BASE)
        for a in s.select("footer a, .levels a"):
            href = urljoin(BASE, a["href"])
            if urlparse(href).netloc != host or not href.endswith("/"):
                continue
            if polite and not rp.can_fetch(UA, href):
                continue
            if CANARY in get(href).text:
                return True
        return False

    assert crawl(polite=False) is True
    assert crawl(polite=True) is False


# ---------------------------------------------------------------- 關卡 7：改版

def test_level7_v1_selectors_break_on_v2():
    s = soup(urljoin(BASE, "v2/laws/N0030001/p/1.html"))
    assert s.select("article.article") == []  # 舊選擇器失效
    assert len(s.select("tr.row")) == 25


def test_level7_change_detection():
    import hashlib

    def h(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    old = {(p, a["slug"]): h(a["content"]) for p, law in EXPECTED.items() for a in law["articles"]}
    new = {}
    index = get(urljoin(BASE, "v2/api/laws.json")).json()
    for item in index["items"]:
        n, pages = 1, 1
        while n <= pages:
            d = get(urljoin(BASE, f'v2/api/laws/{item["code"]}/{n}.json')).json()
            pages = d["pages"]
            for a in d["items"]:
                new[(item["code"], a["id"])] = h(a["text"])
            n += 1
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    assert added == [("N0030001", "86-1")]
    assert removed == [("N0020012", "21")]
    assert changed == sorted([("N0030001", "24"), ("N0030001", "38"), ("N0060001", "6"), ("N0030014", "15")])


# ---------------------------------------------------------------- 僅本機伺服器

@pytest.mark.skipif(not LOCAL, reason="需要 server.py")
def test_local_robots_at_root_and_conditional_get():
    assert get(urljoin(BASE, "/robots.txt")).text.startswith("# 爬蟲練習站")
    url = urljoin(BASE, "v1/api/laws.json")
    etag = get(url).headers["ETag"]
    r = get(url, headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.content == b""


@pytest.mark.skipif(not LOCAL, reason="需要 server.py")
def test_local_rate_limit_and_auth():
    time.sleep(1.2)
    codes = [requests.get(urljoin(BASE, "v1/laws/"), headers={"User-Agent": UA}, timeout=10).status_code
             for _ in range(30)]
    assert 429 in codes
    time.sleep(5)
    assert requests.get(urljoin(BASE, "v1/api/members/notices.json"), timeout=10).status_code == 401
    r = requests.get(urljoin(BASE, "v1/members/"), allow_redirects=False, timeout=10)
    assert r.status_code == 302
    time.sleep(1.2)
    ok = requests.get(urljoin(BASE, "v1/api/members/notices.json"),
                      cookies={"pg_session": "demo-session-token"}, timeout=10)
    assert ok.status_code == 200 and ok.json()["member_only"] is True


# ---------------------------------------------------------------- Playwright：關卡 3、4、5

@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        kwargs = {}
        if os.environ.get("PG_CHROMIUM"):
            kwargs["executable_path"] = os.environ["PG_CHROMIUM"]
        b = p.chromium.launch(**kwargs)
        yield b
        b.close()


def test_level3_requests_sees_nothing():
    s = soup(urljoin(BASE, "v1/dynamic/"))
    assert s.select("article.article") == []
    assert "載入中" in s.select_one("#app").text


def test_level3_playwright_waits(browser):
    page = browser.new_page(user_agent=UA)
    page.goto(urljoin(BASE, "v1/dynamic/#N0030001"))
    page.locator("article.article").first.wait_for()
    assert page.locator("article.article").count() == len(EXPECTED["N0030001"]["articles"])
    page.close()


def test_level3_playwright_intercepts_api(browser):
    page = browser.new_page(user_agent=UA)
    with page.expect_response(lambda r: r.url.endswith("/api/laws.json")) as info:
        page.goto(urljoin(BASE, "v1/dynamic/"))
    assert info.value.json()["count"] == len(EXPECTED)
    page.close()


def test_level4_infinite_scroll(browser):
    page = browser.new_page(user_agent=UA, viewport={"width": 1000, "height": 700})
    page.goto(urljoin(BASE, "v1/scroll/"))
    for _ in range(40):
        if page.locator("#feed-end").count():
            break
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(500)
    assert page.locator("#feed-end").count() == 1
    assert page.locator(".feed-item").count() == len(EXPECTED["N0030001"]["articles"])
    page.close()


def test_level5_login_and_storage_state(browser, tmp_path):
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    page.goto(urljoin(BASE, "v1/members/"))
    page.wait_for_url("**/login.html")
    page.get_by_label("帳號").fill("student")
    page.get_by_label("密碼").fill("wrong")
    page.get_by_role("button", name="登入").click()
    assert page.locator("#login-error").is_visible()
    page.get_by_label("密碼").fill("crawler-demo")
    page.get_by_role("button", name="登入").click()
    page.locator(".notice-item").first.wait_for()
    assert page.locator(".notice-item").count() == 5
    state = tmp_path / "state.json"
    ctx.storage_state(path=str(state))
    ctx.close()

    ctx2 = browser.new_context(user_agent=UA, storage_state=str(state))
    page2 = ctx2.new_page()
    page2.goto(urljoin(BASE, "v1/members/"))
    page2.locator(".notice-item").first.wait_for()
    assert "members/index.html" in page2.url or page2.url.endswith("/members/")
    ctx2.close()
