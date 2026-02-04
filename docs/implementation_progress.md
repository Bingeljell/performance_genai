# Implementation Progress (Prototype)

Date: 2026-02-04

This doc captures what has been built so far in the repo, what is working, what is intentionally rough, and the proposed next steps based on recent discussion.

---

## What We Have Built

### 1) FastAPI Prototype + Simple Web UI

Entry point:
- `src/performance_genai/api/app.py`

Pages:
- `/` lists projects and allows creating a project.
- `/projects/{project_id}` is the main project workspace page.

Project UI features:
- Upload assets with kind: `reference`, `product`, `motif` (transparent PNG recommended).
- Preview thumbnails for uploaded assets, KVs, and generated outputs.
- KVs and Masters have:
  - per-item open link
  - delete button
  - bulk select + bulk delete
- Project delete button.

### 2) File-Based Storage + Run Registry

Storage:
- `src/performance_genai/storage.py`
- Outputs persist under `data/projects/<project_id>/...`

Folders created per project:
- `assets/` (uploads)
- `motifs/` (motif uploads)
- `profiles/` (observed profile JSON)
- `kvs/` (generated KVs + reframed KVs)
- `masters/` (deterministic Pillow masters)
- `runs/` (run manifests)

Run manifests:
- Every operation writes a JSON manifest under `data/projects/<project_id>/runs/`.
- Manifests include provider/model, inputs, outputs (asset IDs).

### 3) Gemini + OpenAI Integration

Gemini (via `google-genai`):
- `src/performance_genai/providers/gemini_provider.py`
- Capabilities implemented:
  - `propose_observed_profile(...)` from uploaded images (vision -> JSON-like profile)
  - `summarize_brand_language_for_copy(...)` from uploaded images (vision -> bullets)
  - `generate(...)` for KV generation:
    - uses `image_config.aspect_ratio`
    - loops for preview-model behavior that returns fewer images per call
  - `reframe_kv_with_motif(...)` for ratio-specific text-free visuals:
    - uses `image_config(aspect_ratio, image_size)`
    - supports optional motif reference image
    - uses an "outpaint canvas" (locked center) to reduce drift

OpenAI:
- `src/performance_genai/providers/openai_provider.py`
- `generate_copy(...)` for headlines (v0: line list).

### 4) Deterministic "Masters" (Pillow)

Renderer:
- `src/performance_genai/assembly/render.py`

Current behavior:
- cover-crop (no stretching)
- gradient scrim
- headline + CTA rendering (CTA uses a button)
- optional motif overlay via deterministic placement controls

Note:
- This deterministic masters path is working, but it has started to feel redundant if we rely on AI reframe for ratio-specific "final visuals" and let humans place text.

---

## What Is Working (Today)

- Creating projects and uploading images/motifs.
- Generating small KV pools from a prompt (Gemini image model).
- Extracting an observed profile from images (Gemini vision).
- Generating headlines and showing them in the UI.
- AI reframe to target ratios (e.g. 9:16) with `image_config` producing correct dimensions.
- Bulk delete for KVs and Masters.

---

## Known Issues / Limitations

### 1) AI Reframe Drift

Even when aspect ratio is correct, the image model may:
- change parts of the scene
- drift the motif style/shape if a motif asset is not supplied
- vary output between runs

Mitigations already added:
- stricter reframe constraints (preserve base image; outpaint only)
- "locked canvas" input to bias the model toward extending margins
- "do not invent motif" instruction when motif is not provided

Remaining gap:
- This is still not deterministic; it is inherently model-dependent.

### 2) Motif Placement Is Hard to Make Perfect Deterministically

Deterministic motif placement will generally require either:
- a UI to adjust placement/scale per visual, or
- subject segmentation so motif can sit behind subject cleanly

We experimented with deterministic heuristics (rectangular subject protection), but it is not robust across all compositions.

### 3) "Masters" vs "Ratio-Specific Visuals"

If the tool uses AI reframe to generate final ratio-specific visuals, the current deterministic masters section:
- duplicates effort
- is less useful than expected (especially when motif interaction matters)

### 4) Missing "Designer Controls"

