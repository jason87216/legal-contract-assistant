# Legal Contract Assistant

台灣合約審查本機 Agent。支援買賣、勞動、租賃三類合約，使用本地 SQLite 法條與審查規則產生可追溯的 Markdown 風險報告，並提供 FastAPI + React GUI。

> This tool is for preliminary contract risk review only. It is not legal advice.

## Features

- Local GUI: FastAPI serves a React interface at `http://127.0.0.1:8787`.
- Contract modes: sale, labor, lease, or auto classification.
- Input methods: paste text or upload `.txt`.
- Local dry-run: generate reports without API keys or external network calls.
- Optional LLM providers: OpenAI, OpenRouter, and llama.cpp via OpenAI-compatible chat completions.
- API key handling: keys are saved only to local `.env` and shown as masked values in the GUI.
- Traceable output: reports include related statutes, source URLs, risk themes, missing items, and disclaimer.
- Package workflow: build a timestamped zip release with PowerShell.

## Requirements

For normal packaged GUI use:

- Windows 10/11
- Python 3.11+

For development or rebuilding the frontend:

- Node.js 20.19+
- npm

The packaged release includes `frontend/dist`, so end users usually do not need Node unless the frontend build is missing or they want to rebuild it.

## Quick Start

Clone the repository:

```powershell
git clone https://github.com/jason87216/legal-contract-assistant.git
cd legal-contract-assistant
```

Start the local GUI:

```powershell
.\start-gui.ps1
```

Open the browser if it does not open automatically:

```text
http://127.0.0.1:8787
```

First test without an API key:

1. Select `租賃合約`.
2. Paste:

```text
甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。
```

3. Do not check `使用 API 模型產生報告`.
4. Click `產生審查報告`.

Expected result: a Markdown report containing `合約審查報告`, statute citations, source URLs, risk notes, and disclaimer.

## API Key Settings

The GUI supports:

- OpenAI
- OpenRouter
- llama.cpp

Settings are stored in a local `.env` file in the project folder. This file is ignored by Git and is not included in release zips.

For llama.cpp, the default base URL is:

```text
http://127.0.0.1:18080/v1
```

The default local model name is:

```text
local-chat
```

If your llama.cpp server does not require a real key, you may use:

```text
sk-no-key-required
```

## CLI Usage

Generate a dry-run report:

```powershell
python -m src.legal_contract_assistant.main --contract-type lease --text "甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。"
```

Use local llama.cpp:

```powershell
python -m src.legal_contract_assistant.main --contract-type lease --use-local-llama --model-provider llama.cpp --model local-chat --model-base-url http://127.0.0.1:18080/v1 --text "甲方為出租人，乙方為承租人。乙方每月支付租金，房屋修繕由雙方約定。"
```

## Build Release Zip

Build frontend assets and create a timestamped release zip:

```powershell
.\build-release.ps1
```

The release zip includes:

- `src/`
- `frontend/dist/`
- `requirements.txt`
- `start-gui.ps1`
- `README.md`
- `RELEASE_NOTES.md`
- `USER_GUIDE.zh-TW.md`

The release zip excludes:

- `.env`
- `.venv`
- `node_modules`
- `.cache`
- `dist` development artifacts
- `__pycache__`
- `*.pyc`

## Run Tests

Create and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run Python tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Build frontend:

```powershell
cd frontend
npm install
npm run build
cd ..
```

Current expected test result:

```text
24 passed
```

## Project Structure

- `src/legal_contract_assistant/`: Python backend, contract review workflow, statute cache, LLM provider boundary, and FastAPI app.
- `src/legal_contract_assistant/data/`: Seed statute articles and review rules.
- `frontend/`: React + Vite GUI source.
- `tests/`: pytest suite for CLI, cache, testpack metrics, and FastAPI API.
- `docs/`: project notes and roadmap.
- `RELEASE_NOTES.md`: release environment, privacy, and known limitations.
- `USER_GUIDE.zh-TW.md`: user-facing Traditional Chinese guide.
- `start-gui.ps1`: one-command local GUI startup.
- `build-release.ps1`: release zip builder.

## Data And Review Scope

The MVP focuses on:

- 買賣合約
- 勞動合約
- 租賃合約

The local database currently contains cached statutes and structured review rules for the first-pass review workflow. Formal use should still verify the latest official statute text and consult a qualified professional.

## Security Notes

- Do not commit `.env`.
- Do not commit API keys, tokens, private keys, or auth files.
- Remote model calls may send contract text to the selected provider.
- Use dry-run mode if the contract must stay fully local.

## Known Limitations

- TXT and pasted text only; PDF, DOCX, and OCR are not supported yet.
- The report is a preliminary risk check, not formal legal advice.
- The rule system is keyword/rule based and should be manually reviewed.
- LLM output is constrained by provided related articles, but still requires human verification.

## License

No license has been selected yet. Add a license before public reuse or distribution.
