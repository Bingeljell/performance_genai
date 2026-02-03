# performance_genai (prototype)

Minimal, API-first prototype for generating ad creatives:
- FastAPI web UI
- KV generation via Gemini (Nano Banana / Imagen-style) or other provider as you wire in
- Deterministic master rendering via Pillow (headline + CTA over KV)
- File-based project storage + manifests (good enough for v0)

## Quickstart

Prereqs:
- `python3` and `uv`

Install deps:
```bash
uv venv
uv pip install -e .
```

Set API keys (choose what you have).

Option A: put them in `.env` (recommended for local dev):
```bash
cp .env.example .env
# edit .env and fill in keys
```

Option B: export in your shell:
```bash
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="..."
```

Optional model overrides (defaults are intentionally conservative placeholders):
```bash
export GEMINI_VISION_MODEL="gemini-2.0-flash"
export GEMINI_IMAGE_MODEL="imagen-3.0-generate-002"
export OPENAI_TEXT_MODEL="gpt-4.1-mini"
```

Run:
```bash
uvicorn performance_genai.api.app:app --reload --port 8000
```

Open:
- http://127.0.0.1:8000

## Notes

- This is a prototype: no auth, no background job queue, and minimal validation.
- Outputs are stored under `./data/projects/<project_id>/...`.
