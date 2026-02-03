from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

from performance_genai.assembly.render import render_master_simple
from performance_genai.config import settings
from performance_genai.providers.gemini_provider import GeminiProvider
from performance_genai.providers.openai_provider import OpenAITextProvider
from performance_genai.storage import ProjectStore


app = FastAPI(title="performance_genai prototype")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

store = ProjectStore()


def _get_gemini() -> GeminiProvider:
    if not settings.gemini_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY is not set")
    return GeminiProvider(api_key=settings.gemini_api_key)


def _get_openai_text() -> OpenAITextProvider:
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not set")
    return OpenAITextProvider(api_key=settings.openai_api_key)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    projects = store.list_projects()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"projects": projects},
    )


@app.post("/projects")
def create_project(name: str = Form(...)):
    proj = store.create_project(name=name)
    return RedirectResponse(url=f"/projects/{proj.project_id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: str):
    proj = store.read_project(project_id)
    assets = list(reversed(proj.assets))
    kvs = [a for a in assets if a.kind == "kv"]
    masters = [a for a in assets if a.kind == "master"]
    motifs = [a for a in assets if a.kind == "motif"]

    observed_profile_pretty = None
    if proj.observed_profile is not None:
        try:
            # If we stored an envelope, prefer showing the structured profile.
            if isinstance(proj.observed_profile, dict) and "profile" in proj.observed_profile:
                observed_profile_pretty = json.dumps(proj.observed_profile, indent=2)
            else:
                observed_profile_pretty = json.dumps(proj.observed_profile, indent=2)
        except Exception:
            observed_profile_pretty = str(proj.observed_profile)

    headlines: list[str] = []
    try:
        proj_dir = Path(settings.data_dir) / "projects" / project_id
        hl_path = proj_dir / "copy_headlines.json"
        if hl_path.exists():
            headlines = json.loads(hl_path.read_text("utf-8")).get("headlines", []) or []
    except Exception:
        headlines = []

    return templates.TemplateResponse(
        request=request,
        name="project.html",
        context={
            "project": proj,
            "assets": assets,
            "kvs": kvs,
            "masters": masters,
            "motifs": motifs,
            "observed_profile": proj.observed_profile,
            "observed_profile_pretty": observed_profile_pretty,
            "headlines": headlines,
        },
    )


@app.post("/projects/{project_id}/assets/upload")
async def upload_asset(
    project_id: str,
    kind: str = Form("reference"),
    file: UploadFile = File(...),
):
    content = await file.read()
    subdir = "assets"
    if kind == "motif":
        subdir = "motifs"
    store.add_asset(
        project_id=project_id,
        kind=kind,
        filename=file.filename or "upload.bin",
        content=content,
        metadata={"content_type": file.content_type},
        subdir=subdir,
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.get("/projects/{project_id}/assets/{asset_id}")
def get_asset(project_id: str, asset_id: str):
    proj = store.read_project(project_id)
    match = next((a for a in proj.assets if a.asset_id == asset_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="asset not found")
    path = store.abs_asset_path(project_id, match)
    if not path.exists():
        raise HTTPException(status_code=404, detail="asset file missing")
    return FileResponse(path)


@app.post("/projects/{project_id}/profile/propose")
async def propose_profile(
    project_id: str,
    brief_text: str = Form(""),
):
    proj = store.read_project(project_id)
    ref_paths: list[Path] = []
    for a in proj.assets:
        if a.kind in ("reference", "product", "kv"):
            ref_paths.append(store.abs_asset_path(project_id, a))
    if not ref_paths:
        raise HTTPException(status_code=400, detail="upload at least one reference image first")

    gemini = _get_gemini()
    res = await gemini.propose_observed_profile(reference_images=ref_paths[:8], brief_text=brief_text)
    store.write_observed_profile(project_id, res.profile)
    store.write_run_manifest(
        project_id,
        {
            "type": "profile_propose",
            "provider": res.provider,
            "model": res.model,
            "inputs": {"n_images": len(ref_paths[:8])},
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/kvs/generate")
async def generate_kvs(
    project_id: str,
    prompt: str = Form(...),
    n: int = Form(2),
    aspect_ratio: str = Form("1:1"),
    use_images: bool = Form(True),
):
    proj = store.read_project(project_id)
    ref_paths: list[Path] = []
    if use_images:
        ref_paths = [store.abs_asset_path(project_id, a) for a in proj.assets if a.kind in ("reference", "product")]

    gemini = _get_gemini()
    images = await gemini.generate(prompt=prompt, reference_images=ref_paths[:8], n=int(n), aspect_ratio=aspect_ratio)

    kv_asset_ids: list[str] = []
    for idx, gi in enumerate(images):
        buf = _pil_to_png_bytes(gi.image)
        asset = store.add_asset(
            project_id=project_id,
            kind="kv",
            filename=f"kv_{idx}.png",
            content=buf,
            metadata={"provider": gi.provider, "model": gi.model, "prompt": gi.prompt_used},
            subdir="kvs",
        )
        kv_asset_ids.append(asset.asset_id)

    store.write_run_manifest(
        project_id,
        {
            "type": "kv_generate",
            "provider": gemini.name,
            "model": settings.gemini_image_model,
            "inputs": {"prompt": prompt, "n_requested": int(n), "aspect_ratio": aspect_ratio, "use_images": bool(use_images)},
            "outputs": {"kv_asset_ids": kv_asset_ids},
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/copy/headlines")
async def generate_headlines(
    project_id: str,
    brief_text: str = Form(...),
    count: int = Form(10),
    use_images: bool = Form(False),
):
    proj = store.read_project(project_id)
    ref_paths = [store.abs_asset_path(project_id, a) for a in proj.assets if a.kind in ("reference", "product", "kv")]

    # Optionally enrich the brief with brand-language cues extracted from images.
    context_text = ""
    if use_images and ref_paths:
        gemini = _get_gemini()
        context_text = await gemini.summarize_brand_language_for_copy(reference_images=ref_paths[:8], brief_text=brief_text)

    full_brief = brief_text
    if context_text.strip():
        full_brief = (
            f"{brief_text}\n\n"
            "Brand-language cues extracted from reference images:\n"
            f"{context_text.strip()}\n"
        )

    openai = _get_openai_text()
    lines = await openai.generate_copy(brief_text=full_brief, count=int(count))

    store.write_run_manifest(
        project_id,
        {
            "type": "copy_headlines",
            "provider": openai.name,
            "model": settings.openai_text_model,
            "inputs": {"count": int(count), "use_images": bool(use_images)},
            "outputs": {"headlines": lines},
        },
    )

    # Persist as a plain json file in the project for easy UI access in v0.
    proj_dir = Path(settings.data_dir) / "projects" / project_id
    (proj_dir / "copy_headlines.json").write_text(json.dumps({"headlines": lines}, indent=2), "utf-8")
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/masters/build")
async def build_masters(
    project_id: str,
    kv_asset_id: str = Form(...),
    headline: str = Form(...),
    cta: str = Form("Learn more"),
    motif_asset_id: str = Form(""),
    motif_opacity: float = Form(0.14),
    motif_tint_hex: str = Form("#266156"),
    protect_preset: str = Form("right"),
):
    proj = store.read_project(project_id)
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="kv_asset_id must be an existing KV asset")

    kv_path = store.abs_asset_path(project_id, kv_asset)
    kv_img = Image.open(kv_path)

    motif_img = None
    if motif_asset_id:
        motif_asset = next((a for a in proj.assets if a.asset_id == motif_asset_id and a.kind == "motif"), None)
        if motif_asset:
            motif_path = store.abs_asset_path(project_id, motif_asset)
            try:
                motif_img = Image.open(motif_path)
            except Exception:
                motif_img = None

    master_ids: list[str] = []
    for ratio, size in settings.master_sizes.items():
        rendered = render_master_simple(
            kv=kv_img,
            size=size,
            headline=headline,
            cta=cta,
            motif=motif_img,
            motif_opacity=float(motif_opacity),
            motif_tint_hex=motif_tint_hex,
            protect_preset=protect_preset,
        )
        out_bytes = _pil_to_png_bytes(rendered.image)
        asset = store.add_asset(
            project_id=project_id,
            kind="master",
            filename=f"master_{ratio.replace(':','x')}.png",
            content=out_bytes,
            metadata={
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "headline": headline,
                "cta": cta,
                "motif_asset_id": motif_asset_id or None,
                "motif_opacity": float(motif_opacity),
                "motif_tint_hex": motif_tint_hex,
                "protect_preset": protect_preset,
            },
            subdir="masters",
        )
        master_ids.append(asset.asset_id)

    store.write_run_manifest(
        project_id,
        {
            "type": "masters_build",
            "provider": "pillow",
            "model": "render_master_simple",
            "inputs": {"kv_asset_id": kv_asset_id, "headline": headline, "cta": cta},
            "outputs": {"master_asset_ids": master_ids},
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


def _pil_to_png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
