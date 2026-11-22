# Legal Contract Assistant｜台灣合約審查助手

> 以本機法條、審查規則與可替換的 AI 模型，產生可追溯的合約風險報告。

Legal Contract Assistant 是一個面向台灣買賣、勞動與租賃合約的初步審查工具。使用者可貼上文字或上傳 TXT、可擷取文字的 PDF、DOCX（上限 8 MB），選擇審查立場，再以純本機 dry-run 或外部／本機模型產生 Markdown 報告。

報告會整理風險主題、缺漏事項、修改建議、相關法條與來源網址。模型只能使用系統提供或工具查得的法條證據；正式使用仍應由合格法律專業人員確認。

> 本工具只提供初步風險整理，不構成法律意見。

## 企業問題

一般聊天模型可以快速閱讀合約，但若沒有受控的法條來源、審查規則與引用限制，容易產生無法追溯或過度自信的法律敘述。

這個專案將合約審查拆成可驗證的工程流程：

1. 接收合約文字與使用者選擇的合約類型、審查立場。
2. 以本機規則辨識風險主題、缺漏項目與初步風險。
3. 從 SQLite 法條快取或可替換檢索器取得候選法條。
4. 必要時讓模型透過唯讀工具補查法條。
5. 將法條、來源與審查上下文交給報告產生器。
6. 輸出固定結構的 Markdown 報告供人類複核。

## 為什麼不只是 LLM 包裝

### 法條證據先於模型文字

法條名稱、條號、內容與來源網址來自本機快取或檢索工具。Prompt 明確限制模型只能引用 related articles、candidate articles 或工具查詢結果，不能自由補充未提供的法條、判決或函釋。

### 規則與模型責任分離

Python 規則先處理合約類型、風險主題、缺漏與審查立場；模型負責將已提供的上下文整理成可閱讀報告。即使不設定 API key，dry-run 仍可展示完整的法條與風險資料流。

### 檢索與生成保持分離

法條搜尋、候選條文排序與精確條號查詢由後端工具處理；模型只取得整理後的證據。檢索失敗時不會要求模型自行補造法源。

### 工具能力可以重用

GUI、CLI、MCP server 與模型 native tool calling 共用法條搜尋、候選法條檢索與精確條文查詢能力，避免每個介面複製一套法律資料邏輯。

## 架構

    React GUI / CLI / MCP client
                 |
                 v
             FastAPI
                 |
                 v
        ContractReviewService
          |              |
          v              v
    Review rules    Statute retrieval tools
                         |
                         v
                    SQLite cache
                         |
                         v
          Native tool calling / dry-run
                         |
                         v
              Markdown review report

## 核心能力

### 合約與立場

- 買賣、勞動、租賃或不指定合約類型；
- 中立、甲方或乙方審查立場；
- 貼上文字或上傳 TXT、PDF、DOCX（8 MB 上限；PDF 必須含可選取文字，不含 OCR）；
- 長合約截斷警告與明確停止原因。

### 可追溯檢索

- 本機 SQLite 法條與審查規則；
- 依合約類型、風險主題與關鍵字搜尋；
- 候選法條合併、排序與來源網址；
- 精確條號查詢；

### 模型與工具邊界

- OpenAI-compatible、Anthropic 與 Gemini provider boundary；
- 支援本機 llama.cpp 與 Ollama；
- 模型可呼叫 search statutes 與 lookup article 等唯讀工具；
- 後端執行工具並把結果送回模型；
- API key 僅保存於本機環境檔，並在 GUI 遮罩顯示。

## 責任邊界

| 本機規則與檢索 | LLM | 人類 |
| --- | --- | --- |
| 辨識風險、缺漏與審查上下文 | 整理已有證據並撰寫報告 | 確認合約事實與商業背景 |
| 提供法條、條號與來源網址 | 必要時呼叫核准的唯讀工具 | 驗證法條時效與適用性 |
| 限制可引用的法律資料 | 不得自行創造未提供的法源 | 決定是否採納修改建議 |

## 技術證據

| 能力 | 專案中的證據 |
| --- | --- |
| Python / FastAPI | 合約審查服務、API 與本機 GUI backend |
| React / TypeScript | 合約輸入、Provider 設定與 Markdown 報告介面 |
| SQLite | 法條快取、審查規則與可重建的本機資料 |
| Tool Calling | 多種 provider 的 native tool protocol 與共用唯讀法條工具 |
| MCP | 對外提供法條搜尋、候選檢索與精確查詢 |
| Testing | Provider contract、API、法條檢索與報告引用測試 |
| Windows delivery | 雙擊啟動、PowerShell runtime 與 release zip 流程 |

## 展示方式

建議面試時先使用 dry-run，證明即使沒有 API key，系統仍具備本機規則、法條檢索、來源網址與固定報告結構；再切換模型，說明 provider 是可替換邊界。

可展示：

- 同一份租賃合約在甲方與乙方立場下的不同建議；
- 法條引用與官方來源連結；
- 模型 native tool calls 使用後端法條工具；
- API key 遮罩與純本機 dry-run。

## 90 筆標註案例離線評估

使用內附標註資料包，測量合約分類、規則風險、主題命中、法條映射與 dry-run 報告結構：

```bash
python -m scripts.evaluate --out-dir reports
```

會輸出 `reports/evaluation.md`（適合履歷呈現的指標表）與 `reports/evaluation.json`（各案例細節）。GitHub Actions 會在 CI 中執行並提供 `offline-evaluation` artifact 下載。**這不是 LLM 回答準確率，也不代表法律審查正確率。** `citation_relevance` 是法條映射命中的代理指標，並非人工法律相關性評分；每筆只有一個預期風險主題，不能宣稱完整多標籤 Recall。

## 體驗與深入閱讀

- [一般使用者快速開始](START_HERE.zh-TW.md)
- [繁體中文操作手冊](USER_GUIDE.zh-TW.md)
- [本機開發、Provider 與測試說明](DEVELOPMENT.md)
- [架構概覽](docs/overview.md)

## 安全與限制

- 使用遠端模型時，合約文字可能送往所選 provider；敏感合約應優先使用 dry-run 或受控本機模型。
- .env、API key 與本機資料庫不應提交。
- 支援 TXT、含文字層的 PDF 與 DOCX；掃描 PDF、圖片與舊版 .doc 不支援，需先 OCR 或轉換。
- 本機快取與模型輸出都不能取代最新官方法規確認與專業法律意見。

## 授權條款

MIT License。詳見 [LICENSE](LICENSE)。
