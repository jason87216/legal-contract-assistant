# 評測計畫與執行說明

本文件列出專案所有評測：每一項量什麼、用哪些資料、怎麼執行、結果放哪裡，以及能與不能據此宣稱什麼。定位是作品等級：方法與取捨要說清楚，樣本小但誠實標示。

## 資料分三組

| 資料 | 位置 | 用途 | 能否用來調整規則 |
| --- | --- | --- | --- |
| 調整集 | `tw_contract_review_testpack_v1.zip`（90 筆）、`eval/generated_cases/`（Antigravity 產生 110 筆）、`eval/judgment_clauses.jsonl`（判決書引述的條款 30 條，2026-11-26 起） | 回歸測試：改規則後不能變差 | 可以；分數不代表準確率 |
| 範本集（待建） | 官方定型化契約範本 | 誤報：合法條款不應被判成風險 | 只能謹慎修誤報 |
| 測試集（待建） | 新一批判決條款，取代已用掉的判決集 | 漏抓、精確率、法條是否與法院一致 | 不行；測完即凍結，用過就改列調整集 |

判決集第一次評分時規則沒有依它調整過，那次的分數記在第 5 步；之後依使用者審核改了規則，所以改列調整集。

## 整份合約的風險等級

- 觸發 3 條以上不同的高風險規則，整份合約是高風險。
- 觸發 1～2 條高風險規則，或任何中風險規則，整份合約是中風險。
- 沒有觸發規則時是低風險，但 3 項以上必要條款沒有寫到時改判中風險。

同一條規則在合約中出現多次只算一條。每條觸發的規則仍逐項列在報告裡，門檻只影響整份合約的等級標籤（使用者決定，2026-11-26）。

所有分數都要連同規則版本（commit 編號）一起記錄。

## 環境準備

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
# 只有要測 RAG 時才需要（約 2 GB，含 PyTorch 與模型下載）
.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
```

LLM 評測需要 Gemini API key，放在環境變數或專案根目錄的 `.env`（不要提交）：

```
LCA_GEMINI_API_KEY=你的key
```

確認可用的免費模型名稱（模型名稱會變動，執行前先查）：

```powershell
$key = $env:LCA_GEMINI_API_KEY
(Invoke-RestMethod "https://generativelanguage.googleapis.com/v1beta/models?key=$key").models.name
```

## 要執行的測試（依序）

### 1. 單元測試（不呼叫模型）

```powershell
.venv\Scripts\python.exe -m pytest -q
```

預期全部通過。包含調整集的回歸測試（測試包 90 筆、產生案例 110 筆），以及 LLM 評測流程用假回應的端到端測試。

### 2. 規則：測試包 90 筆

```powershell
.venv\Scripts\python.exe -m scripts.evaluate --out-dir reports
```

輸出 `reports/evaluation.md`。測試包標籤沿用舊規則主題，`scripts/testpack_theme_map.json` 對應到新規則；改交 LLM 的主題不計分。測試包每筆只標一個風險主題，且沿用「一條高風險就是高風險」的舊定義，所以計算風險等級正確率時，標為高風險的案例改以中風險比對（`expected_level()`）。

### 3. 規則：產生案例 110 筆

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_generated
```

輸出 `reports/generated_cases.md`：正常合約誤報、各規則不同寫法的命中、相近合法寫法的誤報、類型混淆案例的分類。混淆案例分類錯誤是已知限制（使用者自選類型，分類器只需夠用）。

### 4. 檢索：關鍵字、向量、混合（需要 RAG 選裝套件）

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_retrieval --out-dir reports
```

輸出 `reports/retrieval_evaluation.md`。沒裝選裝套件時，向量與混合會標示略過。第一次執行會下載向量模型並建立索引（約 3,700 條法條），之後讀快取。詳見 [RAG 說明](RAG.md)。

目前的標準答案是規則引用的法條，有資料洩漏，只能比較做法；判決集完成後改用法院實際適用的條文。

### 5. 規則：判決條款 30 條

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_judgments
```

輸出 `reports/judgment_clauses.md`。資料在 `eval/judgment_clauses.jsonl`：6 類合約各 5 條，取自地方法院判決書引述的條款，只保留條款、案號、法院適用的條文與標註，不含當事人姓名。每條逐一跑該類型的規則；「缺少某約定」類的規則因為單一條款看不到整份合約而不計，除非標註本來就預期它。

| 指標 | 定義 |
| --- | --- |
| 風險條款被抓到 | 標為風險的條款，預期規則至少一條觸發 |
| 正常條款誤報 | 標為正常的條款，有任何規則觸發 |
| 觸發的規則中屬於預期規則 | 觸發次數中，有幾次是標註預期的 |
| 法院適用條文被規則法條涵蓋 | 抓到的風險條款，法院適用的條文有幾條出現在觸發規則的法律依據 |

結果：

| 指標 | 第一次評分（規則未調整） | 審核並調整規則後 |
| --- | --- | --- |
| 風險條款被抓到 | 8/13 | 13/13 |
| 正常條款誤報 | 1/16 | 0/15 |
| 觸發的規則中屬於預期規則 | 9/10 | 14/14 |
| 法院適用條文被規則法條涵蓋 | 6/9 | 7/15 |
| 不計分 | 1 條 | 2 條 |

只有第一次評分可以當作規則在沒看過的條款上的表現。調整後的分數依這批條款改過規則，只能當回歸檢查。法院條文涵蓋率下降，是因為新抓到的條款（例如 lease_04 的民法 §432、§438，labor_04 的勞基法 §9-1）不在觸發規則的法律依據裡。

