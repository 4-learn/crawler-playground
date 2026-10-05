"""產生爬蟲練習站（純靜態檔，可放 GitHub Pages，也可用 server.py 在本機提供）。

用法：
    python build.py                                   # 本機：輸出 dist/，base 為 /
    python build.py --base /crawler-playground/ \
        --site-url https://4-learn.github.io          # GitHub Pages

只用 Python 標準函式庫；輸出內容不含時間戳，同一份資料重建結果完全相同。
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data" / "laws.v1.json"
STATIC = ROOT / "static"

V1_PAGE_SIZE = 20
V2_PAGE_SIZE = 25
FEED_PCODE = "N0030001"  # 無限捲動關卡使用勞動基準法
FEED_BATCH = 10
DEMO_USER = "student"
DEMO_PASSWORD = "crawler-demo"
CANARY = "PG-CANARY-ADMIN-7F3A"

DISCLAIMER = (
    "教學練習站：條文取自全國法規資料庫開放資料，可能經刻意修改以供練習，"
    "不具法律效力；正式內容請以全國法規資料庫為準。"
)
V2_NOTICE = "第 2 版練習站：網頁結構與 API 欄位已改版，部分條文加入「虛構修正」句子，用於練習變動偵測。"
V2_FAKE_SENTENCE = "（本句為爬蟲練習站第 2 版虛構修正，用於練習變動偵測，非真實法條。）"

# 第 2 版的刻意變動：修改、刪除、新增。
V2_MODIFY = [("N0030001", "24"), ("N0030001", "38"), ("N0060001", "6"), ("N0030014", "15")]
V2_DELETE = [("N0020012", "21")]
JS_FETCH_HELPER = """// 遇到 429（請求太快）時依 Retry-After 等待後重試
async function fetchJSON(url, options) {
  for (let i = 0; i < 5; i++) {
    const res = await fetch(url, options);
    if (res.status !== 429) {
      if (!res.ok) throw new Error(`${res.status} ${url}`);
      return { res, data: await res.json() };
    }
    const wait = Number(res.headers.get("Retry-After") || "1");
    await new Promise((r) => setTimeout(r, wait * 1000));
  }
  throw new Error(`429 ${url}`);
}
"""

V2_ADD = {
    "pcode": "N0030001",
    "after": "86",
    "slug": "86-1",
    "article_no": "第 86-1 條",
    "content": "本條為爬蟲練習站第 2 版虛構新增之條文，用於練習偵測新增資料，非真實法條。",
}

esc = html.escape


# ---------------------------------------------------------------- 共用

def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, obj) -> None:
    write(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def paragraphs(text: str) -> str:
    return "".join(f"<p>{esc(line)}</p>" for line in text.split("\n"))


def page(title: str, body: str, base: str, *, depth_css: str, extra_head: str = "",
         notice: str = "", scripts: str = "") -> str:
    notice_html = f'<div class="notice notice-version">{esc(notice)}</div>' if notice else ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}｜爬蟲練習站</title>
<link rel="stylesheet" href="{depth_css}style.css">
{extra_head}</head>
<body>
<header class="site-header"><a class="brand" href="{base}">爬蟲練習站</a></header>
<div class="notice">{esc(DISCLAIMER)}</div>
{notice_html}<main>
{body}
</main>
<footer class="site-footer">
<p>資料來源：<a href="https://law.moj.gov.tw/">全國法規資料庫</a>開放資料 API。練習站原始碼：<a href="https://github.com/4-learn/crawler-playground">4-learn/crawler-playground</a></p>
<p class="footer-links"><a href="{base}robots.txt">robots.txt</a> · <a href="{base}v1/admin/">管理後台</a></p>
</footer>
{scripts}</body>
</html>
"""


def rel(depth: int) -> str:
    return "../" * depth


def chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


def law_summary(law: dict) -> dict:
    return {
        "pcode": law["pcode"],
        "name": law["name"],
        "modified_date": law["modified_date"],
        "article_count": len(law["articles"]),
    }


# ---------------------------------------------------------------- v2 資料

