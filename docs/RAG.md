# 選用法條向量檢索

預設使用 `keyword` 關鍵字檢索。向量檢索用本機模型將法條及查詢轉成數值向量，再依餘弦相似度排序。審閱規則仍提供報告的主要法律依據，檢索額外提供候選法條，也可供模型搜尋法條。

## 安裝與首次建索引

在專案根目錄以 PowerShell 執行，建議使用 Python 3.12 的專案虛擬環境。如果虛擬環境沒有 pip，可以使用既有的 uv。

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-rag.txt
$env:LCA_RETRIEVAL_METHOD = "vector"
.venv\Scripts\python.exe -c "from src.legal_contract_assistant.statute_tools import StatuteRetrievalTool; tool=StatuteRetrievalTool(); tool.initialize(); print(tool.call_tool('search_statutes', {'query': '押金', 'limit': 1}))"
```

第一次向量查詢會載入預設模型 `BAAI/bge-m3`，本機尚未快取模型時會嘗試下載。可在啟動前用 `LCA_EMBED_MODEL` 設定另一個 Sentence Transformers 模型。每條法條以法規名稱、條號、主題與條文組成一筆向量，索引存於 `.cache/vectors-*.npz`。模型名稱、官方資料版本或索引文字變動時會產生新索引。查詢向量與合約文字在本機處理，索引只保存法條向量與法條識別鍵。

## 切換方法

- `keyword` 沿用關鍵字評分。
- `vector` 依餘弦相似度排序。
- `hybrid` 以倒數排名融合（RRF，k=60）加總兩份排名的分數。只有出現在該排名中的法條才獲得該排名的分數。

可設定 `$env:LCA_RETRIEVAL_METHOD = "hybrid"` 後啟動工具，或在 Python 呼叫時明確傳入 `method`。設定 `keyword` 即可切回原模式。向量與混合模式在同分時優先取該契約類型的主要法條，再取次要法條。`curated` 只搜尋精選候選法條，`all` 也包含其他已匯入的官方法條。合約候選檢索依條號或空白行切分條款，再以每條法條的最高分合併查詢結果。

缺少選用套件、模型載入失敗或索引不可用時會回到關鍵字檢索。工具結果與候選結果會用 `retrieval_method` 標示實際方法，並附 `warning`。`search_statutes()` 的 Python 回傳值仍為列表，降級資訊附在有回傳的法條上。若需要空結果的降級資訊，可用 `call_tool("search_statutes", ...)`。

## 評估與限制

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_retrieval
```

評估交叉比較三種方法、整份契約與規則命中的條款，以及精選與全部法條範圍。報告顯示前 5／12 筆命中率和平均倒數排名（MRR），以風險主題對應的審閱規則引據作為比對目標。無法啟用向量時，報告會註記並略過該模式。測試案例先前也用於編寫審閱規則與詞表，因此數值適合比較檢索設定，無法據此推估新合約的審閱準確率。

模型可能截斷超出輸入上限的長條文或條款。每次查詢以 NumPy 掃描全部法條向量，速度與記憶體需求會隨法條數量、向量維度及合約條款數增加。檢索分數代表候選排序，各模式的分數尺度不同。
