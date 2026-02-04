from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

from performance_genai.assembly.render import render_master_simple, render_text_layout, render_text_layers
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


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _parse_box_from_form(
    x: str | None,
    y: str | None,
    w: str | None,
    h: str | None,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        _parse_float(x, default[0]),
        _parse_float(y, default[1]),
        _parse_float(w, default[2]),
        _parse_float(h, default[3]),
    )


def _safe_return_path(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.startswith("/projects/") and ".." not in cleaned:
        return cleaned
    return None


def _build_reframe_constraints(has_motif: bool) -> str:
    constraints = (
        "OUTPUT MUST CONTAIN NO TEXT, NO LOGOS, NO WATERMARKS.\n"
        "Preserve the base image exactly; only outpaint/extend into new canvas area to reach the target aspect ratio.\n"
        "Do not change the subject identity, clothing, face, pose, or scene lighting.\n"
    )
    if not has_motif:
        constraints += "Do not add any motif/brand outline/overlay elements.\n"
    else:
        constraints += (
            "Use the provided motif image exactly as reference; keep its shape consistent.\n"
            "Place it on the right side behind the subject (subject occludes motif). Do not cover faces/hands.\n"
        )
    return constraints


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    projects = store.list_projects()
    grouped: dict[str, dict[str, list[Any]]] = {}
    for p in projects:
        brand = (p.brand_name or "").strip() or "Unassigned"
        campaign = (p.campaign_name or "").strip() or "Unassigned"
        grouped.setdefault(brand, {}).setdefault(campaign, []).append(p)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"projects": projects, "grouped": grouped},
    )


@app.post("/projects")
def create_project(name: str = Form(...), brand_name: str = Form(""), campaign_name: str = Form("")):
    proj = store.create_project(name=name, brand_name=brand_name, campaign_name=campaign_name)
    return RedirectResponse(url=f"/projects/{proj.project_id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: str):
    proj = store.read_project(project_id)
    assets = list(reversed(proj.assets))
    kvs = [a for a in assets if a.kind == "kv"]
    base_kvs = [a for a in kvs if not (a.metadata or {}).get("source_kv_asset_id")]
    ratio_kvs = [a for a in kvs if (a.metadata or {}).get("source_kv_asset_id")]
    shortlisted_kvs = [a for a in base_kvs if (a.metadata or {}).get("shortlisted")]
    text_previews = [a for a in assets if a.kind == "text_preview"]
    masters = [a for a in assets if a.kind == "master"]
    motifs = [a for a in assets if a.kind == "motif"]
    selected_kv = request.query_params.get("kv") or ""
    selected_headline = request.query_params.get("headline") or ""

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
            "base_kvs": base_kvs,
            "ratio_kvs": ratio_kvs,
            "shortlisted_kvs": shortlisted_kvs,
            "text_previews": text_previews,
            "masters": masters,
            "motifs": motifs,
            "observed_profile": proj.observed_profile,
            "observed_profile_pretty": observed_profile_pretty,
            "headlines": headlines,
            "selected_kv": selected_kv,
            "selected_headline": selected_headline,
        },
    )


