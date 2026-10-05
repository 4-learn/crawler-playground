"""教師用：從全國法規資料庫官方開放資料 API 下載法規，挑出本站使用的勞動法律。

用法：
    python scripts/fetch_laws.py            # 產生 data/laws.v1.json

這支程式示範「先找官方 API」：law.moj.gov.tw 的 robots.txt 為 Disallow: /，
不應爬它的網頁；官方另外提供 https://law.moj.gov.tw/api/Ch/Law/JSON（ZIP 內含 ChLaw.json）。
只需在更新教材時執行，平常上課直接使用 repo 內的 data/laws.v1.json。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import urllib.request
import zipfile

API_URL = "https://law.moj.gov.tw/api/Ch/Law/JSON"
SWAGGER_URL = "https://law.moj.gov.tw/api/swagger/docs/v1"
USER_AGENT = "4-learn-crawler-playground/1.0 (teaching; contact yillkid@gmail.com)"

# 以 pcode 指定，避免同名或改名造成誤選。
PCODES = [
    "N0030001",  # 勞動基準法
    "N0030014",  # 性別平等工作法
    "N0030020",  # 勞工退休金條例
    "N0060001",  # 職業安全衛生法
    "N0090001",  # 就業服務法
    "N0020007",  # 勞資爭議處理法
    "N0020012",  # 大量解僱勞工保護法
    "N0050031",  # 勞工職業災害保險及保護法
]

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "laws.v1.json"


def normalize_heading(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    # 「第 一 章 總則」→「第一章 總則」
    return re.sub(r"第\s*(\S+?)\s*(章|節|款|目)", r"第\1\2", text)


def article_slug(article_no: str) -> str:
    m = re.fullmatch(r"第\s*(\d+(?:-\d+)?)\s*條", article_no.strip())
    if not m:
        raise ValueError(f"無法解析條號：{article_no!r}")
    return m.group(1)


def convert(law: dict) -> dict:
    chapter = ""
    section = ""
    articles = []
    for item in law["LawArticles"]:
        if item["ArticleType"] == "C":
            heading = normalize_heading(item["ArticleContent"])
            if "節" in heading.split(" ")[0]:
                section = heading
            else:
                chapter, section = heading, ""
            continue
        lines = [ln.strip() for ln in item["ArticleContent"].replace("\r\n", "\n").split("\n")]
        articles.append(
            {
                "slug": article_slug(item["ArticleNo"]),
                "article_no": re.sub(r"\s+", " ", item["ArticleNo"].strip()),
                "chapter": chapter,
                "section": section,
                "content": "\n".join(ln for ln in lines if ln),
            }
        )
    pcode = law["LawURL"].rsplit("pcode=", 1)[1]
    return {
        "pcode": pcode,
        "name": law["LawName"],
        "level": law["LawLevel"],
        "category": law["LawCategory"],
        "modified_date": law["LawModifiedDate"],
        "official_url": law["LawURL"],
        "articles": articles,
    }


def main() -> None:
    req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        data = json.loads(zf.read("ChLaw.json").decode("utf-8-sig"))

    by_pcode = {law["LawURL"].rsplit("pcode=", 1)[1]: law for law in data["Laws"]}
    missing = [p for p in PCODES if p not in by_pcode]
    if missing:
        raise SystemExit(f"官方資料中找不到 pcode：{missing}")
    abandoned = [p for p in PCODES if by_pcode[p]["LawAbandonNote"]]
    if abandoned:
        raise SystemExit(f"以下法規已廢止，請改選：{abandoned}")

    laws = [convert(by_pcode[p]) for p in PCODES]
    payload = {
        "source": {
            "name": "全國法規資料庫 開放資料 API（中文法規 法律）",
            "api_url": API_URL,
            "swagger_url": SWAGGER_URL,
            "api_update_date": data["UpdateDate"],
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "zip_sha256": hashlib.sha256(raw).hexdigest(),
            "note": "法律條文依著作權法第 9 條不得為著作權標的；本站為教學用副本，不具法律效力，請以全國法規資料庫為準。",
        },
        "laws": laws,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(l["articles"]) for l in laws)
    print(f"寫入 {OUT}：{len(laws)} 部法律、{total} 條")
    for law in laws:
        print(f"  {law['pcode']} {law['name']}：{len(law['articles'])} 條（異動日 {law['modified_date']}）")


if __name__ == "__main__":
    main()
