# Release Notes

## Legal Contract Assistant GUI MVP

這是台灣合約審查 Agent 的本機 GUI 技術預覽版。使用者解壓 zip 後，可用 PowerShell 啟動本機網頁介面，選擇合約模式、貼上或上傳 `.txt` 合約，並產生 Markdown 審查報告。

## 支援環境

- 作業系統：Windows 10/11。
- 必要工具：Python 3.11 以上。
- 開發或重建前端：Node.js 20.19 以上與 npm。
- 已打包 zip 內含 React build 結果，一般使用者啟動 GUI 時通常不需要 Node；若 `frontend/dist` 不存在或要重新 build GUI，才需要 Node。

## 啟動方式

在解壓後的資料夾中執行：

```powershell
.\start-gui.ps1
```

若要不開命令列視窗啟動，可雙擊：

```text
start-gui.vbs
```

需要除錯時，請改用 `start-gui.ps1` 以便查看 log。

腳本會：

- 建立本機 `.venv`。
- 安裝 `requirements.txt` 內的 Python 依賴。
- 若需要，建置前端 GUI。
- 啟動 FastAPI 服務於 `http://127.0.0.1:8787`。
- 開啟瀏覽器。

## API Key 與隱私

- API key 儲存在解壓資料夾內的 `.env`。
- `.env` 不會包含在 release zip 中。
- GUI 不會明文回顯 API key，只顯示是否已設定與末四碼遮罩。
- 若未勾選「使用 API 模型產生報告」，系統會使用本地 dry-run 模式，不呼叫外部 API。
- 使用 OpenAI、OpenRouter 或其他遠端模型時，合約內容會送到使用者設定的模型服務；正式使用前應自行確認資料保護與保密需求。
- 模型供應商支援 OpenAI、OpenRouter、llama.cpp、Ollama、Anthropic、Gemini；Ollama 與 llama.cpp 走 OpenAI-compatible 介面，Anthropic/Gemini 第一版為非串流文字輸出。
- 一般模式固定請求 `8192` output tokens；長合約模式會改用工具內的 provider 高輸出上限。免費模型仍可能被供應商平台限制；若模型因 `length`、`max_tokens` 或 `MAX_TOKENS` 停止，GUI 會顯示停止原因與截斷警告。

## 已知限制

- 第一版只支援貼上純文字與 `.txt` 上傳。
- 尚未支援 PDF、DOCX、掃描件或 OCR。
- 報告僅為合約風險初步檢查，不構成正式法律意見。
- 法條與審查規則來自本地 seed/cache，正式使用前仍應回官方來源核對最新版本。
- GUI 目前以本機單人使用為目標，尚未設計多人帳號、權限或伺服器部署。

## 發布內容

release zip 應包含：

- `src/`
- `frontend/dist/`
- `requirements.txt`
- `START_HERE.zh-TW.md`
- `start-gui.ps1`
- `start-gui.vbs`
- `README.md`
- `RELEASE_NOTES.md`
- `USER_GUIDE.zh-TW.md`

release zip 不應包含：

- `.env`
- `.venv`
- `node_modules`
- `.cache`
- `tests/`
- `requirements-dev.txt`
- `pytest.ini`
- `tw_contract_review_testpack_v1.zip`
- `contracts/` 測試資料夾
- `__pycache__`
- `*.pyc`