@app.get("/projects/{project_id}/editor", response_class=HTMLResponse)
def editor_page(request: Request, project_id: str):
    proj = store.read_project(project_id)
    assets = list(reversed(proj.assets))
    kvs = [a for a in assets if a.kind == "kv"]
    base_kvs = [a for a in kvs if not (a.metadata or {}).get("source_kv_asset_id")]
    kv_choices = [
        {
            "id": a.asset_id,
            "label": (a.metadata or {}).get("display_name") or a.filename,
            "url": f"/projects/{project_id}/assets/{a.asset_id}",
        }
        for a in base_kvs
    ]
    selected_kv = request.query_params.get("kv") or ""

    copy_sets: list[dict[str, str]] = []
    try:
        proj_dir = Path(settings.data_dir) / "projects" / project_id
        cs_path = proj_dir / "copy_sets.json"
        if cs_path.exists():
            copy_sets = json.loads(cs_path.read_text("utf-8")).get("sets", []) or []
    except Exception:
        copy_sets = []

    text_previews = [a for a in assets if a.kind == "text_preview"]
    return templates.TemplateResponse(
        request=request,
        name="editor.html",
        context={
            "project": proj,
            "kv_choices_json": json.dumps(kv_choices),
            "kv_choices": kv_choices,
            "selected_kv": selected_kv,
            "copy_sets": copy_sets,
            "text_previews": text_previews,
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

@app.post("/projects/{project_id}/delete")
def delete_project(project_id: str):
    store.delete_project(project_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/projects/{project_id}/assets/{asset_id}/delete")
def delete_asset(project_id: str, asset_id: str, return_to: str = Form("")):
    store.delete_asset(project_id, asset_id)
    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


@app.post("/projects/{project_id}/kvs/{asset_id}/shortlist")
def shortlist_kv(project_id: str, asset_id: str, shortlisted: str = Form("1")):
    value = _parse_bool(shortlisted)
    store.update_asset_metadata(project_id, asset_id, {"shortlisted": value})
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/assets/bulk_delete")
def bulk_delete_assets(project_id: str, asset_ids: list[str] = Form(default=[])):
    # v0: best-effort bulk delete for faster iteration.
    for asset_id in asset_ids:
        try:
            store.delete_asset(project_id, asset_id)
        except Exception:
            continue
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
    existing_base = [a for a in proj.assets if a.kind == "kv" and not (a.metadata or {}).get("source_kv_asset_id")]
    base_start = len(existing_base)
    for idx, gi in enumerate(images):
        label = f"kv_option_{base_start + idx + 1}"
        buf = _pil_to_png_bytes(gi.image)
        asset = store.add_asset(
            project_id=project_id,
            kind="kv",
            filename=f"{label}.png",
            content=buf,
            metadata={
                "provider": gi.provider,
                "model": gi.model,
                "prompt": gi.prompt_used,
                "display_name": label,
            },
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

@app.post("/projects/{project_id}/kvs/reframe")
async def reframe_kv(
    project_id: str,
    kv_asset_id: str = Form(...),
    motif_asset_id: str = Form(""),
    aspect_ratio: str = Form("9:16"),
    image_size: str = Form("2K"),
    n: int = Form(1),
    prompt: str = Form("Reframe this KV to the target aspect ratio and integrate the motif as a background brand element."),
):
    proj = store.read_project(project_id)
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="kv_asset_id must be an existing KV asset")

    motif_path: Path | None = None
    if motif_asset_id:
        motif_asset = next((a for a in proj.assets if a.asset_id == motif_asset_id and a.kind == "motif"), None)
        if motif_asset:
            motif_path = store.abs_asset_path(project_id, motif_asset)

    kv_path = store.abs_asset_path(project_id, kv_asset)
    gemini = _get_gemini()

    # Add strong constraints to reduce drift. If motif isn't provided, explicitly
    # instruct the model not to invent one.
    sys_constraints = _build_reframe_constraints(motif_path is not None)

    images = await gemini.reframe_kv_with_motif(
        kv_image=kv_path,
        motif_image=motif_path,
        prompt=f"{prompt}\n\n{sys_constraints}",
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        n=int(n),
    )

    kv_asset_ids: list[str] = []
    for idx, gi in enumerate(images):
        source_label = (kv_asset.metadata or {}).get("display_name") or kv_asset.filename
        display_label = f"{source_label}_{aspect_ratio}_{idx + 1}"
        buf = _pil_to_png_bytes(gi.image)
        asset = store.add_asset(
            project_id=project_id,
            kind="kv",
            filename=f"kv_reframe_{idx}.png",
            content=buf,
            metadata={
                "provider": gi.provider,
                "model": gi.model,
                "prompt": gi.prompt_used,
                "source_kv_asset_id": kv_asset_id,
                "motif_asset_id": motif_asset_id or None,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "display_name": display_label,
            },
            subdir="kvs",
        )
        kv_asset_ids.append(asset.asset_id)

    store.write_run_manifest(
        project_id,
        {
            "type": "kv_reframe",
            "provider": gemini.name,
            "model": settings.gemini_image_model,
            "inputs": {
                "kv_asset_id": kv_asset_id,
                "motif_asset_id": motif_asset_id or None,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "n_requested": int(n),
            },
            "outputs": {"kv_asset_ids": kv_asset_ids},
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/kvs/reframe_batch")
async def reframe_kv_batch(
    project_id: str,
    aspect_ratios: list[str] = Form(default=[]),
    image_size: str = Form("2K"),
    n_per_ratio: int = Form(1),
    prompt: str = Form("Return the SAME image, just expanded to the target aspect ratio by outpainting ONLY the new canvas areas."),
    motif_asset_id: str = Form(""),
):
    proj = store.read_project(project_id)
    kvs = [a for a in proj.assets if a.kind == "kv"]
    shortlisted = [a for a in kvs if (a.metadata or {}).get("shortlisted")]
    if not shortlisted:
        raise HTTPException(status_code=400, detail="shortlist at least one KV first")
    if not aspect_ratios:
        raise HTTPException(status_code=400, detail="select at least one target ratio")

    motif_path: Path | None = None
    if motif_asset_id:
        motif_asset = next((a for a in proj.assets if a.asset_id == motif_asset_id and a.kind == "motif"), None)
        if motif_asset:
            motif_path = store.abs_asset_path(project_id, motif_asset)

    gemini = _get_gemini()
    batch_id = uuid.uuid4().hex[:12]
    sys_constraints = _build_reframe_constraints(motif_path is not None)
    full_prompt = f"{prompt}\n\n{sys_constraints}"

    all_outputs: list[dict[str, Any]] = []
    all_kv_asset_ids: list[str] = []

    for kv in shortlisted:
        kv_path = store.abs_asset_path(project_id, kv)
        source_label = (kv.metadata or {}).get("display_name") or kv.filename
        for ratio in aspect_ratios:
            images = await gemini.reframe_kv_with_motif(
                kv_image=kv_path,
                motif_image=motif_path,
                prompt=full_prompt,
                aspect_ratio=ratio,
                image_size=image_size,
                n=int(n_per_ratio),
            )
            created_ids: list[str] = []
            for idx, gi in enumerate(images):
                buf = _pil_to_png_bytes(gi.image)
                safe_ratio = ratio.replace(":", "x")
                display_label = f"{source_label}_{ratio}_{idx + 1}"
                asset = store.add_asset(
                    project_id=project_id,
                    kind="kv",
                    filename=f"kv_reframe_{safe_ratio}_{idx}.png",
                    content=buf,
                    metadata={
                        "provider": gi.provider,
                        "model": gi.model,
                        "prompt": gi.prompt_used,
                        "source_kv_asset_id": kv.asset_id,
                        "motif_asset_id": motif_asset_id or None,
                        "aspect_ratio": ratio,
                        "image_size": image_size,
                        "batch_id": batch_id,
                        "display_name": display_label,
                    },
                    subdir="kvs",
                )
                created_ids.append(asset.asset_id)
                all_kv_asset_ids.append(asset.asset_id)
            all_outputs.append(
                {
                    "source_kv_asset_id": kv.asset_id,
                    "aspect_ratio": ratio,
                    "kv_asset_ids": created_ids,
                }
            )

    store.write_run_manifest(
        project_id,
        {
            "type": "kv_reframe_batch",
            "provider": gemini.name,
            "model": settings.gemini_image_model,
            "inputs": {
                "batch_id": batch_id,
                "kv_asset_ids": [k.asset_id for k in shortlisted],
                "motif_asset_id": motif_asset_id or None,
                "aspect_ratios": aspect_ratios,
                "image_size": image_size,
                "n_per_ratio": int(n_per_ratio),
            },
            "outputs": {"kv_asset_ids": all_kv_asset_ids, "groups": all_outputs},
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/layouts/preview")
async def preview_text_layout(
    project_id: str,
    kv_asset_id: str = Form(...),
    text_layers: str = Form(""),
    image_box: str = Form(""),
    headline: str = Form(""),
    subhead: str = Form(""),
    cta: str = Form("Learn more"),
    font_family: str = Form("dejavu"),
    text_color: str = Form("#ffffff"),
    text_align: str = Form("left"),
    font_scale: float = Form(1.0),
    headline_x: str = Form("0.06"),
    headline_y: str = Form("0.60"),
    headline_w: str = Form("0.88"),
    headline_h: str = Form("0.16"),
    subhead_x: str = Form("0.06"),
    subhead_y: str = Form("0.76"),
    subhead_w: str = Form("0.88"),
    subhead_h: str = Form("0.08"),
    cta_x: str = Form("0.06"),
    cta_y: str = Form("0.86"),
    cta_w: str = Form("0.50"),
    cta_h: str = Form("0.10"),
    return_to: str = Form(""),
):
    proj = store.read_project(project_id)
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="kv_asset_id must be an existing KV asset")

    kv_path = store.abs_asset_path(project_id, kv_asset)
    kv_img = Image.open(kv_path)

    layout_id = uuid.uuid4().hex[:12]
    use_layers = False
    layers_payload: list[dict] = []
    if text_layers.strip():
        try:
            parsed = json.loads(text_layers)
            if isinstance(parsed, list):
                use_layers = True
                layers_payload = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"text_layers must be JSON list: {exc}") from exc

    image_box_payload: dict | None = None
    if image_box.strip():
        try:
            parsed = json.loads(image_box)
            if isinstance(parsed, dict):
                image_box_payload = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"image_box must be JSON object: {exc}") from exc

    headline_box = _parse_box_from_form(headline_x, headline_y, headline_w, headline_h, (0.06, 0.60, 0.88, 0.16))
    subhead_box = _parse_box_from_form(subhead_x, subhead_y, subhead_w, subhead_h, (0.06, 0.76, 0.88, 0.08))
    cta_box = _parse_box_from_form(cta_x, cta_y, cta_w, cta_h, (0.06, 0.86, 0.50, 0.10))

    if use_layers:
        layout = {
            "layout_id": layout_id,
            "kv_asset_id": kv_asset_id,
            "font_family": font_family,
            "text_color": text_color,
            "text_align": text_align,
            "text_layers": layers_payload,
        }
    else:
        layout = {
            "layout_id": layout_id,
            "kv_asset_id": kv_asset_id,
            "headline": headline,
            "subhead": subhead,
            "cta": cta,
            "font_family": font_family,
            "text_color": text_color,
            "text_align": text_align,
            "headline_box": headline_box,
            "subhead_box": subhead_box,
            "cta_box": cta_box,
        }

    proj_dir = Path(settings.data_dir) / "projects" / project_id
    layouts_dir = proj_dir / "layouts"
    layouts_dir.mkdir(parents=True, exist_ok=True)
    (layouts_dir / f"layout_{layout_id}.json").write_text(json.dumps(layout, indent=2), "utf-8")

    preview_ids: list[str] = []
    for ratio in ("1:1", "4:5", "9:16"):
        size = settings.master_sizes.get(ratio)
        if not size:
            continue
        if use_layers:
            rendered = render_text_layers(
                kv=kv_img,
                size=size,
                text_layers=layers_payload,
                font_family=font_family,
                text_color_hex=text_color,
                text_align=text_align,
                image_box=image_box_payload,
            )
        else:
            rendered = render_text_layout(
                kv=kv_img,
                size=size,
                headline=headline,
                subhead=subhead,
                cta=cta,
                font_family=font_family,
                text_color_hex=text_color,
                headline_box=headline_box,
                subhead_box=subhead_box,
                cta_box=cta_box,
                text_align=text_align,
                font_scale=float(font_scale),
                image_box=image_box_payload,
            )
        out_bytes = _pil_to_png_bytes(rendered.image)
        label = (kv_asset.metadata or {}).get("display_name") or kv_asset.filename
        asset = store.add_asset(
            project_id=project_id,
            kind="text_preview",
            filename=f"text_preview_{label}_{ratio.replace(':','x')}.png",
            content=out_bytes,
            metadata={
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "layout_id": layout_id,
                "font_family": font_family,
                "text_color": text_color,
                "text_align": text_align,
                "text_layers": len(layers_payload) if use_layers else None,
                "headline": headline if not use_layers else None,
                "subhead": subhead if not use_layers else None,
                "cta": cta if not use_layers else None,
            },
            subdir="text_previews",
        )
        preview_ids.append(asset.asset_id)

    store.write_run_manifest(
        project_id,
        {
            "type": "layout_preview",
            "provider": "pillow",
            "model": "render_text_layers" if use_layers else "render_text_layout",
            "inputs": {
                "kv_asset_id": kv_asset_id,
                "layout_id": layout_id,
                "ratios": ["1:1", "4:5", "9:16"],
                "text_layers": len(layers_payload) if use_layers else None,
                "image_box": image_box_payload,
            },
            "outputs": {"preview_asset_ids": preview_ids},
        },
    )

    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


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


@app.post("/projects/{project_id}/copy/sets")
async def generate_copy_sets(
    project_id: str,
    brief_text: str = Form(...),
    count: int = Form(8),
    use_images: bool = Form(False),
    return_to: str = Form(""),
):
    proj = store.read_project(project_id)
    ref_paths = [store.abs_asset_path(project_id, a) for a in proj.assets if a.kind in ("reference", "product", "kv")]

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
    sets = await openai.generate_copy_sets(brief_text=full_brief, count=int(count))

    store.write_run_manifest(
        project_id,
        {
            "type": "copy_sets",
            "provider": openai.name,
            "model": settings.openai_text_model,
            "inputs": {"count": int(count), "use_images": bool(use_images)},
            "outputs": {"n_sets": len(sets)},
        },
    )

    proj_dir = Path(settings.data_dir) / "projects" / project_id
    (proj_dir / "copy_sets.json").write_text(json.dumps({"sets": sets}, indent=2), "utf-8")

    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}/editor"
    return RedirectResponse(url=redirect_path, status_code=303)


@app.post("/projects/{project_id}/masters/build")
async def build_masters(
    project_id: str,
    kv_asset_id: str = Form(...),
    headline: str = Form(""),
    headline_select: str = Form(""),
    cta: str = Form("Learn more"),
    motif_asset_id: str = Form(""),
    motif_opacity: float = Form(0.14),
    motif_tint_hex: str = Form("#266156"),
    motif_position: str = Form("right"),
    subject_position: str = Form("right"),
):
    proj = store.read_project(project_id)
    use_headline = (headline_select or "").strip() or (headline or "").strip()
    if not use_headline:
        raise HTTPException(status_code=400, detail="headline is required (type one or select one)")
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
            headline=use_headline,
            cta=cta,
            motif=motif_img,
            motif_opacity=float(motif_opacity),
            motif_tint_hex=motif_tint_hex,
            motif_position=motif_position,
            subject_position=subject_position,
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
                "headline": use_headline,
                "cta": cta,
                "motif_asset_id": motif_asset_id or None,
                "motif_opacity": float(motif_opacity),
                "motif_tint_hex": motif_tint_hex,
                "motif_position": motif_position,
                "subject_position": subject_position,
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
