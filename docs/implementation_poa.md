# Performance Creative Generation Tool — Implementation Plan of Action

This document provides a comprehensive implementation guide based on the detailed spec (`spec.md`).

---

## 0. Implementation Tighteners (Delta From Review)

These are small, high-leverage clarifications that will make the v1 implementation significantly easier to build, debug, and re-run deterministically.

### 0.1 Canonical IDs, Hashing, and Manifests (Make Runs Idempotent)

- Define stable IDs for every artifact type: `asset_id`, `observed_profile_id`, `enforced_profile_version`, `kv_id`, `copy_id`, `template_id`, `master_id`.
- Define a deterministic cache key for each step (KV gen, copy gen, masters build), e.g.:
  - `inputs_sha256` (files + normalized params)
  - `profile_version`
  - `provider`, `model`
  - `prompt` (or compiled prompt fragments)
  - `generation_params` (ratio, seed, etc.)
- Every command should emit a `run_manifest.json` capturing:
  - command name + timestamp
  - inputs hash + input asset IDs
  - profile version
  - provider/model + params
  - output artifact IDs + paths

This is the difference between "one-off scripts" and "reliably re-runnable".

### 0.2 Observed vs Enforced Profile Schema (Control Plane Contract)

- Observed profile should include:
  - proposed values
  - `confidence` per field
  - `evidence` pointers (reference asset IDs + notes)
- Enforced profile should include:
  - final values + strictness (`hard|soft|off`) per field
  - versioning (`profile_v1.json`, `profile_v2.json`, ...)
  - explicit defaults (so missing fields never mean "undefined behavior")

### 0.3 Profile Compiler (Enforced Profile -> Prompts + Gates + Defaults)

Treat the Enforced Profile as "source of truth", then compile it into:
- `compiled_prompt_fragments` (what actually gets sent to providers)
- `quality_gate_thresholds` (palette tolerance, avoid-color threshold, text-detection setting, clutter thresholds)
- `template_defaults` (e.g., default text color strategy, scrim behavior)

Persist this as a separate artifact (e.g., `profiles/compiled_profile_v1.json`) so downstream steps do not have to re-interpret rules.

### 0.4 Reserved Zones: Unify Safe Areas + Logo Boxes + Negative Space

The spec includes `logo_reserved_box` and `negative_space_zone/box`, while templates introduce `safe_areas`.

Recommendation: normalize these into a single concept used everywhere, e.g. `reserved_zones[]` with:
- `purpose` (`logo`, `headline_safe`, `cta_safe`, `platform_ui`, ...)
- `box` normalized `[x, y, w, h]`

Then enforce:
- KV quality gates score "clutter" inside `reserved_zones`
- template text boxes must not overlap forbidden reserved zones

### 0.5 Determinism Caveats (Masters)

If determinism matters across machines:
- vendor fonts (checked-in font files), pin font rendering settings
- avoid any "auto" behavior that depends on system fonts
- store the exact font file + font size used in the master manifest

(Pillow is fine for v1, but make the determinism boundary explicit.)

### 0.6 Async Boundaries (Provider SDK Reality)

Many provider SDK calls are sync even if we wrap them in `async def`.
Pick one approach early:
- keep provider methods sync and run them in a threadpool, or
- use a truly-async HTTP client layer

Avoid "fake async" that blocks the event loop during generation.

### 0.7 KV Quality Gates: Define Simple, Measurable Metrics

Start simple but explicit:
- Palette compliance: dominant colors in LAB + DeltaE tolerance; separately track avoid-colors over a threshold percentage.
- Text detection: staged (cheap heuristic -> OCR) to manage cost.
- Safe-area clutter: edge density / local contrast variance inside reserved zones.

Persist gate scores in KV metadata so the UI can filter/sort.

### 0.8 Python Package Layout (Avoid Import Pain)

Use a real package under `src/performance_genai/` so:
- imports are stable (`from performance_genai...`)
- CLI entry points and tests work predictably

### 0.9 Agency-Scale Extension (Roadmap Input)

If you plan to extend this beyond a single team to the whole agency, assume you will need:
- Centralized project storage (shared filesystem or object storage) vs purely local folders
- Multi-user access control + audit logs (who generated what, from which inputs, with which profile)
- Secret management for provider keys (no keys in local dotfiles for shared deployments)
- Cost/rate-limit controls (per-user and per-team budgets, concurrency limits)
- A template/font registry (versioned templates, licensed fonts, approved logo packs) so outputs stay consistent across teams
- A "server mode" or run coordinator eventually (even if v1 starts as a simple internal web app) so you can queue, resume, and observe runs centrally

## 1. Tech Stack Recommendations

### Core Framework

