# 先看這裡：啟動台灣合約審查 Agent

這是本機版 GUI Agent。解壓縮後不需要打開測試資料夾，也不需要先執行 pytest。

## 1. 最快啟動

在這個資料夾中雙擊：

```text
start-gui.vbs
```

啟動後瀏覽器會開啟：

```text
http://127.0.0.1:8787
```

如果瀏覽器沒有自動開啟，請手動貼上上面的網址。

如果啟動時提示 `Port 8787 is already in use`，代表可能已經有舊版服務在跑。腳本會打開現有網址並停止啟動新服務。若要重新載入新版，請先回到舊的 PowerShell 視窗按 `Ctrl+C`，再重新執行 `start-gui.ps1`。

## 2. 如果雙擊沒有反應

改用 PowerShell 啟動，這樣可以看到錯誤訊息：

```powershell
cd 解壓縮後的資料夾路徑
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start-gui.ps1
```

第一次啟動會自動建立 `.venv` 並安裝 Python 依賴，會花幾分鐘。

## 3. 第一次測試

1. 合約模式選 `租賃合約`、`買賣合約`、`勞動合約`，或選 `自動判斷`。
2. 貼上合約文字，或上傳 `.txt` 檔。
3. 先不要勾選「使用 API 模型產生報告」。
4. 按「產生審查報告」。

這會使用本機 dry-run 模式，不需要 API key，也不會呼叫外部模型。

## 4. 使用 API 模型

如果要使用模型產生報告：

1. 在「API 設定」選 OpenAI、OpenRouter、Gemini、Anthropic、llama.cpp 或 Ollama。
2. 遠端模型請填 API key；Ollama 和部分 llama.cpp 情境可不填。
3. 確認 Base URL 和模型名稱。
4. 按「保存設定」。
5. 在合約輸入區勾選「使用 API 模型產生報告」。
6. 按「產生審查報告」。

API key 只會存在本機 `.env`，不會提交到 Git，也不會顯示完整內容。

## 5. 停止服務

如果你是用 PowerShell 啟動，回到該 PowerShell 視窗按：

```text
Ctrl+C
```

如果你用 `start-gui.vbs` 啟動且需要停止，請在工作管理員結束對應的 `python.exe` 或 `uvicorn`。

## 6. 這個 zip 不應該包含什麼

正式使用者包不應包含：

- `tests/`
- `node_modules/`
- `.venv/`
- `.env`
- `tw_contract_review_testpack_v1.zip`
- `contracts/` 測試資料夾

如果你看到上述內容，表示你打開的是開發資料夾或測試資料包，不是正式 release zip。