def make_v2(data: dict) -> dict:
    v2 = copy.deepcopy(data)
    laws = {law["pcode"]: law for law in v2["laws"]}
    for pcode, slug in V2_MODIFY:
        art = next(a for a in laws[pcode]["articles"] if a["slug"] == slug)
        art["content"] = art["content"] + "\n" + V2_FAKE_SENTENCE
    for pcode, slug in V2_DELETE:
        laws[pcode]["articles"] = [a for a in laws[pcode]["articles"] if a["slug"] != slug]
    target = laws[V2_ADD["pcode"]]["articles"]
    idx = next(i for i, a in enumerate(target) if a["slug"] == V2_ADD["after"])
    new = {k: V2_ADD[k] for k in ("slug", "article_no", "content")}
    new["chapter"] = target[idx]["chapter"]
    new["section"] = target[idx]["section"]
    target.insert(idx + 1, new)
    return v2


# ---------------------------------------------------------------- 第 1 版：靜態頁

def build_v1_static(out: pathlib.Path, data: dict, base: str) -> None:
    root = out / "v1"
    laws = data["laws"]

    rows = "".join(
        f'<tr class="law" data-pcode="{law["pcode"]}">'
        f'<td class="law-name"><a href="{law["pcode"]}/">{esc(law["name"])}</a></td>'
        f'<td class="pcode">{law["pcode"]}</td>'
        f'<td class="modified">{law["modified_date"]}</td>'
        f'<td class="count">{len(law["articles"])}</td></tr>'
        for law in laws
    )
    body = f"""<h1>勞動法規列表</h1>
<p>共 <span id="law-count">{len(laws)}</span> 部法規。點選法規名稱查看條文。</p>
<table class="law-list">
<thead><tr><th>法規名稱</th><th>pcode</th><th>異動日期</th><th>條文數</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""
    write(root / "laws" / "index.html", page("勞動法規列表", body, base, depth_css=rel(2)))

    for law in laws:
        pages = chunked(law["articles"], V1_PAGE_SIZE)
        for n, chunk in enumerate(pages, 1):
            items = "".join(
                f'<article class="article" id="a-{a["slug"]}" data-slug="{a["slug"]}">'
                f'<h3 class="article-no"><a href="articles/{a["slug"]}.html">{esc(a["article_no"])}</a></h3>'
                f'<p class="chapter">{esc(a["chapter"])}{(" " + esc(a["section"])) if a["section"] else ""}</p>'
                f'<div class="article-content">{paragraphs(a["content"])}</div></article>'
                for a in chunk
            )
            nav = []
            if n > 1:
                prev_href = "index.html" if n == 2 else f"page-{n - 1}.html"
                nav.append(f'<a class="prev" rel="prev" href="{prev_href}">上一頁</a>')
            nav.append(f'<span class="current">第 {n} / {len(pages)} 頁</span>')
            if n < len(pages):
                nav.append(f'<a class="next" rel="next" href="page-{n + 1}.html">下一頁</a>')
            body = f"""<nav class="breadcrumb"><a href="../">勞動法規列表</a> › {esc(law["name"])}</nav>
<h1 class="law-title">{esc(law["name"])}</h1>
<dl class="law-meta"><dt>pcode</dt><dd class="pcode">{law["pcode"]}</dd><dt>異動日期</dt><dd class="modified">{law["modified_date"]}</dd><dt>條文數</dt><dd class="count">{len(law["articles"])}</dd></dl>
<section class="articles">{items}</section>
<nav class="pagination">{"".join(nav)}</nav>"""
            name = "index.html" if n == 1 else f"page-{n}.html"
            write(root / "laws" / law["pcode"] / name,
                  page(f'{law["name"]} 第 {n} 頁', body, base, depth_css=rel(3)))

        arts = law["articles"]
        for i, a in enumerate(arts):
            ld = {
                "@context": "https://schema.org",
                "@type": "Legislation",
                "name": f'{law["name"]} {a["article_no"]}',
                "legislationIdentifier": f'{law["pcode"]}#{a["slug"]}',
                "isPartOf": law["name"],
                "text": a["content"],
            }
            links = []
            if i > 0:
                links.append(f'<a class="prev" rel="prev" href="{arts[i - 1]["slug"]}.html">上一條</a>')
            if i < len(arts) - 1:
                links.append(f'<a class="next" rel="next" href="{arts[i + 1]["slug"]}.html">下一條</a>')
            body = f"""<nav class="breadcrumb"><a href="../../">勞動法規列表</a> › <a href="../">{esc(law["name"])}</a> › {esc(a["article_no"])}</nav>
