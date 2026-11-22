# Legal Contract Assistant 本機開發說明

這份文件面向本機安裝、Provider、MCP、測試與發布。企業／作品集入口請閱讀 [README.md](README.md)；一般使用者請先閱讀 [START_HERE.zh-TW.md](START_HERE.zh-TW.md)。

## 環境需求

一般 GUI：

- Windows
- Python 3.11 或更新版本

重新建置前端：

- Node.js 20.19 或更新版本
- npm

打包版已包含 frontend/dist，一般使用者不需要 Node.js。

## 快速啟動

Windows 可直接執行：

    start-gui.vbs

需要查看 log 時使用 PowerShell：

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\start-gui.ps1

腳本會建立 .venv、安裝 requirements.txt、必要時建置前端，並啟動：

    http://127.0.0.1:8787

若連接埠已被使用，腳本會開啟既有網址而不啟動第二個服務。

## 開發環境

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

後端：

    .\.venv\Scripts\python.exe -m uvicorn src.legal_contract_assistant.web_app:app --host 127.0.0.1 --port 8787

前端：

    cd frontend
    npm install
    npm run build
    cd ..

## Provider 設定

GUI 支援：

- OpenAI
- OpenRouter
- llama.cpp
- Ollama
- Anthropic
- Gemini

設定保存在專案根目錄的 .env，並由 Git 忽略。GUI 只顯示遮罩值，不回顯完整 API key。

OpenAI-compatible 本機服務可在 GUI 填入自訂 base URL 與模型 ID。Ollama 與不需真實金鑰的 llama.cpp 仍可能因 client contract 需要非空字串，但不應使用真實秘密當占位值。

使用遠端 Provider 之前，先確認合約資料是否允許傳送到該服務。

## Dry-run 與 CLI

不使用模型產生報告：

    python -m src.legal_contract_assistant.main --contract-type lease --text "甲方為出租人，乙方為承租人。"

Dry-run 使用本機規則與法條資料，適合離線測試與面試展示。

## 法條檢索

標準模式使用：

- ContractStatuteCache
- StatuteLookupService
- StatuteRetrievalTool
- CacheStatuteRetriever

法條工具：

- search_statutes
- retrieve_candidate_articles
- lookup_article

主審查 API 的預設模式為 standard。

## MCP server

啟動：

    python -m src.legal_contract_assistant.mcp_server

MCP server 與 GUI／CLI 共用相同法條工具，不維護第二份法律資料邏輯。

## 自動測試

    .\.venv\Scripts\python.exe -m pytest -q

測試涵蓋：

- 合約分類與風險規則；
- SQLite 法條 cache 與來源連結；
- Provider payload、截斷警告與 native tool calling；
- FastAPI settings、dry-run、立場與 TXT／PDF／DOCX upload；

額外執行離線標註評估：

    python -m scripts.evaluate --out-dir reports

評估報告寫入 `reports/evaluation.md` 和 `reports/evaluation.json`，不需要 API key；結果代表規則及 dry-run 模板，不能當成 LLM 的法律準確率。CI 在 PR 與 push 時執行 Python 測試、離線評估和前端 build，並將報告存為 artifact。

不要在 README 保存會快速過時的 passed 數字；以當次 pytest 結果為準。

## Release zip

建置前端並建立 timestamped zip：

    .\build-release.ps1

Release 應包含執行所需 backend、frontend/dist、requirements、啟動腳本與使用者文件；不應包含：

- .env
- .venv
- node_modules
- cache 或本機展示資料
- tests 與測試資料
- API key 或私人合約

## 專案結構

- src/legal_contract_assistant：後端、審查工作流、法條、Provider 與 API
- frontend：React / TypeScript GUI
- tests：規則、檢索、Provider 與 API 測試
- docs：架構與維護文件
- START_HERE.zh-TW.md：一般使用者快速开始
- USER_GUIDE.zh-TW.md：繁体中文操作手册
- RELEASE_NOTES.md：發布環境、隱私與限制

## 維護原則

- 法條資料需要持續與官方來源核對。
- 新 Provider 必須維持 citation grounding 與 tool contract。
- 敏感合約優先使用 dry-run 或受控本機模型。
- 不提交 .env、API key、本機 SQLite、模型檔或使用者合約。
