# Changelog

- **2026-02-03 > AGENTS.md > n/a > add agent workflow instructions**
- **2026-02-03 > src/performance_genai/api/templates/project.html > n/a > restructure project UI and add previews for uploaded assets, KVs, masters, and headlines**
- **2026-02-03 > src/performance_genai/api/templates/index.html > n/a > refresh landing page layout and styling**
- **2026-02-03 > src/performance_genai/storage.py > delete_project, delete_asset > add reversible delete operations for projects and assets in file-based store**
- **2026-02-03 > src/performance_genai/api/app.py > delete_project, delete_asset, build_masters > add delete endpoints and improve selection UX (KV/headline selection)**
- **2026-02-03 > src/performance_genai/assembly/render.py > render_master_simple and helpers > improve deterministic master rendering (cover-crop, scrim, legible text sizing, CTA button)**
- **2026-02-03 > src/performance_genai/assembly/render.py > _apply_motif_overlay, _contain, _tint_preserving_alpha > place motif as a side-positioned design element and protect subject region separately**
- **2026-02-03 > src/performance_genai/api/templates/project.html > n/a > add separate motif-position and subject-position controls for motif overlays**
- **2026-02-03 > src/performance_genai/api/app.py > build_masters > pass motif-position and subject-position to renderer for correct motif placement**
- **2026-02-03 > src/performance_genai/providers/gemini_provider.py > generate, propose_observed_profile > fix google-genai API usage, parse fenced JSON, and loop to return N images on preview models**
- **2026-02-03 > src/performance_genai/providers/gemini_provider.py > reframe_kv_with_motif > add AI reframe/outpaint flow for ratio-specific text-free visuals with optional motif integration**
- **2026-02-03 > src/performance_genai/api/app.py > reframe_kv > add endpoint to AI-reframe an existing KV into a target aspect ratio (text-free)**
- **2026-02-03 > src/performance_genai/api/templates/project.html > n/a > add AI reframe form to generate ratio-specific text-free visuals**
- **2026-02-03 > src/performance_genai/api/app.py > reframe_kv > add strict constraints to reduce drift; prevent motif invention when no motif is provided**
- **2026-02-03 > src/performance_genai/providers/gemini_provider.py > reframe_kv_with_motif, _make_outpaint_canvas > bias AI reframe toward true outpainting by providing a larger locked canvas input**
- **2026-02-03 > src/performance_genai/api/templates/project.html > n/a > add open link for KV thumbnails**
- **2026-02-03 > src/performance_genai/api/app.py > bulk_delete_assets > add bulk-delete endpoint for deleting multiple assets at once**
- **2026-02-03 > src/performance_genai/api/templates/project.html > n/a > add KV/master multi-select checkboxes and bulk delete buttons**
