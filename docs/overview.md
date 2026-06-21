# Overview

## Problem

Contract review is slow when key obligations, renewal terms, liability caps, and termination conditions are buried in long documents.

## Initial Scope

- Accept pasted contract text.
- Support sale, labor, and lease contracts in the first version.
- Extract core contract metadata.
- Highlight common clause categories.
- Summarize notable risks in plain language.

## Non-Goals

- Giving formal legal advice.
- Auto-signing or auto-approving contracts.
- Supporting every contract type in the first version.
- Calling external LLM APIs in the first local MVP.

## Milestone 1

- Basic CLI flow
- Structured result format
- Cache-first statute lookup for sale, labor, and lease contracts
- Markdown report with citations, source URLs, missing items, and disclaimer
- Replaceable LLM provider interface with a no-network default

## Milestone 2

- Live lookup for uncached statute articles
- Review rules, template clauses, and risk examples
- LLM-backed clause review
- Prompt templates per contract type
- Markdown or JSON report export
