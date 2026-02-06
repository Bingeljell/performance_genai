from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
assets_dir = BASE_DIR.parents[2] / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

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


def _make_outpaint_canvas_with_box(
    base: Image.Image,
    size: tuple[int, int],
    image_box: dict[str, Any] | None,
) -> Image.Image:
    tw, th = size
    canvas = Image.new("RGB", (tw, th), (128, 128, 128))
    try:
        import random

        px = canvas.load()
        for _ in range(int(tw * th * 0.002)):
            x = random.randint(0, tw - 1)
            y = random.randint(0, th - 1)
            v = 120 + random.randint(0, 20)
            px[x, y] = (v, v, v)
    except Exception:
        pass

    if not image_box:
        iw, ih = base.size
        if iw > 0 and ih > 0:
            scale = min(tw / iw, th / ih)
            nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
            resized = base.convert("RGB").resize((nw, nh), Image.Resampling.LANCZOS)
            left = max(0, (tw - nw) // 2)
            top = max(0, (th - nh) // 2)
            canvas.paste(resized, (left, top))
        return canvas

    try:
        x = float(image_box.get("x", 0))
        y = float(image_box.get("y", 0))
        w = float(image_box.get("w", 1))
    except (TypeError, ValueError):
        return canvas

    if w <= 0:
        iw, ih = base.size
        if iw > 0 and ih > 0:
            scale = min(tw / iw, th / ih)
            nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
            resized = base.convert("RGB").resize((nw, nh), Image.Resampling.LANCZOS)
            left = max(0, (tw - nw) // 2)
            top = max(0, (th - nh) // 2)
            canvas.paste(resized, (left, top))
        return canvas

    img_w, img_h = base.size
    if img_w <= 0 or img_h <= 0:
        return canvas

    target_w = max(1, int(round(w * tw)))
    target_h = max(1, int(round(target_w * (img_h / img_w))))
    resized = base.convert("RGB").resize((target_w, target_h), Image.Resampling.LANCZOS)
    px = int(round(x * tw))
    py = int(round(y * th))
    canvas.paste(resized, (px, py))
    return canvas
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


def _export_profiles() -> dict[str, dict[str, tuple[int, int]]]:
    return {"performance_default": dict(settings.master_sizes)}


def _resolve_export_size(ratio: str, size_profile: str) -> tuple[int, int]:
    profiles = _export_profiles()
    profile = profiles.get(size_profile) or profiles["performance_default"]
    size = profile.get(ratio)
    if not size:
        raise HTTPException(status_code=400, detail=f"ratio '{ratio}' is not available in profile '{size_profile}'")
    return size


def _load_layout(project_id: str, layout_id: str) -> dict[str, Any]:
    layouts_dir = Path(settings.data_dir) / "projects" / project_id / "layouts"
    layout_path = layouts_dir / f"layout_{layout_id}.json"
    if not layout_path.exists():
        raise HTTPException(status_code=404, detail="layout not found")
    try:
        loaded = json.loads(layout_path.read_text("utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="failed to parse layout")
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=500, detail="layout payload is invalid")
    return loaded


def _collect_render_elements(project_id: str, proj: Any, layout: dict[str, Any]) -> list[dict[str, Any]]:
    elements_layout = layout.get("elements") if isinstance(layout.get("elements"), list) else []
    if not elements_layout:
        return []
    out: list[dict[str, Any]] = []
    for el in elements_layout:
        if not isinstance(el, dict):
            continue
        asset_id = (el.get("asset_id") or "").strip()
        if not asset_id:
            continue
        asset = next(
            (a for a in proj.assets if a.asset_id == asset_id and a.kind in ("element", "motif", "product")),
            None,
        )
        if not asset:
            continue
        path = store.abs_asset_path(project_id, asset)
        if not path.exists():
            continue
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            continue
        out.append({"image": img, "box": el.get("box"), "opacity": el.get("opacity", 1)})
    return out


def _render_layout_export_png(
    project_id: str,
    proj: Any,
    layout: dict[str, Any],
    size: tuple[int, int],
) -> bytes:
    kv_asset_id = (layout.get("kv_asset_id") or "").strip()
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="layout kv_asset_id is missing or invalid")
    kv_img = Image.open(store.abs_asset_path(project_id, kv_asset)).convert("RGB")
    render_elements = _collect_render_elements(project_id, proj, layout)
    if layout.get("text_layers"):
        rendered = render_text_layers(
            kv=kv_img,
            size=size,
            text_layers=layout.get("text_layers") or [],
            font_family=layout.get("font_family") or "dejavu",
            text_color_hex=layout.get("text_color") or "#ffffff",
            text_align=layout.get("text_align") or "left",
            image_box=layout.get("image_box"),
            elements=render_elements,
            shapes=layout.get("shapes") or [],
        )
    else:
        rendered = render_text_layout(
            kv=kv_img,
            size=size,
            headline=layout.get("headline") or "",
            subhead=layout.get("subhead") or "",
            cta=layout.get("cta") or "",
            font_family=layout.get("font_family") or "dejavu",
            text_color_hex=layout.get("text_color") or "#ffffff",
            text_align=layout.get("text_align") or "left",
            headline_box=layout.get("headline_box"),
            subhead_box=layout.get("subhead_box"),
            cta_box=layout.get("cta_box"),
            image_box=layout.get("image_box"),
            elements=render_elements,
            shapes=layout.get("shapes") or [],
        )
    return _pil_to_png_bytes(rendered.image)


def _parse_json_list_payload(raw: str, label: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be JSON list: {exc}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail=f"{label} must be JSON list")
    out: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            out.append(item)
    return out


def _normalize_elements_for_render(elements_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    elements_layout: list[dict[str, Any]] = []
    for el in elements_payload:
        asset_id = (el.get("asset_id") or "").strip()
        if not asset_id:
            continue
        box = el.get("box") if isinstance(el.get("box"), dict) else {}
        try:
            box_norm = (
                float(box.get("x", 0)),
                float(box.get("y", 0)),
                float(box.get("w", 0)),
                float(box.get("h", 0)),
            )
        except (TypeError, ValueError):
            continue
        elements_layout.append(
            {
                "asset_id": asset_id,
                "box": box_norm,
                "opacity": float(el.get("opacity", 1) or 1),
            }
        )
    return elements_layout


def _normalize_shapes_for_render(shapes_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shapes_layout: list[dict[str, Any]] = []
    for shape in shapes_payload:
        box = shape.get("box") if isinstance(shape.get("box"), dict) else {}
        try:
            box_norm = (
                float(box.get("x", 0)),
                float(box.get("y", 0)),
                float(box.get("w", 0)),
                float(box.get("h", 0)),
            )
        except (TypeError, ValueError):
            continue
        shapes_layout.append(
            {
                "shape": shape.get("shape") or shape.get("type") or "rect",
                "box": box_norm,
                "color": shape.get("color") or "#ffffff",
                "opacity": float(shape.get("opacity", 1) or 1),
            }
        )
    return shapes_layout


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    projects = store.list_projects()
    grouped: dict[str, dict[str, list[Any]]] = {}
    brand_options: list[str] = []
    for p in projects:
        brand = (p.brand_name or "").strip() or "Unassigned"
        campaign = (p.campaign_name or "").strip() or "Unassigned"
        grouped.setdefault(brand, {}).setdefault(campaign, []).append(p)
        if brand and brand != "Unassigned":
            brand_options.append(brand)
    brand_options = sorted(set(brand_options))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"projects": projects, "grouped": grouped, "brand_options": brand_options},
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
def editor_page(request: Request, project_id: str, layout_id: str = ""):
    proj = store.read_project(project_id)
    assets = list(reversed(proj.assets))
    kvs = [a for a in assets if a.kind == "kv"]
    kv_choices = [
        {
            "id": a.asset_id,
            "label": (a.metadata or {}).get("display_name") or a.filename,
            "url": f"/projects/{project_id}/assets/{a.asset_id}",
        }
        for a in kvs
    ]
    selected_kv = request.query_params.get("kv") or ""
    editor_layout: dict | None = None
    if layout_id:
        try:
            proj_dir = Path(settings.data_dir) / "projects" / project_id
            layout_path = proj_dir / "layouts" / f"layout_{layout_id}.json"
            if layout_path.exists():
                editor_layout = json.loads(layout_path.read_text("utf-8"))
        except Exception:
            editor_layout = None

    copy_sets: list[dict[str, str]] = []
    try:
        proj_dir = Path(settings.data_dir) / "projects" / project_id
        cs_path = proj_dir / "copy_sets.json"
        if cs_path.exists():
            copy_sets = json.loads(cs_path.read_text("utf-8")).get("sets", []) or []
    except Exception:
        copy_sets = []

    text_previews = [a for a in assets if a.kind == "text_preview"]
    insert_assets = [a for a in assets if a.kind in ("element", "motif", "product")]
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
            "insert_assets": insert_assets,
            "editor_layout": editor_layout,
        },
    )


@app.post("/projects/{project_id}/assets/upload")
async def upload_asset(
    project_id: str,
    kind: str = Form("reference"),
    return_to: str = Form(""),
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
    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


@app.post("/projects/{project_id}/layouts/{layout_id}/outpaint")
async def outpaint_layout(
    project_id: str,
    layout_id: str,
    image_size: str = Form("2K"),
    prompt: str = Form(
        "Return the SAME image, only outpaint missing areas to fill the target ratio. "
        "Do not change or edit existing content."
    ),
):
    proj = store.read_project(project_id)
    layouts_dir = Path(settings.data_dir) / "projects" / project_id / "layouts"
    layout_path = layouts_dir / f"layout_{layout_id}.json"
    if not layout_path.exists():
        raise HTTPException(status_code=404, detail="layout not found")

    layout = json.loads(layout_path.read_text("utf-8"))
    ratio = layout.get("ratio") or layout.get("guide_ratio") or "1:1"
    size = settings.master_sizes.get(ratio)
    if not size:
        raise HTTPException(status_code=400, detail="ratio not supported for outpaint")

    kv_asset_id = layout.get("kv_asset_id") or ""
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="kv_asset_id must be an existing KV asset")

    kv_path = store.abs_asset_path(project_id, kv_asset)
    base_img = Image.open(kv_path).convert("RGB")
    locked_canvas = _make_outpaint_canvas_with_box(base_img, size, layout.get("image_box"))

    gemini = _get_gemini()
    sys_constraints = _build_reframe_constraints(False)
    images = await gemini.reframe_kv_with_motif(
        kv_image=kv_path,
        motif_image=None,
        prompt=f"{prompt}\n\n{sys_constraints}",
        aspect_ratio=ratio,
        image_size=image_size,
        n=1,
        locked_canvas=locked_canvas,
    )
    if not images:
        raise HTTPException(status_code=500, detail="outpaint failed")

    source_label = (kv_asset.metadata or {}).get("display_name") or kv_asset.filename
    display_label = f"{source_label}_outpaint_{ratio}"
    buf = _pil_to_png_bytes(images[0].image)
    out_asset = store.add_asset(
        project_id=project_id,
        kind="kv",
        filename="kv_outpaint.png",
        content=buf,
        metadata={
            "provider": images[0].provider,
            "model": images[0].model,
            "prompt": images[0].prompt_used,
            "source_kv_asset_id": kv_asset_id,
            "aspect_ratio": ratio,
            "image_size": image_size,
            "display_name": display_label,
            "source_layout_id": layout_id,
            "image_box": layout.get("image_box"),
        },
        subdir="kvs",
    )

    new_layout_id = uuid.uuid4().hex[:12]
    new_layout = dict(layout)
    new_layout.update(
        {
            "layout_id": new_layout_id,
            "layout_kind": "ratio_outpaint",
            "source_layout_id": layout_id,
            "ratio": ratio,
            "kv_asset_id": out_asset.asset_id,
            "guide_ratio": ratio,
            "image_box": None,
        }
    )
    (layouts_dir / f"layout_{new_layout_id}.json").write_text(json.dumps(new_layout, indent=2), "utf-8")

    elements_layout = new_layout.get("elements") if isinstance(new_layout.get("elements"), list) else []
    render_elements: list[dict] = []
    if elements_layout:
        for el in elements_layout:
            if not isinstance(el, dict):
                continue
            asset_id = (el.get("asset_id") or "").strip()
            if not asset_id:
                continue
            asset = next(
                (a for a in proj.assets if a.asset_id == asset_id and a.kind in ("element", "motif", "product")),
                None,
            )
            if not asset:
                continue
            path = store.abs_asset_path(project_id, asset)
            if not path.exists():
                continue
            try:
                img = Image.open(path).convert("RGBA")
            except Exception:
                continue
            render_elements.append(
                {
                    "image": img,
                    "box": el.get("box"),
                    "opacity": el.get("opacity", 1),
                }
            )

    kv_img = Image.open(store.abs_asset_path(project_id, out_asset)).convert("RGB")
    if new_layout.get("text_layers"):
        rendered = render_text_layers(
            kv=kv_img,
            size=size,
            text_layers=new_layout.get("text_layers") or [],
            font_family=new_layout.get("font_family") or "dejavu",
            text_color_hex=new_layout.get("text_color") or "#ffffff",
            text_align=new_layout.get("text_align") or "left",
            image_box=None,
            elements=render_elements,
            shapes=new_layout.get("shapes") or [],
        )
    else:
        rendered = render_text_layout(
            kv=kv_img,
            size=size,
            headline=new_layout.get("headline") or "",
            subhead=new_layout.get("subhead") or "",
            cta=new_layout.get("cta") or "",
            font_family=new_layout.get("font_family") or "dejavu",
            text_color_hex=new_layout.get("text_color") or "#ffffff",
            text_align=new_layout.get("text_align") or "left",
            headline_box=new_layout.get("headline_box"),
            subhead_box=new_layout.get("subhead_box"),
            cta_box=new_layout.get("cta_box"),
            image_box=None,
            elements=render_elements,
            shapes=new_layout.get("shapes") or [],
        )

    preview_asset = store.add_asset(
        project_id=project_id,
        kind="text_preview",
        filename="layout_outpaint_preview.png",
        content=_pil_to_png_bytes(rendered.image),
        metadata={
            "ratio": ratio,
            "ratio_layout_id": new_layout_id,
            "source_layout_id": layout_id,
            "outpaint_kv_asset_id": out_asset.asset_id,
        },
        subdir="text_previews",
    )

    store.write_run_manifest(
        project_id,
        {
            "type": "layout_outpaint",
            "provider": gemini.name,
            "model": settings.gemini_image_model,
            "inputs": {
                "layout_id": layout_id,
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "image_size": image_size,
            },
            "outputs": {"kv_asset_id": out_asset.asset_id, "preview_asset_id": preview_asset.asset_id},
        },
    )

    return RedirectResponse(url=f"/projects/{project_id}/editor?layout_id={new_layout_id}", status_code=303)


@app.post("/projects/{project_id}/layouts/{layout_id}/export")
def export_layout(
    project_id: str,
    layout_id: str,
    size_profile: str = Form("performance_default"),
):
    proj = store.read_project(project_id)
    layout = _load_layout(project_id, layout_id)
    ratio = (layout.get("ratio") or layout.get("guide_ratio") or "1:1").strip() or "1:1"
    size = _resolve_export_size(ratio, size_profile)
    png = _render_layout_export_png(project_id, proj, layout, size)
    safe_ratio = ratio.replace(":", "x")
    filename = f"layout_{safe_ratio}_{size[0]}x{size[1]}.png"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=png, media_type="image/png", headers=headers)


@app.post("/projects/{project_id}/layouts/export_current")
def export_current_layout(
    project_id: str,
    kv_asset_id: str = Form(...),
    text_layers: str = Form(""),
    image_box: str = Form(""),
    elements: str = Form(""),
    shapes: str = Form(""),
    guide_ratio: str = Form("1:1"),
    font_family: str = Form("dejavu"),
    text_color: str = Form("#ffffff"),
    text_align: str = Form("left"),
    size_profile: str = Form("performance_default"),
):
    proj = store.read_project(project_id)
    kv_asset = next((a for a in proj.assets if a.asset_id == kv_asset_id and a.kind == "kv"), None)
    if not kv_asset:
        raise HTTPException(status_code=400, detail="kv_asset_id must be an existing KV asset")

    ratio = (guide_ratio or "1:1").strip() or "1:1"
    size = _resolve_export_size(ratio, size_profile)
    kv_img = Image.open(store.abs_asset_path(project_id, kv_asset)).convert("RGB")

    image_box_payload = None
    if image_box.strip():
        try:
            parsed_box = json.loads(image_box)
            if isinstance(parsed_box, dict):
                image_box_payload = parsed_box
        except Exception:
            image_box_payload = None

    layers_payload = _parse_json_list_payload(text_layers, "text_layers")
    elements_payload = _parse_json_list_payload(elements, "elements")
    shapes_payload = _parse_json_list_payload(shapes, "shapes")

    elements_layout = _normalize_elements_for_render(elements_payload)
    shapes_layout = _normalize_shapes_for_render(shapes_payload)
    pseudo_layout = {"elements": elements_layout}
    render_elements = _collect_render_elements(project_id, proj, pseudo_layout)

    if layers_payload:
        rendered = render_text_layers(
            kv=kv_img,
            size=size,
            text_layers=layers_payload,
            font_family=font_family,
            text_color_hex=text_color,
            text_align=text_align,
            image_box=image_box_payload,
            elements=render_elements,
            shapes=shapes_layout,
        )
    else:
        rendered = render_text_layout(
            kv=kv_img,
            size=size,
            headline="",
            subhead="",
            cta="",
            font_family=font_family,
            text_color_hex=text_color,
            text_align=text_align,
            image_box=image_box_payload,
            elements=render_elements,
            shapes=shapes_layout,
        )

    png = _pil_to_png_bytes(rendered.image)
    safe_ratio = ratio.replace(":", "x")
    filename = f"canvas_{safe_ratio}_{size[0]}x{size[1]}.png"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=png, media_type="image/png", headers=headers)


@app.post("/projects/{project_id}/layouts/export_selected")
def export_selected_layouts(
    project_id: str,
    asset_ids: list[str] = Form(default=[]),
    size_profile: str = Form("performance_default"),
):
    if not asset_ids:
        raise HTTPException(status_code=400, detail="select at least one preview")
    proj = store.read_project(project_id)
    selected_previews = [a for a in proj.assets if a.kind == "text_preview" and a.asset_id in set(asset_ids)]
    layout_ids: list[str] = []
    seen: set[str] = set()
    for preview in selected_previews:
        meta = preview.metadata or {}
        layout_id = (meta.get("ratio_layout_id") or meta.get("layout_id") or "").strip()
        if not layout_id or layout_id in seen:
            continue
        seen.add(layout_id)
        layout_ids.append(layout_id)
    if not layout_ids:
        raise HTTPException(status_code=400, detail="selected previews do not contain exportable layouts")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        written = 0
        for idx, lid in enumerate(layout_ids, start=1):
            try:
                layout = _load_layout(project_id, lid)
                ratio = (layout.get("ratio") or layout.get("guide_ratio") or "1:1").strip() or "1:1"
                size = _resolve_export_size(ratio, size_profile)
                png = _render_layout_export_png(project_id, proj, layout, size)
            except Exception:
                continue
            safe_ratio = ratio.replace(":", "x")
            name = f"{idx:02d}_{safe_ratio}_{size[0]}x{size[1]}_{lid[:6]}.png"
            zf.writestr(name, png)
            written += 1
    if written == 0:
        raise HTTPException(status_code=400, detail="no exports could be generated")

    zip_bytes = buf.getvalue()
    headers = {"Content-Disposition": 'attachment; filename="selected_layout_exports.zip"'}
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


@app.post("/projects/{project_id}/delete")
def delete_project(project_id: str):
    store.delete_project(project_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/projects/{project_id}/assets/{asset_id}/delete")
def delete_asset(project_id: str, asset_id: str, return_to: str = Form("")):
    proj = store.read_project(project_id)
    asset = next((a for a in proj.assets if a.asset_id == asset_id), None)
    if asset and asset.kind == "text_preview":
        linked = (asset.metadata or {}).get("outpaint_kv_asset_id")
        if linked:
            try:
                store.delete_asset(project_id, linked)
            except Exception:
                pass
    store.delete_asset(project_id, asset_id)
    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


@app.post("/projects/{project_id}/assets/bulk_delete")
def bulk_delete_assets(
    project_id: str,
    asset_ids: list[str] = Form(default=[]),
    asset_kind: str = Form(""),
    return_to: str = Form(""),
):
    # v0: best-effort bulk delete for faster iteration.
    proj = store.read_project(project_id)
    if asset_kind:
        allowed = {a.asset_id for a in proj.assets if a.kind == asset_kind}
    else:
        allowed = {a.asset_id for a in proj.assets}
    for asset_id in asset_ids:
        if asset_id not in allowed:
            continue
        try:
            asset = next((a for a in proj.assets if a.asset_id == asset_id), None)
            if asset and asset.kind == "text_preview":
                linked = (asset.metadata or {}).get("outpaint_kv_asset_id")
                if linked:
                    store.delete_asset(project_id, linked)
            store.delete_asset(project_id, asset_id)
        except Exception:
            continue
    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


@app.post("/projects/{project_id}/copy/headlines/delete")
def delete_headlines(
    project_id: str,
    indices: list[int] = Form(default=[]),
    clear_all: str = Form(""),
    return_to: str = Form(""),
):
    proj_dir = Path(settings.data_dir) / "projects" / project_id
    hl_path = proj_dir / "copy_headlines.json"
    headlines: list[str] = []
    if hl_path.exists():
        try:
            headlines = json.loads(hl_path.read_text("utf-8")).get("headlines", []) or []
        except Exception:
            headlines = []

    if _parse_bool(clear_all):
        headlines = []
    elif indices:
        remove: set[int] = set()
        for idx in indices:
            try:
                remove.add(int(idx))
            except (TypeError, ValueError):
                continue
        headlines = [h for i, h in enumerate(headlines) if i not in remove]

    hl_path.write_text(json.dumps({"headlines": headlines}, indent=2), "utf-8")
    redirect_path = _safe_return_path(return_to) or f"/projects/{project_id}"
    return RedirectResponse(url=redirect_path, status_code=303)


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


@app.post("/projects/{project_id}/layouts/preview")
async def preview_text_layout(
    project_id: str,
    kv_asset_id: str = Form(...),
    text_layers: str = Form(""),
    image_box: str = Form(""),
    elements: str = Form(""),
    shapes: str = Form(""),
    guide_ratio: str = Form(""),
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

    elements_payload: list[dict] = []
    if elements.strip():
        try:
            parsed = json.loads(elements)
            if isinstance(parsed, list):
                elements_payload = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"elements must be JSON list: {exc}") from exc

    shapes_payload: list[dict] = []
    if shapes.strip():
        try:
            parsed = json.loads(shapes)
            if isinstance(parsed, list):
                shapes_payload = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"shapes must be JSON list: {exc}") from exc

    headline_box = _parse_box_from_form(headline_x, headline_y, headline_w, headline_h, (0.06, 0.60, 0.88, 0.16))
    subhead_box = _parse_box_from_form(subhead_x, subhead_y, subhead_w, subhead_h, (0.06, 0.76, 0.88, 0.08))
    cta_box = _parse_box_from_form(cta_x, cta_y, cta_w, cta_h, (0.06, 0.86, 0.50, 0.10))

    elements_layout: list[dict] = []
    if elements_payload:
        for el in elements_payload:
            if not isinstance(el, dict):
                continue
            asset_id = (el.get("asset_id") or "").strip()
            if not asset_id:
                continue
            box = el.get("box") if isinstance(el.get("box"), dict) else {}
            try:
                box_norm = (
                    float(box.get("x", 0)),
                    float(box.get("y", 0)),
                    float(box.get("w", 0)),
                    float(box.get("h", 0)),
                )
            except (TypeError, ValueError):
                continue
            elements_layout.append(
                {
                    "asset_id": asset_id,
                    "box": box_norm,
                    "opacity": float(el.get("opacity", 1) or 1),
                }
            )

    shapes_layout: list[dict] = []
    if shapes_payload:
        for shape in shapes_payload:
            if not isinstance(shape, dict):
                continue
            box = shape.get("box") if isinstance(shape.get("box"), dict) else {}
            try:
                box_norm = (
                    float(box.get("x", 0)),
                    float(box.get("y", 0)),
                    float(box.get("w", 0)),
                    float(box.get("h", 0)),
                )
            except (TypeError, ValueError):
                continue
            shapes_layout.append(
                {
                    "shape": shape.get("shape") or shape.get("type") or "rect",
                    "box": box_norm,
                    "color": shape.get("color") or "#ffffff",
                    "opacity": float(shape.get("opacity", 1) or 1),
                }
            )

    if use_layers:
        layout = {
            "layout_id": layout_id,
            "layout_kind": "master",
            "kv_asset_id": kv_asset_id,
            "guide_ratio": guide_ratio or None,
            "font_family": font_family,
            "text_color": text_color,
            "text_align": text_align,
            "image_box": image_box_payload,
            "text_layers": layers_payload,
            "elements": elements_layout,
            "shapes": shapes_layout,
        }
    else:
        layout = {
            "layout_id": layout_id,
            "layout_kind": "master",
            "kv_asset_id": kv_asset_id,
            "guide_ratio": guide_ratio or None,
            "headline": headline,
            "subhead": subhead,
            "cta": cta,
            "font_family": font_family,
            "text_color": text_color,
            "text_align": text_align,
            "headline_box": headline_box,
            "subhead_box": subhead_box,
            "cta_box": cta_box,
            "image_box": image_box_payload,
            "elements": elements_layout,
            "shapes": shapes_layout,
        }

    proj_dir = Path(settings.data_dir) / "projects" / project_id
    layouts_dir = proj_dir / "layouts"
    layouts_dir.mkdir(parents=True, exist_ok=True)
    (layouts_dir / f"layout_{layout_id}.json").write_text(json.dumps(layout, indent=2), "utf-8")

    preview_ids: list[str] = []
    ratio_layout_ids: dict[str, str] = {}
    render_elements: list[dict] = []
    if elements_layout:
        for el in elements_layout:
            asset_id = el.get("asset_id")
            if not asset_id:
                continue
            asset = next(
                (a for a in proj.assets if a.asset_id == asset_id and a.kind in ("element", "motif", "product")),
                None,
            )
            if not asset:
                continue
            path = store.abs_asset_path(project_id, asset)
            if not path.exists():
                continue
            try:
                img = Image.open(path).convert("RGBA")
            except Exception:
                continue
            render_elements.append(
                {
                    "image": img,
                    "box": el.get("box"),
                    "opacity": el.get("opacity", 1),
                }
            )

    for ratio in ("1:1", "4:5", "9:16"):
        size = settings.master_sizes.get(ratio)
        if not size:
            continue
        ratio_layout_id = uuid.uuid4().hex[:12]
        ratio_layout_ids[ratio] = ratio_layout_id
        if use_layers:
            ratio_layout = {
                "layout_id": ratio_layout_id,
                "layout_kind": "ratio",
                "source_layout_id": layout_id,
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "guide_ratio": ratio,
                "font_family": font_family,
                "text_color": text_color,
                "text_align": text_align,
                "image_box": image_box_payload,
                "text_layers": layers_payload,
                "elements": elements_layout,
                "shapes": shapes_layout,
            }
        else:
            ratio_layout = {
                "layout_id": ratio_layout_id,
                "layout_kind": "ratio",
                "source_layout_id": layout_id,
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "guide_ratio": ratio,
                "headline": headline,
                "subhead": subhead,
                "cta": cta,
                "font_family": font_family,
                "text_color": text_color,
                "text_align": text_align,
                "headline_box": headline_box,
                "subhead_box": subhead_box,
                "cta_box": cta_box,
                "image_box": image_box_payload,
                "elements": elements_layout,
                "shapes": shapes_layout,
            }
        (layouts_dir / f"layout_{ratio_layout_id}.json").write_text(json.dumps(ratio_layout, indent=2), "utf-8")

        if use_layers:
            rendered = render_text_layers(
                kv=kv_img,
                size=size,
                text_layers=layers_payload,
                font_family=font_family,
                text_color_hex=text_color,
                text_align=text_align,
                image_box=image_box_payload,
                elements=render_elements,
                shapes=shapes_layout,
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
                elements=render_elements,
                shapes=shapes_layout,
            )
        out_bytes = _pil_to_png_bytes(rendered.image)
        label = (kv_asset.metadata or {}).get("display_name") or kv_asset.filename
        debug_render_layers: list[dict] | None = None
        if use_layers:
            debug_render_layers = []
            for layer in layers_payload:
                if not isinstance(layer, dict):
                    continue
                box = layer.get("box") if isinstance(layer.get("box"), dict) else {}
                try:
                    x = float(box.get("x", 0))
                    y = float(box.get("y", 0))
                    w = float(box.get("w", 0))
                    h = float(box.get("h", 0))
                except (TypeError, ValueError):
                    continue
                x1 = max(0, int(x * size[0]))
                y1 = max(0, int(y * size[1]))
                x2 = min(size[0], int((x + w) * size[0]))
                y2 = min(size[1], int((y + h) * size[1]))
                box_h = max(1, y2 - y1)
                font_px = None
                if layer.get("font_size_box_norm") is not None:
                    try:
                        font_px = float(layer.get("font_size_box_norm")) * box_h
                    except (TypeError, ValueError):
                        font_px = None
                if font_px is None and layer.get("font_size_norm") is not None:
                    try:
                        font_px = float(layer.get("font_size_norm")) * size[0]
                    except (TypeError, ValueError):
                        font_px = None
                debug_render_layers.append(
                    {
                        "text": layer.get("text"),
                        "box_norm": {"x": x, "y": y, "w": w, "h": h},
                        "box_px": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                        "font_px": font_px,
                        "font_size_box_norm": layer.get("font_size_box_norm"),
                        "font_size_norm": layer.get("font_size_norm"),
                    }
                )

        asset = store.add_asset(
            project_id=project_id,
            kind="text_preview",
            filename=f"text_preview_{label}_{ratio.replace(':','x')}.png",
            content=out_bytes,
            metadata={
                "ratio": ratio,
                "kv_asset_id": kv_asset_id,
                "layout_id": layout_id,
                "ratio_layout_id": ratio_layout_ids.get(ratio),
                "font_family": font_family,
                "text_color": text_color,
                "text_align": text_align,
                "text_layers": len(layers_payload) if use_layers else None,
                "headline": headline if not use_layers else None,
                "subhead": subhead if not use_layers else None,
                "cta": cta if not use_layers else None,
                "debug_text_layers": layers_payload if use_layers else None,
                "debug_render_layers": debug_render_layers,
                "debug_elements": elements_layout or None,
                "debug_image_box": image_box_payload,
                "debug_guide_ratio": guide_ratio or None,
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
                "elements": len(elements_payload),
            },
            "outputs": {"preview_asset_ids": preview_ids, "ratio_layout_ids": ratio_layout_ids},
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


@app.post("/projects/{project_id}/copy/sets/delete")
def delete_copy_sets(
    project_id: str,
    indices: list[int] = Form(default=[]),
    clear_all: str = Form(""),
    return_to: str = Form(""),
):
    proj_dir = Path(settings.data_dir) / "projects" / project_id
    cs_path = proj_dir / "copy_sets.json"
    sets: list[dict[str, str]] = []
    if cs_path.exists():
        try:
            sets = json.loads(cs_path.read_text("utf-8")).get("sets", []) or []
        except Exception:
            sets = []

    if _parse_bool(clear_all):
        sets = []
    elif indices:
        remove: set[int] = set()
        for idx in indices:
            try:
                remove.add(int(idx))
            except (TypeError, ValueError):
                continue
        sets = [s for i, s in enumerate(sets) if i not in remove]

    cs_path.write_text(json.dumps({"sets": sets}, indent=2), "utf-8")
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