<article class="article-detail" data-pcode="{law["pcode"]}" data-slug="{a["slug"]}">
<h1><span class="law-name">{esc(law["name"])}</span> <span class="article-no">{esc(a["article_no"])}</span></h1>
<p class="chapter">{esc(a["chapter"])}{(" " + esc(a["section"])) if a["section"] else ""}</p>
<div class="article-content">{paragraphs(a["content"])}</div>
</article>
<nav class="pagination">{"".join(links)}</nav>"""
            head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
            write(root / "laws" / law["pcode"] / "articles" / f'{a["slug"]}.html',
                  page(f'{law["name"]} {a["article_no"]}', body, base, depth_css=rel(4), extra_head=head))


# ---------------------------------------------------------------- 第 1 版：API

def build_v1_api(out: pathlib.Path, data: dict) -> None:
    api = out / "v1" / "api"
    laws = data["laws"]
    write_json(api / "laws.json", {"version": 1, "count": len(laws), "laws": [law_summary(l) for l in laws]})
    for law in laws:
        pages = chunked(law["articles"], V1_PAGE_SIZE)
        for n, chunk in enumerate(pages, 1):
            write_json(api / "laws" / law["pcode"] / f"page-{n}.json", {
                "version": 1,
                "pcode": law["pcode"],
                "name": law["name"],
                "page": n,
                "total_pages": len(pages),
                "total": len(law["articles"]),
                "next": f"page-{n + 1}.json" if n < len(pages) else None,
                "articles": [{k: a[k] for k in ("slug", "article_no", "chapter", "section", "content")} for a in chunk],
            })
    feed_law = next(l for l in laws if l["pcode"] == FEED_PCODE)
    batches = chunked(feed_law["articles"], FEED_BATCH)
    for n, chunk in enumerate(batches, 1):
        write_json(api / "feed" / f"page-{n}.json", {
            "page": n,
            "has_more": n < len(batches),
            "items": [{"pcode": FEED_PCODE, "law": feed_law["name"], **{k: a[k] for k in ("slug", "article_no", "content")}}
                      for a in chunk],
        })
    notices = sorted(laws, key=lambda l: l["modified_date"], reverse=True)[:5]
    write_json(api / "members" / "notices.json", {
        "member_only": True,
        "notices": [
            {"pcode": l["pcode"], "title": f'{l["name"]} 最近異動日期 {l["modified_date"]}', "modified_date": l["modified_date"]}
            for l in notices
        ],
    })


# ---------------------------------------------------------------- 第 1 版：動態頁、捲動、登入、後台

def build_v1_interactive(out: pathlib.Path, data: dict, base: str) -> None:
    root = out / "v1"

    body = """<h1>動態載入的法規頁</h1>
<p>本頁內容由 JavaScript 呼叫 API 後才出現。用 <code>requests</code> 下載原始碼試試看，再打開 DevTools 的 Network 分頁。</p>
<label>選擇法規：<select id="law-select"><option value="">載入中…</option></select></label>
<div id="app" class="loading">載入中…</div>"""
    write(root / "dynamic" / "index.html",
          page("動態載入", body, base, depth_css=rel(2), scripts='<script src="dynamic.js"></script>\n'))
    write(root / "dynamic" / "dynamic.js", JS_FETCH_HELPER + """// 刻意延遲，讓學員體會「等待元素出現」
const API = "../api/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const app = document.getElementById("app");
const select = document.getElementById("law-select");

async function loadLaw(pcode) {
  app.className = "loading";
  app.textContent = "載入中…";
  const articles = [];
  let url = `${API}laws/${pcode}/page-1.json`;
  let name = "";
  while (url) {
    const { res, data } = await fetchJSON(url);
    name = data.name;
    articles.push(...data.articles);
    url = data.next ? new URL(data.next, res.url).href : null;
  }
  await sleep(1200);
  app.className = "";
  app.innerHTML = "";
  const h = document.createElement("h2");
  h.className = "law-title";
  h.textContent = `${name}（${articles.length} 條）`;
  app.appendChild(h);
  for (const a of articles) {
    const el = document.createElement("article");
    el.className = "article";
    el.dataset.slug = a.slug;
    const no = document.createElement("h3");
    no.className = "article-no";
    no.textContent = a.article_no;
    const body = document.createElement("div");
    body.className = "article-content";
    for (const line of a.content.split("\\n")) {
      const p = document.createElement("p");
      p.textContent = line;
      body.appendChild(p);
    }
    el.append(no, body);
    app.appendChild(el);
  }
}