To make this usable across an agency (and for motif-heavy brands), we will likely need:
- subject isolation (cut out subject/product as a separate layer)
- a simple editor for text/logo/motif placement
- live multi-ratio previews while working (so users can validate adapts early)

---

## Product Discussion Summary (Current Direction)

We discussed simplifying the experience and focusing on "master visual correctness" over deterministic text rendering.

Proposed flow:
1) User uploads references (and optionally motif).
2) User enters prompt to generate a small pool of master visuals (n options, max 5).
3) Tool generates and displays the pool.
4) User shortlists selected options.
5) User picks ratios for the shortlisted options.
6) Tool generates ratio-specific visuals (AI reframe/outpaint) for each shortlisted option and each ratio.
7) Text placement can be manual (designer) in the short term, since it is easier than getting motif + subject interactions perfect with deterministic compositing.
8) Longer term, add a lightweight editor so users can place text/logo/motif and preview multiple ratios before export.

Rationale:
- AI reframe handles motif/subject interaction better than deterministic cropping.
- Designers can place text manually while we learn what visuals are stable.
- Keeps the v0 prototype focused and reduces UI clutter.

---

## Strategy Notes (Scaling Beyond One Team)

We want v0 to solve an immediate internal need, but still be on a path to agency-scale usage.

Recommended shape:
- Keep this repo as the "creative engine" (Python/FastAPI + providers + rendering) for now.
- If/when we productize, add a separate "control plane" (potentially your existing Laravel app) for:
  - auth/session management
  - quotas/budgets
  - team/project permissions
  - billing/usage reporting
- Connect them via an internal API (Laravel -> Python engine) with service-to-service auth (API key/JWT) and audit logs.

---

## Proposed Next Steps

### A) Workflow Simplification (Shortlist -> Ratios)

- Rename / refactor sections:
  - "KVs" -> "Visual Pool"
  - "AI Reframe KV" -> "Generate Ratios"
- Add shortlist state:
  - per-visual checkbox "Shortlist"
  - or a dedicated "Shortlisted" section
- Add a single "Generate ratios for shortlisted" action:
  - choose ratios (1:1, 4:5, 9:16, optionally 16:9)
  - choose image_size (1K/2K/4K)

### B) Deprecate "Masters (Assembly)" In UI (For Now)

- Either remove it from the UI or move it into an "Advanced" accordion.
- Keep deterministic text assembly as a later phase when we want scale/repeatability.

### C) Subject Isolation + Layering (Required For Motifs)

- Add "Cut out subject/product" as a first-class operation:
  - input: chosen KV
  - output: transparent PNG subject layer + mask (stored as assets)
- This unlocks correct stacking:
  - background (AI-generated)
  - motif behind subject
  - subject layer on top
  - text/logo layers on top

### D) Multi-Ratio Preview While Working

- While editing a visual, always show previews in a few key ratios (e.g. 1:1, 4:5, 9:16).
- Implementation direction:
  - deterministic render from a stored `render_spec.json` (layer model)
  - optional AI outpaint pass only when background extension is needed

### E) Better Control for Motif When Asset Is Missing

- Add a guided "extract motif from reference image" workflow:
  - user selects a reference image
  - user selects a crop region
  - tool attempts to extract line-art mask and saves it as a motif asset

### F) Strengthen Traceability

- Ensure reframed visuals carry metadata:
  - source_kv_asset_id
  - aspect_ratio + image_size
  - motif_asset_id (if provided)
  - prompt used

---

## Current Endpoints (For Reference)

From `src/performance_genai/api/app.py`:
- `GET /`
- `POST /projects`
- `GET /projects/{project_id}`
- `POST /projects/{project_id}/assets/upload`
- `POST /projects/{project_id}/delete`
- `POST /projects/{project_id}/assets/{asset_id}/delete`
- `POST /projects/{project_id}/assets/bulk_delete`
- `GET /projects/{project_id}/assets/{asset_id}`
- `POST /projects/{project_id}/profile/propose`
- `POST /projects/{project_id}/kvs/generate`
- `POST /projects/{project_id}/kvs/reframe`
- `POST /projects/{project_id}/copy/headlines`
- `POST /projects/{project_id}/masters/build`
