# TENERA AI Brief Engine — MVP

## Run locally
```bash
pip install -r requirements.txt
python app.py
```
Open http://localhost:7860.

## Optional model endpoint
Set `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` as environment variables / Studio secrets. The app expects an OpenAI-compatible Chat Completions endpoint. Obtain the correct endpoint and model ID from the provider console; this template intentionally does not guess them.

Without model credentials, the app generates a prompt for ChatGPT. Paste ChatGPT's JSON response into the import tab to save a new brief version.

## ModelScope deployment
Use a Gradio Studio with `app.py` as entrypoint. Upload/push the project, configure secrets, then deploy. Do not commit API keys.

## Current MVP boundaries
- Parses PDF, DOCX, XLSX, CSV, TXT; image files are registered but not visually interpreted yet.
- Stores products, versions, feedback, approval proposals and approved brand rules in SQLite.
- Default data directory: `/mnt/workspace/tenera_brief_engine` (verify platform persistence and backup before production).
- No user login/RBAC, external object storage, automatic backups, or polished PDF/DOCX exports yet.
- ModelScope app and a ChatGPT consumer chat do not automatically share session context. The current bridge is prompt export + JSON import. Direct API collaboration requires separate API credentials.

## Approval rule
Product-level drafts may be generated automatically. Brand-wide rules and global marketing strategy changes require explicit human approval.