| Component | Recommendation | Rationale |
|-----------|---------------|-----------|
| **Language** | **Python 3.11+** | Best ecosystem for AI/ML, image processing, and CLI tools |
| **API Framework** | **FastAPI** | API-first architecture, easy to host internally, scales cleanly into a service |
| **UI (v0)** | Server-rendered templates (FastAPI/Starlette) | Fastest path to a usable internal tool without frontend build overhead |
| **UI (v1+)** | Next.js + TypeScript + canvas editor (Konva/Fabric) | Needed for real designer controls: layers, text editing, multi-ratio preview |
| **CLI Wrapper** | Typer (optional) | Useful for automation/batch runs; can call the same orchestration code as the API |
| **Config/Data** | **Pydantic v2** | Excellent for the Brand Style Profile schemas, validation, serialization |
| **Project Structure** | **Dataclass + JSON** files | Spec already defines folder structure; keep it simple |

### AI/ML Providers

| Component | Recommendation |
|-----------|---------------|
| **LLM Interface** | LiteLLM or custom abstraction over OpenAI, Gemini, Anthropic SDKs |
| **Image Gen** | Google GenAI SDK (Gemini/Imagen) as default; OpenAI DALL-E as alt |
| **Image Analysis** | Gemini 2.0 Flash for profile extraction (multimodal) |

### Image Processing

| Component | Recommendation |
|-----------|---------------|
| **Manipulation** | Pillow (PIL) + Pillow-SIMD for speed |
| **Advanced ops** | OpenCV for palette analysis, text region detection |
| **Text detection** | EasyOCR or paddleocr (for KV quality gate) |
| **Color analysis** | scikit-image or colorthief for palette compliance |

### Storage & Caching

| Component | Recommendation |
|-----------|---------------|
| **Asset storage (v0)** | Local filesystem (as per spec) |
| **Asset storage (scale)** | Object storage (S3/GCS) + CDN for serving |
| **Caching** | File-based hash caching (v0), Redis (scale) |
| **Metadata** | SQLite (v0) -> Postgres (scale) for indexing, auth, quotas, metrics |

---

## 2. Architecture Overview

### 2.1 Project Structure (Python Package)

```
performance_genai/
├── pyproject.toml
├── src/
│   └── performance_genai/
│       ├── api/              # FastAPI app + templates (v0 UI)
│       ├── cli/              # (Optional) Typer wrapper for batch/automation
│       ├── providers/        # Gemini/OpenAI providers, capability flags
│       ├── assembly/         # Deterministic renderer + (future) RenderSpec engine
│       ├── quality/          # (Future) palette checks, text detection gates
│       ├── storage.py        # File-based store + run manifests (v0)
│       └── config.py         # Settings/env
└── tests/
```

### 2.2 Key Design Principles

1. **AI proposes. User confirms. System enforces.** (Spec Section 3)
   - LLM analyzes references and proposes an Observed Profile
   - User reviews/edits/toggles strictness; saves Enforced Profile v1
   - Profile v1 is now the control plane for KV and copy generation

2. **Separate KV generation from typography/layout.** (Spec Section 3)
   - AI generates text-free KVs
   - Final ad text/logo/CTA are rendered deterministically via templates

3. **Determinism in masters.** (Spec Section 3)
   - Given the same KV, text selection, template, and profile version, the output is reproducible

4. **Provider-agnostic architecture.** (Spec Section 5)
   - Image generation/editing sits behind an interface to support Gemini/Nano Banana (default), OpenAI image models, and others later

5. **Layered composition for designer control.**
   - Treat each creative as a set of layers (background, subject cutout, motif, logo, text).
   - Generate multi-ratio previews deterministically from the same layer stack.
   - Use AI only where it is uniquely good (background generation / optional outpaint), not for typography.

---

## 3. Provider Interface Design

The spec requires **provider-agnostic architecture** (Section 5, 14). This means your core logic shouldn't care whether it's calling Gemini, OpenAI, or something else.

### 3.1 The Problem

Different providers have different APIs:
- **Gemini**: Uses `google.genai`, supports multimodal (image+text) natively
- **OpenAI**: Uses `openai` SDK, DALL-E for images, GPT-4o for vision
- **Future**: Maybe Replicate, Stability AI, etc.

You don't want `if gemini: ... elif openai: ...` scattered through your code.

### 3.2 The Solution: Abstract Base Classes

Define two interfaces:
- Image provider: `generate(...)` (Mode B) and `edit(...)` (Mode A), plus a capability surface (max refs, mask semantics, region protection semantics).
- LLM provider: propose observed profile (with confidence/evidence), generate copy pool, generate style directions.