async function init() {
  const { data } = await fetchJSON(`${API}laws.json`);
  select.innerHTML = "";
  for (const law of data.laws) {
    const opt = document.createElement("option");
    opt.value = law.pcode;
    opt.textContent = law.name;
    select.appendChild(opt);
  }
  const fromHash = location.hash.slice(1);
  select.value = data.laws.some((l) => l.pcode === fromHash) ? fromHash : data.laws[0].pcode;
  select.addEventListener("change", () => {
    location.hash = select.value;
    loadLaw(select.value);
  });
  await loadLaw(select.value);
}
init();
""")

    body = """<h1>無限捲動：勞動基準法</h1>
<p>往下捲動才會載入更多條文。要拿到全部條文，你的爬蟲得學會「捲動」或直接找到背後的 API。</p>
<section id="feed"></section>
<div id="sentinel" class="loading">捲動以載入更多…</div>"""
    write(root / "scroll" / "index.html",
          page("無限捲動", body, base, depth_css=rel(2), scripts='<script src="scroll.js"></script>\n'))
    write(root / "scroll" / "scroll.js", JS_FETCH_HELPER + """const feed = document.getElementById("feed");
const sentinel = document.getElementById("sentinel");
let page = 0;
let loading = false;
let done = false;

async function loadMore() {
  if (loading || done) return;
  loading = true;
  page += 1;
  await new Promise((r) => setTimeout(r, 600));
  const { data } = await fetchJSON(`../api/feed/page-${page}.json`);
  for (const item of data.items) {
    const el = document.createElement("article");
    el.className = "feed-item";
    el.dataset.slug = item.slug;
    el.innerHTML = `<h3 class="article-no"></h3><p class="article-content"></p>`;
    el.querySelector(".article-no").textContent = `${item.law} ${item.article_no}`;
    el.querySelector(".article-content").textContent = item.content;
    feed.appendChild(el);
  }
  if (!data.has_more) {
    done = true;
    sentinel.className = "end";
    sentinel.id = "feed-end";
    sentinel.textContent = "已經到底了";
  }
  loading = false;
  // 若內容還不足以填滿畫面，繼續載入
  if (!done && sentinel.getBoundingClientRect().top < window.innerHeight) loadMore();
}

new IntersectionObserver((entries) => {
  if (entries.some((e) => e.isIntersecting)) loadMore();
}).observe(sentinel);
""")

    cookie_path = base + "v1/"
    body = f"""<h1>會員登入</h1>
<p>練習用帳號：<code>{DEMO_USER}</code>，密碼：<code>{DEMO_PASSWORD}</code>。請勿輸入任何真實帳號密碼。</p>
<form id="login-form">
<label>帳號 <input name="username" id="username" autocomplete="off"></label>
<label>密碼 <input name="password" id="password" type="password" autocomplete="off"></label>
<button type="submit" id="login-button">登入</button>
</form>
<p id="login-error" class="error" hidden>帳號或密碼錯誤</p>"""
    write(root / "members" / "login.html",
          page("會員登入", body, base, depth_css=rel(2), scripts='<script src="login.js"></script>\n'))
    write(root / "members" / "login.js", f"""// 注意：這是「假登入」，只為練習表單操作與保存登入狀態。
// 靜態網站無法真正保護資料；用 server.py 在本機執行時，伺服器才會檢查 cookie。
document.getElementById("login-form").addEventListener("submit", (e) => {{
  e.preventDefault();
  const u = document.getElementById("username").value;
  const p = document.getElementById("password").value;
  if (u === "{DEMO_USER}" && p === "{DEMO_PASSWORD}") {{
    document.cookie = "pg_session=demo-session-token; path={cookie_path}; SameSite=Lax";
    location.href = "index.html";
  }} else {{
    document.getElementById("login-error").hidden = false;
  }}
}});
""")
    body = """<h1>會員專區</h1>
<p id="welcome" hidden>歡迎回來，<span id="member-name"></span>！以下是最近異動的法規通知：</p>
<ul id="notices"></ul>
<button id="logout" hidden>登出</button>"""
    write(root / "members" / "index.html",
          page("會員專區", body, base, depth_css=rel(2), scripts='<script src="members.js"></script>\n'))
    write(root / "members" / "members.js", JS_FETCH_HELPER + f"""const hasSession = document.cookie.split("; ").some((c) => c === "pg_session=demo-session-token");