使用者審核（2026-11-26）後的修改：
- 標註：work_05 改為風險（預期 `shared_high_liability_fully_excluded`）。work_02 不計分（`rule_scope: "skip"`）。labor_04 的預期規則改為 `labor_medium_confidentiality_overbroad`。sale_01、loan_05 的違約金維持風險，因為風險提醒不等於法院會判無效。
- 規則：
  - `shared_high_penalty`：加入「違約賠償金」（labor_01）。
  - `shared_high_liability_fully_excluded`：加入「無須…負擔任何…責任」（work_05）。
  - `lease_medium_deposit_landlord_discretion`：加入「出租人得逕自押金內扣除」（lease_04）。
  - `labor_medium_confidentiality_overbroad`：加入離職後保密、營業秘密義務，requires 補上「受雇」寫法（labor_04）。
  - `shared_high_interest_over_cap`：加入「月息 N 分」的口語寫法（loan_04）。
  - `lease_high_deposit_over_cap`：月數改成完整讀取小數，「1.8個月」不再被讀成「8個月」，「3.5個月」照樣觸發（lease_01 誤報）。
- 調整前後，產生案例 110 筆的報告內容相同，新寫法沒有造成新的誤報。

限制：
- 標註由 Claude Code 完成，使用者已審核。第一次評分後補標過兩處（labor_01、labor_03 漏標「有寫就是高風險」的違約金規則），已寫在該條的 note。
- 委任 5 條都是正常條款，找不到判決引述的委任風險條款，所以委任只量誤報。
- 部分條款是判決轉述的約定內容而非契約原文（`source_kind`），口語寫法較多。
- 法院條文只列判決書明文引用的實體法條；判決沒引用時留空，不算進涵蓋率。

### 6. LLM 第一階段（需要 Gemini key）

先用 1 份合約試跑，確認 key、模型名稱與網路都正常：

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_llm run --model <模型名稱> --limit 1 --runs 1
```

再跑完整一輪：

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_llm run --model <模型名稱>
```

- 合約：`eval/llm_cases.json` 固定 18 份，6 類合約各一份正常、中風險、高風險。
- 兩種做法：
  - **pipeline**：規則、法條、候選法條與法條查詢工具，同一份合約跑 3 次（穩定性）；
  - **baseline**：只給合約全文和同樣的報告要求，不給法條也不給工具，跑 1 次。
- 呼叫次數：pipeline 每份 1～2 次（有工具呼叫時 2 次），54 份；baseline 18 份；合計約 72～126 次。預設每分鐘 8 次（`--rpm`），約 10～16 分鐘。遇到 429 或 5xx 會自動等待重試。
- 免費額度有每日上限，執行前到 Google AI Studio 確認。額度用完中斷時，用 `--resume <結果資料夾>` 接續，已存的回覆不會重跑。
- 每次回覆存在 `reports/llm_eval/<時間>-<模型>/raw/`，`summary.md` 是結果。要改計分方式時，不必重新呼叫模型：

```powershell
.venv\Scripts\python.exe -m scripts.evaluate_llm score reports/llm_eval/<結果資料夾>
```

指標（都不需要標準答案）：

| 指標 | 定義 | 解讀 |
| --- | --- | --- |
| 不存在的法條 | 報告引用的法條在匯入法規中不存在（例如 民法 第 9999 條） | 編造法條，越低越好 |
| 存在但未提供 | 法條存在，但不在提供給模型的法條或工具結果中 | pipeline 違反「只能引用提供的法條」 |
| 法規不在資料庫 | 引用了未匯入的法規（例如 票據法） | 無法自動查核，需人工看 |
| 規則風險有寫進報告 | 規則找到的風險，報告有提到主題、引用其法條或引述觸發條款 | 近似判斷；baseline 看模型自己能否找到同樣的風險 |
| 穩定性 | pipeline 同一合約 3 次的引用法條、寫進報告的風險，兩兩相似度（Jaccard） | 越高越穩定 |
| 工具呼叫、token、秒數 | 每份報告的成本 | 比較成本 |

最值得看的是 pipeline 與 baseline 兩欄的差距：規則與法條提供給模型後，編造法條與遺漏風險是否明顯下降。

變化做法（選做）：`--no-tools` 跑沒有工具的 pipeline，比較工具的貢獻；`LCA_RETRIEVAL_METHOD=hybrid` 環境變數讓候選法條與工具改用混合檢索，比較 RAG 開關。

### 7. 帶回來的結果

把以下檔案帶回（或推上 GitHub）即可分析：

- `reports/evaluation.md`、`reports/generated_cases.md`、`reports/judgment_clauses.md`、`reports/retrieval_evaluation.md`
- `reports/llm_eval/<結果資料夾>/` 整個資料夾（含 `raw/`，可重新計分）

## 尚未完成

| 項目 | 狀態 |
| --- | --- |
| 範本集：官方範本轉文字，跑規則看誤報 | 待建 |
| 判決集：6 類合約各 5 條短條款 | 已審核，依審核調整規則後改列調整集 |
| 判決集計分 | 已完成（`scripts/evaluate_judgments.py`） |
| 新的判決測試集：取代已用掉的判決集 | 待建 |
| LLM 第二階段：評審模型、檢查清單判斷、規則外的風險 | 待做；評審需先與人工判斷校準 |

## 已知限制

- 調整集曾用於撰寫或調整規則，分數不代表真實準確率。
- 「規則風險有寫進報告」是字面近似判斷，可能低估換句話說的報告。
- 引用法條擷取以「法規名稱＋第 N 條」為準；沒寫法規名稱的條號（例如合約第五條）不計。
- LLM 結果會隨模型版本與溫度變動，記錄時要寫明模型名稱與日期。
