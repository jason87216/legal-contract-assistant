# Overview

中文備註：這份文件給專案維護者、GitHub 開發者與 Agent 看，用來快速理解產品目標、範圍邊界與開發里程碑；一般使用者請優先看 `START_HERE.zh-TW.md` 或 `USER_GUIDE.zh-TW.md`。

## Problem

Contract review is slow when key obligations, renewal terms, liability caps, and termination conditions are buried in long documents.

中文備註：本專案要解決的是「合約太長，重要風險條款不容易被快速看見」的問題，例如義務、續約、責任限制、終止條款。

## Initial Scope

- Accept pasted contract text.
- Support sale, labor, and lease contracts in the first version.
- Extract core contract metadata.
- Highlight common clause categories.
- Summarize notable risks in plain language.

中文備註：第一版只做文字輸入與三種合約模式：買賣、勞動、租賃。重點不是取代律師，而是先把常見風險、相關法條、缺漏事項整理成可讀報告。

## Non-Goals

- Giving formal legal advice.
- Auto-signing or auto-approving contracts.
- Supporting every contract type in the first version.
- Calling external LLM APIs in the first local MVP.

中文備註：這些是不做的事。尤其「不提供正式法律意見」很重要；系統輸出只能當初步檢查，不能當最終法律判斷。

## Milestone 1

- Basic CLI flow
- Structured result format
- Cache-first statute lookup for sale, labor, and lease contracts
- Markdown report with citations, source URLs, missing items, and disclaimer
- Replaceable LLM provider interface with a no-network default

中文備註：第一階段已從 CLI 擴展到本機 GUI。核心成果是本地法條快取、固定報告格式、dry-run 模式、可替換的 LLM provider 介面。

## Milestone 2

- Live lookup for uncached statute articles
- Review rules, template clauses, and risk examples
- LLM-backed clause review
- Prompt templates per contract type
- Markdown or JSON report export

中文備註：下一階段應優先做「長合約分段審查」、「法源資料補強」、「更細的規則與風險分類」。即時查詢法條可以做，但要避免不穩定來源影響報告品質。