Keep the core orchestration code provider-agnostic by:
- avoiding provider-specific branching outside provider wrappers
- using capability flags to choose between layered strategies (mask vs prompt vs post-check)

For concrete interface shapes and example implementations, see `docs/sample_quickstart_code.md` (Provider Interfaces, Gemini Provider, and KV Generation).

### 3.6 Gemini (Nano Banana) Optimizations and Capability Flags (Spec 7.5)

The spec adds explicit optimizations for the default Gemini provider. To make this robust and portable across providers:

- Split reference inputs conceptually:
  - `subject_images[]` (product fidelity, Mode A edits)
  - `style_images[]` (anchor refs for lighting/mood/style)
  If you keep a single `reference_images[]` parameter, you will still need an internal convention for what goes in that list and in what order.
- Track provider capabilities in one place (avoid "if provider == ..."):
  - max number of reference images supported
  - supports "region protection" semantics vs "best-effort" prompt guidance only
  - supports masks and how masks are interpreted
- Implement negative space protection as a layered strategy:
  1) structural prompt ("keep region calm / low contrast")
  2) mask usage if semantics actually protect a region
  3) post-check (safe-area clutter metric) + regenerate or flag

---

## 4. Template Engine

The spec's **Master Creation** (Section 10) requires generating **10–15 deterministic variants** for each KV+copy pairing. This means:

> Same inputs (KV, headline, template) → Same output every time

### 4.1 The Problem

You need to place text on images with:
- Different positions (headline top vs bottom)
- Different CTA styles
- Scrims/gradients for readability
- Safe area awareness
- Multiple aspect ratios (1:1, 4:5, 9:16)

Hard-coding this with Pillow coordinates gets messy fast.

### 4.2 Assembly Engine Interface + Canonical Render Spec (Spec 14.3)

The spec's updated Assembly Engine section is a good call. It lets you start with a Pillow backend and later swap to HTML->Image, ImageMagick, or a hosted renderer without rewriting business logic.

Recommendation: add an internal interface like:
- `AssemblyEngine.render(render_spec: RenderSpec, assets: dict) -> RenderResult`

Where `RenderSpec` is a canonical, normalized (0-1) layout/layer model that includes:
- canvas size + ratio
- layers (image, text, shapes), z-order, blending
- typography (font file IDs, sizes, weights), alignment
- scrim rules (deterministic) and the measured contrast inputs used to trigger them

Then:
- templates compile to `RenderSpec`
- the Pillow compositor is one AssemblyEngine implementation
- VaaJ (Spec 10.6) can run against the rendered master + render spec to suggest deterministic edits

### 4.3 The Solution: Declarative Templates + Compositor

Keep templates declarative and portable:
- JSON templates define text boxes, safe areas/reserved zones, scrim options, and a small set of deterministic variants.
- Templates compile into the canonical RenderSpec consumed by the Assembly Engine (Spec 14.3).

For sample template schemas and example JSON, see `docs/sample_quickstart_code.md` (Templates).

### 4.4 The Compositor (Builds Masters)
The compositor should be a thin backend over the Assembly Engine:
- take KV + selected copy + compiled template variant (RenderSpec)
- apply deterministic scrim rules when contrast is low (or when VaaJ recommends)
- render into one master image + metadata

For illustrative compositor code, see `docs/sample_quickstart_code.md` (Pillow Compositor).

### 4.5 Master Builder (Orchestrates 10-15 Variants)
The master builder is a small orchestrator:
- iterate template variants (10-15) for each KV+copy pairing
- render each master deterministically via the Assembly Engine
- write the master artifact + manifest (Spec 10.5) + run registry linkage (Spec 12.3)

For a sample master builder and manifest shape, see `docs/sample_quickstart_code.md` (Master Builder + Manifest).

---

## 5. Implementation Phases

### Phase 0: v0 Prototype (Already Built In This Repo)

- FastAPI app + server-rendered web UI for projects and generation workflows
- File-based project storage and run manifests (traceability)
- Gemini provider:
  - observed profile extraction from refs (vision)
  - KV generation (text-free visuals)
  - AI reframe/outpaint into target aspect ratios (ratio-specific visuals)
- OpenAI provider: headline generation (v0)
- Deterministic renderer (Pillow) for simple text/CTA overlays (useful, but likely not the long-term UX)

### Phase 1: Stabilize The Visual Workflow (Immediate Internal Need)

- Make the core flow fast and obvious:
  - Visual pool generation (n <= 5)
  - shortlist selection
  - batch "generate ratios" for shortlisted visuals
- Reduce reframe drift where possible:
  - stricter reframe constraints, locked-canvas outpaint bias
  - optional motif enforcement (avoid motif invention)
  - better prompts: "extend margins only" / "preserve subject"
