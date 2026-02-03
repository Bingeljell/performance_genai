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

This is the difference between "CLI-first" and "reliably re-runnable".

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
- A "server mode" or run coordinator eventually (even if v1 is CLI-first) so you can queue, resume, and observe runs centrally

## 1. Tech Stack Recommendations

### Core Framework

| Component | Recommendation | Rationale |
|-----------|---------------|-----------|
| **Language** | **Python 3.11+** | Best ecosystem for AI/ML, image processing, and CLI tools |
| **CLI Framework** | **Typer** | Modern, type-hinted, generates great help text, async support |
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

### GUI (Internal Tool)

| Component | Recommendation |
|-----------|---------------|
| **Framework** | **Streamlit** or **Gradio** | Spec says "basic internal GUI, not complicated" — these are fastest |
| **Alternative** | FastAPI + simple React if you need more control |

### Storage & Caching

| Component | Recommendation |
|-----------|---------------|
| **Asset storage** | Local filesystem (as per spec) |
| **Caching** | diskcache or simple file-based hash caching |
| **Metadata** | SQLite (optional) for indexing projects if you grow beyond file-based |

---

## 2. Architecture Overview

### 2.1 Project Structure (Python Package)

```
performance_genai/
├── pyproject.toml
├── src/
│   └── performance_genai/
│       ├── cli/              # Typer commands (ads init, ads kv generate, etc.)
│       ├── core/             # Project, Profile, KV, Copy, Master models (Pydantic)
│       ├── providers/        # ImageProvider, LLMProvider abstractions
│       ├── generation/       # KV generator, Copy generator
│       ├── assembly/         # Master builder, template engine
│       ├── quality/          # Palette checks, text detection gates
│       └── gui/              # Streamlit app
├── templates/            # Layout templates (JSON)
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

### Phase 1: Foundation (Week 1-2)
- Project structure, CLI skeleton (`ads init`, `ads ingest`)
- Pydantic models for Profile, Project, KV, Copy, Master
- Provider abstraction with Gemini implementation
- Basic file-based project storage
- Run manifests + input hashing + optional `--job-id` plumbing (Spec 12.3)
- `ads schema` JSON schema emission for core artifacts (Spec 12.3)

### Phase 2: Profile & KV (Week 3-4)
- `ads profile propose` — multimodal LLM analysis of reference images
- Profile review/edit flow
- `ads kv explore` — style exploration (6-12 variants)
- `ads kv generate` — full pool generation
- Basic palette compliance checks
- Implement Spec 7.5 "Nano Banana optimization" in the Gemini provider wrapper (multi-ref product fidelity, negative space protection layering, style anchoring)

### Phase 3: Copy & Assembly (Week 5-6)
- `ads copy generate` — headlines, primary, CTAs
- Assembly Engine interface + Pillow implementation (Spec 14.3)
- Template system compiles to canonical RenderSpec (not just ad-hoc Pillow calls)
- `ads masters build` — deterministic assembly
- Export to 1:1, 4:5, 9:16
- Add VaaJ pass/fail flagging and deterministic regeneration rules (Spec 10.6)

### Phase 4: GUI (Week 7-8)
- Streamlit wrapper around CLI commands
- Grid browsing for KVs
- Profile editor with visual feedback
- Master preview & shortlist

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

**Go with Python + Typer + Pydantic + Streamlit.** The spec is well-designed for a file-based, CLI-first architecture with clear data models. The provider abstraction lets you start with Gemini (good multimodal support for profile extraction) and add OpenAI later.

| Component | Purpose |
|-----------|---------|
| **Provider Interface** | Lets you swap Gemini ↔ OpenAI without changing business logic. Abstracts image gen, editing, and LLM tasks. |
| **Template Engine** | Turns KV+copy into 10-15 variants deterministically. JSON templates define text placement, scrims, safe areas. Compositor renders final images with Pillow. |

Both are critical for the spec's goals of **provider-agnostic** and **deterministic master generation**.
Both are critical for the spec's goals of **provider-agnostic** and **deterministic master generation**.

---

## Updated thoughts - 3rdFeb - Agennt: Kimi

### Security Gaps Not Addressed

**1. API Key Handling**
- Mentioned `settings.GEMINI_API_KEY` but no secure storage patterns specified
- No key rotation, encryption at rest, or environment separation (dev/prod)
- The `raw_metadata` field in `GeneratedImage` could leak sensitive provider responses

**2. File System Security**
- Path traversal risks: User uploads could contain `../../../etc/passwd` style paths
- No validation on file sizes, image dimensions, or malicious uploads (polyglot images)
- Suggested local file storage without permission controls or access logging

**3. Prompt Injection**
- `brand_brief` data flows directly into LLM prompts without sanitization
- No input validation on free-text fields (product names, objectives)
- Template files (JSON) could be tampered with to inject malicious instructions

**4. Streamlit for Internal GUI**
- Streamlit's default configuration has no authentication
- "Internal use" assumptions can lead to exposed instances
- No mention of session management or audit logging

**5. Output Safety**
- No content moderation hooks before saving generated KVs
- Master manifests contain file paths that could expose directory structure

### Scalability Issues

**1. File-Based Architecture**
- Spec requires CLI-first with file storage, but this has hard limits:
  - No concurrent write safety (multiple CLI processes → corrupted manifests)
  - No indexing → linear scans for finding projects/KVs as volume grows
  - File system limitations on number of files per directory

**2. Synchronous Processing**
- PIL operations are CPU-bound and blocking
- Generating "10-15 Masters per KV+copy pairing" × multiple KVs × multiple copies = potentially hundreds of images processed sequentially
- No task queue or worker pool architecture suggested

**3. Caching Strategy**
- Suggested "file-based hash caching" but:
  - Hash collisions possible with large image sets
  - No eviction strategy → disk bloat
  - Not shareable across multiple machines

**4. Rate Limiting & Costs**
- No circuit breakers for provider failures
- Retry logic could amplify costs during outages
- No cost tracking or budget controls per project

### Remaining Duplicates / Sources of Truth Concerns

**1. Profile Data Duplication**
- `ObservedProfile` → `EnforcedProfile` versioning could lead to drift
- Same style constraints exist in: Profile JSON, prompt templates, and KV metadata
- If user updates Enforced Profile v1, existing KVs don't reflect the change

**2. Template Logic Duplication**
- Each template variant repeats ratio-specific dimensions
- Platform specs (Meta safe areas, Google specs) duplicated in every template file
- No central registry of "valid" template combinations

**3. Validation Logic Duplication**
- Palette compliance checks needed in: KV generation, quality gates, and master assembly
- Text detection needed for KV gate AND potentially for master verification
- Color adaptation ("auto" color) logic in compositor mirrors palette analysis logic

**4. Reference Image Handling**
- Reference images referenced by: Profile (anchor_refs), KV generation (reference_images), and Edit operations
- No single source of truth for which images were actually used to generate a KV

### Tensions with Spec

**1. "Deterministic Masters" vs "Provider Agnostic"**
- Spec says deterministic output given same inputs
- But different providers (Gemini vs OpenAI) produce different KV images → different masters
- The abstraction doesn't account for this non-determinism

**2. "Scale through templating" vs File Storage**
- Spec Section 3: "Scale through templating, not more prompting"
- But file-based storage doesn't scale with template variants (imagine 1000 projects × 15 variants × 3 ratios)

**3. "Text-free KVs" vs Mode A**
- Spec Section 7.2: Mode A is "background replace... keep product intact"
- But Gemini's `edit()` might introduce text artifacts during contextualization
- The interface doesn't enforce the "no text in KVs" constraint at the type level

### What Should Be Added

1. **Security**: Input sanitization layer, signed URLs for assets, audit logging, API key management via secrets manager integration
2. **Scalability**: SQLite/PostgreSQL for metadata with file storage for blobs, background job queue (Celery/RQ), streaming responses for long operations
3. **Single Source of Truth**: Content-addressed storage (hash-based filenames), immutable profiles (enforced profiles are snapshots, not mutable), centralized validation rules

The spec is well-designed for a single-user, single-machine workflow. The implementation suggestions follow that scope but don't flag where architectural decisions would break if the tool needs to grow beyond that.
