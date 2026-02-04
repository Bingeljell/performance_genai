# performance_genai (prototype)

Minimal, API-first prototype for generating performance creatives:
- FastAPI backend + simple web UI
- Text-free KV (visual) generation via Gemini (Imagen / `gemini-3-pro-image-preview`)
- AI reframe/outpaint to generate ratio-specific visuals (e.g. 1:1, 4:5, 9:16)
- File-based project storage + run manifests (good enough for v0)

Docs:
- `docs/implementation_progress.md` (what we have built + current workflow direction)
- `docs/implementation_poa.md` (implementation plan / roadmap)
- `spec.md` (product spec)

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
export GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"  # or "imagen-3.0-generate-002"
export OPENAI_TEXT_MODEL="gpt-4.1-mini"
```

Run:
```bash
uvicorn performance_genai.api.app:app --reload --port 8000
```

Open:
- http://127.0.0.1:8000

## Notes

- This is a prototype: no auth, no background job queue, and minimal validation. For internal use, run behind a VPN / IP allowlist / reverse proxy auth.
- Outputs are stored under `./data/projects/<project_id>/...`.
