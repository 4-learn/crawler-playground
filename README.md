# crawler-playground 爬蟲練習站

勞動部 AI 大數據人才養成班「Python 爬蟲」課程的自建練習站，用來取代爬真實網站。
內容是 8 部勞動相關法律與「營造安全衛生設施標準」，共 9 部 749 條，來源是[全國法規資料庫開放資料 API](https://law.moj.gov.tw/api/swagger/docs/v1)。

- 線上版（GitHub Pages）：<https://4-learn.github.io/crawler-playground/>
- 教室版（本機或區網）：`python server.py`

> 為什麼不直接爬 law.moj.gov.tw？因為它的 `robots.txt` 是 `Disallow: /`，而且官方另外提供開放資料 API。
> 這本身就是課程的第一個案例：**先找 API，再考慮爬網頁。** 法律條文依著作權法第 9 條不受著作權保護，所以可以做成練習站。

## 關卡

| 關卡 | 路徑 | 練習重點 |
|---|---|---|
| 1 靜態頁與分頁 | `v1/laws/` | requests + BeautifulSoup、跟著「下一頁」走、詳細頁內的 JSON-LD |
| 2 先找 API | `v1/api/laws.json` | 同一份資料的 JSON 版，拿來跟 HTML 爬下來的結果比對 |
| 3 動態載入 | `v1/dynamic/` | requests 只會看到「載入中…」；改用 DevTools 找 API，或用 Playwright 等元素出現、攔截 response |
| 4 無限捲動 | `v1/scroll/` | 用 Playwright 捲動，或直接找 `api/feed/page-N.json` |
| 5 登入 | `v1/members/login.html` | 帳號 `student`、密碼 `crawler-demo`；練表單操作和 `storage_state` 保存登入狀態 |
| 6 robots.txt | `robots.txt` | `v1/admin/` 是禁止爬取的路徑，頁面上有一串 canary 字串，爬到就代表沒有先檢查 robots.txt |
| 7 網站改版 | `v2/` | HTML 結構和 API 欄位都改了，條文有 4 條修改、1 條刪除、1 條新增，用來練習偵測變動 |

第 2 版（`v2/`）裡的改動都是刻意做的，修改處會標註「虛構修正」，不是真實條文：

- 修改：勞動基準法第 24、38 條，職業安全衛生法第 6 條，性別平等工作法第 15 條
- 刪除：大量解僱勞工保護法第 21 條
- 新增：勞動基準法第 86-1 條

## 兩種部署方式的差異

| 功能 | GitHub Pages | `server.py` |
|---|---|---|
| 關卡 1～7 | ✅ | ✅ |
| `robots.txt` 位置 | `/crawler-playground/robots.txt`（課程約定以此為準） | 網域根目錄 `/robots.txt`（符合規範） |
| 速率限制 429 + `Retry-After` | ❌（GitHub 自己的限制無法控制） | ✅ 預設可瞬間發 20 個請求，持續上限每秒 5 個 |
| 會員專區由伺服器驗證 cookie | ❌ 只有前端假登入，資料其實公開 | ✅ 未登入時 API 回 401、頁面導回登入頁 |
| ETag 與 304 | 有，由 GitHub 提供 | ✅ |
| 爬到禁止路徑時顯示在老師畫面 | ❌ | ✅ 終端機印出 `[robots] IP … UA …` |

建議：學員回家練習用 GitHub Pages；上課示範 429、401 和 robots 違規紀錄時，老師用 `python server.py --host 0.0.0.0` 開在教室區網。

## 開發

只用 Python 標準函式庫，不必安裝任何套件就能建站和啟動伺服器。

```bash
python build.py                      # 輸出 dist/（base=/）
python server.py                     # 重建 dist-local/ 並啟動 http://127.0.0.1:8000
python scripts/fetch_laws.py         # 教師用：重新從官方 API 下載 data/laws.v1.json
```

同一份資料每次建出來的檔案內容完全相同，所以課程講義裡寫的預期輸出不會因為重建而改變。

### 驗收測試

測試的寫法就是學員會寫的爬蟲（requests + bs4 和 Playwright），每一關都實際爬一遍，再跟 `data/laws.v1.json` 比對。

```bash
pip install requests beautifulsoup4 playwright pytest
playwright install chromium

python server.py --port 8000 &
PG_BASE_URL=http://127.0.0.1:8000/ PG_LOCAL=1 pytest -q tests

PG_BASE_URL=https://4-learn.github.io/crawler-playground/ pytest -q tests
```

如果 Playwright 在你的系統上無法下載瀏覽器，可以用 `PG_CHROMIUM=/path/to/chrome` 指定執行檔。

## 授權與聲明

- 程式碼：MIT
- 條文資料：取自全國法規資料庫，法律條文依著作權法第 9 條不受著作權保護。本站為教學用副本，第 2 版有刻意修改，**不具法律效力**，正式內容請以全國法規資料庫為準。