if (!hasSession) {{
  location.replace("login.html");
}} else {{
  fetchJSON("../api/members/notices.json", {{ credentials: "same-origin" }})
    .then(({{ data }}) => {{
      document.getElementById("member-name").textContent = "{DEMO_USER}";
      document.getElementById("welcome").hidden = false;
      const ul = document.getElementById("notices");
      for (const n of data.notices) {{
        const li = document.createElement("li");
        li.className = "notice-item";
        li.dataset.pcode = n.pcode;
        li.textContent = n.title;
        ul.appendChild(li);
      }}
      const btn = document.getElementById("logout");
      btn.hidden = false;
      btn.addEventListener("click", () => {{
        document.cookie = "pg_session=; path={cookie_path}; max-age=0";
        location.href = "login.html";
      }});
    }});
}}
""")

    for ver in ("v1", "v2"):
        body = f"""<h1>管理後台（禁止爬取）</h1>
<p>這個路徑寫在 <a href="{base}robots.txt">robots.txt</a> 的 <code>Disallow</code> 裡。</p>
<p>如果你的爬蟲抓到了這一頁，代表它沒有先檢查 robots.txt。請回頭修正。</p>
<p class="canary">{CANARY}</p>"""
        write(out / ver / "admin" / "index.html",
              page("管理後台", body, base, depth_css=rel(2), extra_head='<meta name="robots" content="noindex, nofollow">\n'))


# ---------------------------------------------------------------- 第 2 版：改版後的網站

def build_v2(out: pathlib.Path, data: dict, base: str) -> None:
    root = out / "v2"
    laws = data["laws"]

    cards = "".join(
        f'<li class="law-card" data-pcode="{law["pcode"]}">'
        f'<a class="title" href="{law["pcode"]}/p/1.html">{esc(law["name"])}</a>'
        f'<span class="meta">{law["pcode"]}・{law["modified_date"]}・{len(law["articles"])} 條</span></li>'
        for law in laws
    )
    body = f"""<h1>勞動法規列表（第 2 版）</h1>
<ul class="law-cards">{cards}</ul>"""
    write(root / "laws" / "index.html", page("勞動法規列表（第 2 版）", body, base, depth_css=rel(2), notice=V2_NOTICE))

    for law in laws:
        pages = chunked(law["articles"], V2_PAGE_SIZE)
        for n, chunk in enumerate(pages, 1):
            rows = "".join(
                f'<tr class="row" data-article="{a["slug"]}">'
                f'<th class="no" scope="row"><a href="../a/{a["slug"]}.html">{esc(a["article_no"])}</a></th>'
                f'<td class="text">{paragraphs(a["content"])}</td></tr>'
                for a in chunk
            )
            more = f'<a class="more" href="{n + 1}.html">更多條文 →</a>' if n < len(pages) else ""
            body = f"""<h1 class="title">{esc(law["name"])}</h1>
<p class="page-info">第 {n} / {len(pages)} 頁</p>
<table class="law-table"><tbody>{rows}</tbody></table>
<div class="pager">{more}</div>"""
            write(root / "laws" / law["pcode"] / "p" / f"{n}.html",
                  page(f'{law["name"]}（第 2 版）第 {n} 頁', body, base, depth_css=rel(4), notice=V2_NOTICE))
        for a in law["articles"]:
            body = f"""<div class="article-detail" data-pcode="{law["pcode"]}" data-article="{a["slug"]}">
<h1><span class="title">{esc(law["name"])}</span>・<span class="no">{esc(a["article_no"])}</span></h1>
<div class="text">{paragraphs(a["content"])}</div>
</div>"""
            write(root / "laws" / law["pcode"] / "a" / f'{a["slug"]}.html',
                  page(f'{law["name"]} {a["article_no"]}（第 2 版）', body, base, depth_css=rel(4), notice=V2_NOTICE))

    api = root / "api"
    write_json(api / "laws.json", {"version": 2, "items": [
        {"code": l["pcode"], "title": l["name"], "updated": l["modified_date"], "articles": len(l["articles"])}
        for l in laws
    ]})
    for law in laws:
        pages = chunked(law["articles"], V2_PAGE_SIZE)
        for n, chunk in enumerate(pages, 1):
            write_json(api / "laws" / law["pcode"] / f"{n}.json", {
                "version": 2,
                "code": law["pcode"],
                "title": law["name"],
                "page": n,
                "pages": len(pages),
                "items": [{"id": a["slug"], "number": a["article_no"], "chapter": a["chapter"], "text": a["content"]}
                          for a in chunk],
            })


# ---------------------------------------------------------------- 首頁、robots、sitemap

LEVELS = [
    ("關卡 1｜靜態頁與分頁", "v1/laws/", "requests + BeautifulSoup：列表 → 分頁 → 條文詳細頁。"),
    ("關卡 2｜先找 API", "v1/api/laws.json", "同樣的資料，網站本身就有 JSON。能用 API 就不要解析 HTML。"),
    ("關卡 3｜動態載入", "v1/dynamic/", "內容由 JavaScript 產生：用 DevTools 找 API，或用 Playwright 等待元素出現。"),
    ("關卡 4｜無限捲動", "v1/scroll/", "往下捲才會載入：Playwright 捲動，或攔截背後的 JSON。"),
    ("關卡 5｜登入", "v1/members/login.html", "填表登入後才看得到的會員專區：練習表單操作與保存登入狀態。"),
    ("關卡 6｜robots.txt", "robots.txt", "先讀規則再爬：有一個路徑是禁止爬取的。"),
    ("關卡 7｜網站改版", "v2/laws/", "第 2 版：HTML 結構、API 欄位與部分條文都變了。你的爬蟲還能用嗎？哪些條文變了？"),
]


def build_root(out: pathlib.Path, base: str, site_url: str, data: dict, v2: dict) -> None:
    items = "".join(
        f'<li class="level"><a href="{base}{href}">{esc(title)}</a><p>{esc(desc)}</p></li>' for title, href, desc in LEVELS
    )
    src = data["source"]
    body = f"""<h1>爬蟲練習站</h1>
