# 使用說明

## 1. 解壓與啟動

1. 將 release zip 解壓到一個固定資料夾，例如：

```text
D:\tools\legal-contract-assistant
```

2. 在該資料夾空白處按右鍵，選擇「在終端機中開啟」或開啟 PowerShell 後切換到該資料夾：

```powershell
cd D:\tools\legal-contract-assistant
```

3. 執行啟動腳本：

```powershell
.\start-gui.ps1
```

4. 瀏覽器會開啟：

```text
http://127.0.0.1:8787
```

如果 PowerShell 停在終端機中持續顯示服務訊息，這是正常狀態。要停止服務，回到該 PowerShell 視窗按 `Ctrl+C`。

## 2. 選擇合約類型

GUI 的「合約模式」可選：

- `自動判斷`：由系統用關鍵字初步分類。
- `買賣合約`：適用買賣、標的物、價金、交付、瑕疵等條款。
- `勞動合約`：適用雇主、勞工、薪資、工時、離職等條款。
- `租賃合約`：適用出租人、承租人、租金、押金、修繕、租期等條款。

如果你已經知道合約類型，建議直接選明確類型；如果不確定，再選「自動判斷」。

## 3. 輸入合約

你可以使用兩種方式：

- 直接把合約全文貼到「合約文字」欄位。
- 上傳 `.txt` 檔案。

目前不支援 PDF、DOCX 或圖片掃描件。若合約是 PDF 或 Word，請先自行轉成純文字或 `.txt`。

## 4. 不填 API Key 的 dry-run 測試

第一次測試建議先不要勾選「使用 API 模型產生報告」。

1. 合約模式選 `租賃合約`。
2. 貼上測試文字：

```text
甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。
```

3. 按「產生審查報告」。
4. 預期右側會出現 Markdown 報告，包含：

- `合約審查報告`
- `相關法條`
- `可能缺漏項目`
- `免責聲明`

dry-run 模式只使用本地 SQLite 法條與規則，不會呼叫外部模型，也不需要 API key。

## 5. 設定 API Key

若要使用模型產生報告：

1. 在「API 設定」選擇供應商：

- `OpenAI`
- `OpenRouter`
- `llama.cpp`

2. 貼上 API key。
3. 確認 Base URL 與模型名稱。
4. 按「保存設定」。

API key 會寫入同資料夾的 `.env`。GUI 不會明文顯示已保存的 key，只會顯示遮罩，例如：

```text
***3456
```

若要移除 key，按「清除 key」。

## 6. 使用 llama.cpp 本機模型

如果你已經在本機啟動 llama.cpp OpenAI-compatible server，可用：

```text
Base URL: http://127.0.0.1:18080/v1
Model: local-chat
```

llama.cpp 通常可使用佔位 API key；如果 GUI 未要求真實 key，可先不填或使用：

```text
sk-no-key-required
```

然後勾選「使用 API 模型產生報告」，再按「產生審查報告」。

## 7. 匯出報告

報告產生後，你可以：

- 按「複製」將 Markdown 複製到剪貼簿。
- 按「下載 .md」下載 Markdown 檔。

## 8. 常見問題

### PowerShell 顯示無法執行腳本

如果 Windows 阻擋本機 PowerShell 腳本，請在該終端機中執行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start-gui.ps1
```

這只會影響目前 PowerShell 視窗。

### 瀏覽器沒有自動打開

手動開啟：

```text
http://127.0.0.1:8787
```

### 不想把合約送到外部 API

不要勾選「使用 API 模型產生報告」。系統會使用 dry-run 模式，只在本機產生報告。

### 報告能否當正式法律意見？

不能。本工具只提供初步風險檢查，正式使用前仍需人工審查並核對最新官方法規。
