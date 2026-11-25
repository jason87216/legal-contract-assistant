# 台灣合約審查 90 筆標註案例評估

- 案例數：90
- 評估模式：本機規則 + 法條檢索 + dry-run 報告（**不呼叫 LLM**）
- 注意：本報告不能代表生成模型、真實法律準確率或實際法律意見品質。

| 指標 | 通過／適用案例 | 比率 | 定義 |
| --- | ---: | ---: | --- |
| `contract_type_accuracy` | 90/90 | 100.0% | 分類器與標註類別一致（獨立分類器，非 Web auto 模式） |
| `risk_level_accuracy` | 75/80 | 93.8% | 審查上下文風險等級符合標註（只計規則負責判斷的案例） |
| `risk_theme_recall` | 80/80 | 100.0% | 預期風險由對應的新規則命中；無風險案例須沒有規則命中 |
| `citation_presence` | 90/90 | 100.0% | 相關法條列表非空；不代表法律引用正確 |
| `citation_relevance` | 50/50 | 100.0% | 預期風險主題已定義的法條映射，至少命中一條（代理指標） |
| `manual_review_flag` | 90/90 | 100.0% | dry-run 報告包含人工覆核及免責提醒 |
| `report_structure` | 90/90 | 100.0% | dry-run 報告包含必要標題與固定段落 |

## 解讀限制

- 測試包的標籤沿用舊規則的風險主題；`scripts/testpack_theme_map.json` 記錄每個舊主題由哪些新規則負責。改交 LLM 或刪除的主題（保固條款不明、價金稅費不明、所有權移轉不明、標的規格不明、片面沒收已付款、租賃範圍不明、管轄條款不利、續租條件不明、試用期條款不明、轉租約定不明）不計入規則的風險等級與主題命中。
- 每筆案例只有一個預期風險主題，因此 `risk_theme_recall` 是單一標籤命中率，並非完整多標籤召回率。
- `citation_relevance` 僅檢查規則內的法條映射命中，不是由律師人工評分的引用正確率。
- `citation_presence` 只是有無引用；不能推論引用完整、最新或法律上適當。
- `manual_review_flag` 與 `report_structure` 評估固定報告模板的涵蓋情況，不是 AI 文筆品質。
- 這 90 筆資料已被既有規則測試使用；本評估可能與規則設計相互對齊，**不能視為獨立、未見過的測試資料**。未來需另外保留未參與調整的案例。

## 未通過案例（每項最多列 20 筆）

- `contract_type_accuracy`：無
- `risk_level_accuracy`：sale_16, sale_18, sale_27, lease_13, lease_30
- `risk_theme_recall`：無
- `citation_presence`：無
- `citation_relevance`：無
- `manual_review_flag`：無
- `report_structure`：無