- Add basic safety and ops:
  - upload validation (size/dimensions/type)
  - internal-only security posture (reverse proxy auth, IP allowlist/VPN)
  - usage monitoring from run manifests (counts, latency, approximate cost)

### Phase 2: Layer Model + Designer Controls (Needed For Agency Rollout)

- Introduce a canonical `RenderSpec` / layer model per creative:
  - background image
  - subject/product cutout (transparent PNG) + mask
  - motif layer(s)
  - logo layer
  - text layers (headline, body, CTA)
- Add subject isolation as a first-class operation (segmentation -> cutout):
  - required for correct motif placement "behind subject"
- Build a lightweight editor UI:
  - Next.js + TypeScript + a canvas library (Konva/Fabric)
  - live multi-ratio preview (1:1, 4:5, 9:16) while editing
- Keep rendering deterministic:
  - backend renders final exports from `RenderSpec`
  - AI outpaint becomes optional only when background extension is needed for a ratio

### Phase 3: Scale To Agency / SaaS (Control Plane + Infra)

- Separate concerns:
  - Python service = "creative engine" (generation, rendering, quality gates)
  - Control plane (potentially your existing Laravel app) = auth/sessions, quotas, billing, org/team model
- Add production primitives:
  - Postgres for metadata + audit logs
  - object storage for assets + signed URLs
  - background jobs (Celery/RQ) + concurrency limits
  - metrics + tracing + error reporting
  - template/font registry and versioning (agency consistency)

---

## 6. Key Technical Decisions

| Decision | Recommendation |
|----------|----------------|
| **Async vs Sync** | Use `asyncio` throughout — you're calling external APIs heavily |
| **Image generation strategy** | For Mode A (product fidelity), use Gemini's inpainting/editing. For Mode B (style variations), use Imagen 3 with reference images |
| **KV quality gates** | Start with simple heuristics (Pillow histogram for palette, EasyOCR for text detection) — don't over-engineer v1 |
| **Template format** | JSON with normalized coordinates (0-1) so templates are ratio-agnostic |
| **Copy deduplication** | Use sentence-transformers for semantic similarity, or simple LLM-based dedup |

---

## 7. Potential Pitfalls & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Provider rate limits / costs** | Implement aggressive caching (hash of prompt+params → result). Retry with exponential backoff. |
| **Inconsistent KV quality** | The "Style Exploration" step is crucial — get user direction before burning tokens on 100 KVs |
| **Text in KVs** | Hard constraint in prompts + OCR check post-generation + human review in GUI |
| **Color accuracy** | Don't rely solely on prompts; post-process with palette mapping if needed |

---

## 8. Summary

**Go with Python + FastAPI + Pydantic (creative engine).** Start with the existing server-rendered UI for v0/internal delivery, then add a real editor UI (Next.js + TypeScript + canvas) for agency-scale designer controls. A Typer CLI wrapper can come later for batch automation.

| Component | Purpose |
|-----------|---------|
| **Provider Interface** | Lets you swap Gemini ↔ OpenAI without changing business logic. Abstracts image gen, editing, and LLM tasks. |
| **RenderSpec + Assembly Engine** | Canonical layer/layout model that enables deterministic multi-ratio previews and exports, and a future interactive editor UI. |
| **Control Plane (optional)** | Auth/sessions, quotas, budgets, billing, org/team model (can live in your existing Laravel app and call the Python engine). |

These boundaries keep v0 fast while preserving a clean path to agency-scale rollout and monetization.

---

## Appendix: Security + Scale Checklist (Before Wider Rollout)

### Security

- **API key handling**: keep keys in env/secrets manager; avoid persisting raw provider responses in artifacts/manifests.
- **File upload safety**: validate file type, size, and dimensions; sanitize names; store outside any public web root.
- **Auth**: for internal v0, run behind VPN/IP allowlist and reverse proxy auth; for agency scale, integrate SSO via the control plane.
- **Prompt injection**: treat briefs and templates as untrusted input; restrict who can edit templates; escape/validate free-text inputs.
- **Output safety**: optional moderation hook + audit log (who generated what, when, with which inputs).

### Scalability / Reliability

- **File-based storage limits**: no indexing and weaker concurrency guarantees; plan a migration path to Postgres + object storage.
- **Long-running jobs**: add a worker queue (Celery/RQ) before expanding usage or adding large batch runs.
- **Rate limiting + cost controls**: implement budgets, circuit breakers, and backoff/retry policies to avoid runaway spend.
- **Observability**: keep run manifests, but also add metrics/tracing/error reporting for production use.

### Single Source Of Truth

- Keep profiles/versioning, render specs, and references immutable once used for a run.
- Prefer content-addressed assets (sha-based) once you move beyond v0 prototypes.