<p>這是勞動部 AI 大數據人才養成班「Python 爬蟲」課程的練習網站。內容是勞動相關法規條文，
資料取自<a href="{esc(src["swagger_url"])}">全國法規資料庫開放資料 API</a>（官方資料日期：{esc(src["api_update_date"])}）。</p>
<h2>上課規則</h2>
<ul class="rules">
<li>先讀 <a href="{base}robots.txt">robots.txt</a>，遵守 <code>Disallow</code> 與 <code>Crawl-delay</code>。</li>
<li>爬蟲每次請求之間至少間隔 1 秒；請設定自己的 User-Agent，例如 <code>course-crawler/1.0 (你的暱稱)</code>。教室版伺服器遇到連續快速請求會回 <code>429</code>。</li>
<li>這個站是給你練習的；在真實網站上，一樣要先找 API／開放資料，並確認服務條款。</li>
</ul>
<h2>關卡</h2>
<ol class="levels">{items}</ol>"""
    write(out / "index.html", page("首頁", body, base, depth_css=""))
    # 所有頁面都以相對路徑（../）回到根目錄引用這一份 style.css
    shutil.copy(STATIC / "style.css", out / "style.css")
    for ver, label in (("v1", "第 1 版"), ("v2", "第 2 版")):
        write(out / ver / "index.html",
              f'<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=laws/"><a href="laws/">{label}</a>\n')

    sitemap_urls = [f"{base}v1/laws/"] + [f'{base}v1/laws/{l["pcode"]}/' for l in data["laws"]]
    sitemap_urls += [f"{base}v2/laws/"] + [f'{base}v2/laws/{l["pcode"]}/p/1.html' for l in v2["laws"]]
    write(out / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{esc(site_url + u)}</loc></url>\n" for u in sitemap_urls) + "</urlset>\n")

    write(out / "robots.txt", f"""# 爬蟲練習站 robots.txt
# 注意：robots.txt 依規範應放在網域根目錄。GitHub Pages 專案站不在根目錄，
# 因此本課約定：以「練習站首頁 + robots.txt」這份檔案為準。用 server.py 在本機執行時則位於根目錄。

User-agent: *
Crawl-delay: 1
Disallow: {base}v1/admin/
Disallow: {base}v2/admin/

User-agent: BadBot
Disallow: /

Sitemap: {site_url}{base}sitemap.xml
""")
    write(out / ".nojekyll", "")
    write(out / "404.html", page("找不到頁面", "<h1>404 找不到頁面</h1>", base, depth_css=base))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="/", help="網站根路徑，例如 /crawler-playground/（前後都要有 /）")
    ap.add_argument("--site-url", default="http://127.0.0.1:8000", help="網站 origin，用於 sitemap")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()
    base = args.base
    if not (base.startswith("/") and base.endswith("/")):
        ap.error("--base 必須以 / 開頭並以 / 結尾")

    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    v2 = make_v2(data)

    build_v1_static(out, data, base)
    build_v1_api(out, data)
    build_v1_interactive(out, data, base)
    build_v2(out, v2, base)
    build_root(out, base, args.site_url.rstrip("/"), data, v2)

    files = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"已輸出 {out}（{files} 個檔案，base={base}）")


if __name__ == "__main__":
    main()
