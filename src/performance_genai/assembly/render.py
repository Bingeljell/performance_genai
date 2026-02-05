from __future__ import annotations

from dataclasses import dataclass
import math

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class RenderedMaster:
    image: Image.Image
    scrim_applied: bool


def render_master_simple(
    kv: Image.Image,
    size: tuple[int, int],
    headline: str,
    cta: str,
    motif: Image.Image | None = None,
    motif_opacity: float = 0.14,
    motif_tint_hex: str = "#266156",
    motif_position: str = "right",
    subject_position: str = "right",
) -> RenderedMaster:
    """
    Minimal deterministic renderer:
    - resize KV to target size without stretching (cover-crop)
    - add a bottom gradient scrim overlay
    - draw headline + CTA over the image

    This is intentionally "v0 ugly but works". Templates come next.
    """
    base = _resize_contain(kv.convert("RGB"), size).convert("RGBA")

    if motif is not None:
        base = _apply_motif_overlay(
            base,
            motif=motif,
            opacity=motif_opacity,
            tint_hex=motif_tint_hex,
            motif_position=motif_position,
            subject_position=subject_position,
        )

    # Give 9:16 more room since copy blocks tend to be taller.
    ratio = _ratio_key_for_size(size)
    if ratio == "9:16":
        scrim_h = int(size[1] * 0.40)
    elif ratio == "4:5":
        scrim_h = int(size[1] * 0.34)
    else:
        scrim_h = int(size[1] * 0.30)
    scrim_y0 = size[1] - scrim_h
    base = _apply_bottom_gradient_scrim(base, y0=scrim_y0, max_alpha=200)

    draw = ImageDraw.Draw(base)

    pad = int(size[0] * 0.06)
    headline_box = (pad, scrim_y0 + pad, size[0] - pad, scrim_y0 + int(scrim_h * 0.58))
    cta_box = (pad, scrim_y0 + int(scrim_h * 0.64), size[0] - pad, size[1] - pad)

    # Fit headline into its box with a real TTF font if available.
    head_font, head_text, head_spacing = _fit_text_to_box(
        draw,
        headline,
        headline_box,
        max_font_px=int((headline_box[3] - headline_box[1]) * 0.32),
        min_font_px=max(18, int(size[0] * 0.026)),
    )
    _draw_multiline(
        draw,
        head_text,
        (headline_box[0], headline_box[1]),
        font=head_font,
        fill=(255, 255, 255, 255),
        spacing=head_spacing,
        shadow=True,
    )

    # CTA as a button for readability.
    _draw_cta_button(
        draw,
        cta=cta,
        box=cta_box,
        fill_hex="#ED8924",
        text_fill=(255, 255, 255, 255),
    )

    return RenderedMaster(image=base.convert("RGB"), scrim_applied=True)


def render_text_layout(
    kv: Image.Image,
    size: tuple[int, int],
    headline: str,
    subhead: str,
    cta: str,
    font_family: str,
    text_color_hex: str,
    headline_box: tuple[float, float, float, float],
    subhead_box: tuple[float, float, float, float],
    cta_box: tuple[float, float, float, float],
    text_align: str = "left",
    font_scale: float = 1.0,
    image_box: dict | None = None,
    elements: list[dict] | None = None,
    shapes: list[dict] | None = None,
) -> RenderedMaster:
    """
    Deterministic text overlay for editor previews.
    Boxes are normalized (x, y, w, h) in 0..1 coordinates.
    """
    base = _render_base_image(kv, size, image_box=image_box)
    if shapes:
        _apply_shapes(base, size, shapes)
    if elements:
        _apply_elements(base, size, elements)
    draw = ImageDraw.Draw(base)

    align = (text_align or "left").strip().lower()
    text_color = _hex_to_rgb(text_color_hex) + (255,)

    def draw_block(text: str, box_norm: tuple[float, float, float, float], scale: float) -> None:
        if not text:
            return
        px_box = _norm_box_to_px(box_norm, size)
        if px_box is None:
            return
        x1, y1, x2, y2 = px_box
        # No scrim by default; keep previews clean.

        max_font = max(14, int((y2 - y1) * scale * max(0.5, font_scale)))
        min_font = max(12, int(max_font * 0.55))
        font, wrapped, spacing = _fit_text_to_box(
            draw,
            text,
            (x1, y1, x2, y2),
            max_font_px=max_font,
            min_font_px=min_font,
            font_family=font_family,
        )
        tx = x1
        ty = y1
        if align == "center":
            try:
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = 0
            tx = x1 + max(0, (x2 - x1 - tw) // 2)
        _draw_multiline(draw, wrapped, (tx, ty), font=font, fill=text_color, spacing=spacing, shadow=True)

    draw_block(headline, headline_box, scale=0.48)
    draw_block(subhead, subhead_box, scale=0.36)

    # CTA as a button for now.
    cta_px = _norm_box_to_px(cta_box, size)
    if cta_px and cta:
        _draw_cta_button(
            draw,
            cta=cta,
            box=cta_px,
            fill_hex="#ED8924",
            text_fill=(255, 255, 255, 255),
        )

    return RenderedMaster(image=base.convert("RGB"), scrim_applied=True)


def render_text_layers(
    kv: Image.Image,
    size: tuple[int, int],
    text_layers: list[dict],
    font_family: str,
    text_color_hex: str,
    text_align: str = "left",
    image_box: dict | None = None,
    elements: list[dict] | None = None,
    shapes: list[dict] | None = None,
) -> RenderedMaster:
    """
    Render multiple text boxes using absolute font sizes from the editor.
    Each layer expects:
      - text: string
      - box: {x,y,w,h} normalized to 0..1
      - font_size_norm: font px / canvas height
      - font_family, color, align (optional overrides)
    """
    base = _render_base_image(kv, size, image_box=image_box)
    if shapes:
        _apply_shapes(base, size, shapes)
    if elements:
        _apply_elements(base, size, elements)
    draw = ImageDraw.Draw(base)

    default_align = (text_align or "left").strip().lower()
    default_color = _hex_to_rgb(text_color_hex) + (255,)

    for layer in text_layers or []:
        if not isinstance(layer, dict):
            continue
        text = (layer.get("text_wrapped") or layer.get("text") or "").strip()
        if not text:
            continue
        box = layer.get("box") or {}
        try:
            box_norm = (
                float(box.get("x", 0)),
                float(box.get("y", 0)),
                float(box.get("w", 0)),
                float(box.get("h", 0)),
            )
        except (TypeError, ValueError):
            continue
        px_box = _norm_box_to_px(box_norm, size)
        if px_box is None:
            continue
        x1, y1, x2, y2 = px_box
        max_w = max(1, x2 - x1)

        font_px = None
        if layer.get("font_px") is not None and layer.get("font_base_width"):
            try:
                font_px = float(layer.get("font_px")) * (size[0] / float(layer.get("font_base_width")))
            except (TypeError, ValueError, ZeroDivisionError):
                font_px = None
        font_size_box_norm = layer.get("font_size_box_norm")
        if font_px is not None:
            font_px = max(10, int(font_px))
        elif font_size_box_norm is not None:
            try:
                font_px = max(10, int(float(font_size_box_norm) * (y2 - y1)))
            except (TypeError, ValueError):
                font_px = max(12, int((y2 - y1) * 0.5))
        else:
            font_size_norm = layer.get("font_size_norm")
            if font_size_norm is None:
                font_px = max(12, int((y2 - y1) * 0.5))
            else:
                try:
                    font_px = max(10, int(float(font_size_norm) * size[0]))
                except (TypeError, ValueError):
                    font_px = max(12, int((y2 - y1) * 0.5))

        layer_font_family = layer.get("font_family") or font_family
        font = _load_font(font_px, font_family=layer_font_family)
        spacing = max(2, int(font_px * 0.18))
        text_wrapped = layer.get("text_wrapped")
        if isinstance(text_wrapped, str) and text_wrapped.strip():
            wrapped = text_wrapped
        else:
            wrapped = _wrap_to_width(draw, text, font, max_w)

        align = (layer.get("align") or default_align).strip().lower()
        color_hex = layer.get("color") or text_color_hex
        try:
            text_color = _hex_to_rgb(color_hex) + (255,)
        except Exception:
            text_color = default_color

        bg_color = layer.get("bg_color")
        bg_opacity = layer.get("bg_opacity")
        if bg_color and bg_opacity is not None:
            try:
                alpha = max(0, min(1, float(bg_opacity)))
            except (TypeError, ValueError):
                alpha = 0
            if alpha > 0:
                try:
                    bg_rgb = _hex_to_rgb(bg_color)
                except Exception:
                    bg_rgb = (0, 0, 0)
                bg_fill = bg_rgb + (int(alpha * 255),)
                radius_px = 0
                if layer.get("bg_radius_px") is not None and layer.get("bg_radius_base_width"):
                    try:
                        radius_px = float(layer.get("bg_radius_px")) * (size[0] / float(layer.get("bg_radius_base_width")))
                    except (TypeError, ValueError, ZeroDivisionError):
                        radius_px = 0
                pad_px = 0
                if layer.get("bg_padding_px") is not None and layer.get("bg_padding_base_width"):
                    try:
                        pad_px = float(layer.get("bg_padding_px")) * (size[0] / float(layer.get("bg_padding_base_width")))
                    except (TypeError, ValueError, ZeroDivisionError):
                        pad_px = 0
                if pad_px <= 0:
                    pad_px = max(4, min(24, font_px * 0.22))
                x1p = max(0, int(x1 - pad_px))
                y1p = max(0, int(y1 - pad_px))
                x2p = min(size[0], int(x2 + pad_px))
                y2p = min(size[1], int(y2 + pad_px))
                radius_px = max(0, min(radius_px, min(x2p - x1p, y2p - y1p) / 2))
                try:
                    draw.rounded_rectangle((x1p, y1p, x2p, y2p), radius=radius_px, fill=bg_fill)
                except Exception:
                    draw.rectangle((x1p, y1p, x2p, y2p), fill=bg_fill)

        tx = x1
        if align in ("center", "right"):
            try:
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = 0
            if align == "center":
                tx = x1 + max(0, (max_w - tw) // 2)
            else:
                tx = x2 - tw

        draw.multiline_text((tx, y1), wrapped, font=font, fill=text_color, spacing=spacing)

    return RenderedMaster(image=base.convert("RGB"), scrim_applied=False)


def _draw_multiline(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font,
    fill,
    spacing: int,
    shadow: bool = False,
) -> None:
    x, y = xy
    if shadow:
        draw.multiline_text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180), spacing=spacing)
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=spacing)


def _resize_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """
    Resize to cover the target canvas (no stretching), then center-crop.
    """
    tw, th = size
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img.resize(size, Image.Resampling.LANCZOS)

    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th))


def _resize_contain(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """
    Resize to fit inside the target canvas (no stretching), then center with padding.
    """
    tw, th = size
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img.resize(size, Image.Resampling.LANCZOS)

    scale = min(tw / iw, th / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    left = max(0, (tw - nw) // 2)
    top = max(0, (th - nh) // 2)
    canvas.paste(resized, (left, top))
    return canvas


def _render_base_image(
    kv: Image.Image,
    size: tuple[int, int],
    image_box: dict | None = None,
) -> Image.Image:
    if not image_box:
        return _resize_contain(kv.convert("RGB"), size).convert("RGBA")

    try:
        x = float(image_box.get("x", 0))
        y = float(image_box.get("y", 0))
        w = float(image_box.get("w", 1))
        h = float(image_box.get("h", 1))
    except (TypeError, ValueError):
        return _resize_contain(kv.convert("RGB"), size).convert("RGBA")

    if w <= 0 or h <= 0:
        return _resize_contain(kv.convert("RGB"), size).convert("RGBA")

    tw, th = size
    cx = x + (w / 2)
    cy = y + (h / 2)

    img_w, img_h = kv.size
    if img_w <= 0 or img_h <= 0:
        return _resize_contain(kv.convert("RGB"), size).convert("RGBA")

    # Keep image aspect ratio; use width as the primary scale reference.
    target_w = max(1, int(w * tw))
    target_h = max(1, int(target_w * (img_h / img_w)))

    px = int((cx * tw) - (target_w / 2))
    py = int((cy * th) - (target_h / 2))

    base = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    resized = kv.convert("RGBA").resize((target_w, target_h), Image.Resampling.LANCZOS)
    base.paste(resized, (px, py), resized)
    return base


def _apply_elements(base: Image.Image, size: tuple[int, int], elements: list[dict]) -> None:
    tw, th = size
    for el in elements:
        if not isinstance(el, dict):
            continue
        img = el.get("image")
        if not isinstance(img, Image.Image):
            continue
        box = el.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x, y, w, h = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        cx = x + (w / 2)
        cy = y + (h / 2)
        w_px = max(1, int(w * tw))
        img_w, img_h = img.size
        if img_w <= 0 or img_h <= 0:
            continue
        h_px = max(1, int(w_px * (img_h / img_w)))
        x1 = int((cx * tw) - (w_px / 2))
        y1 = int((cy * th) - (h_px / 2))
        try:
            layer = img.resize((w_px, h_px), Image.Resampling.LANCZOS).convert("RGBA")
        except Exception:
            continue
        opacity = el.get("opacity")
        if opacity is not None:
            try:
                alpha = max(0.0, min(1.0, float(opacity)))
                if alpha < 1:
                    a = layer.getchannel("A").point(lambda p: int(p * alpha))
                    layer.putalpha(a)
            except Exception:
                pass
        base.paste(layer, (x1, y1), layer)


def _apply_shapes(base: Image.Image, size: tuple[int, int], shapes: list[dict]) -> None:
    tw, th = size
    draw = ImageDraw.Draw(base, "RGBA")
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        box = shape.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x, y, w, h = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        x1 = int(x * tw)
        y1 = int(y * th)
        x2 = int((x + w) * tw)
        y2 = int((y + h) * th)
        color_hex = shape.get("color") or "#ffffff"
        try:
            rgb = _hex_to_rgb(color_hex)
        except Exception:
            rgb = (255, 255, 255)
        try:
            alpha = max(0.0, min(1.0, float(shape.get("opacity", 1))))
        except (TypeError, ValueError):
            alpha = 1.0
        fill = rgb + (int(alpha * 255),)
        shape_type = (shape.get("shape") or "rect").lower()

        if shape_type == "square":
            side = min(x2 - x1, y2 - y1)
            x2 = x1 + side
            y2 = y1 + side
            draw.rectangle((x1, y1, x2, y2), fill=fill)
        elif shape_type == "circle":
            draw.ellipse((x1, y1, x2, y2), fill=fill)
        elif shape_type == "triangle":
            draw.polygon([(x1, y2), ((x1 + x2) // 2, y1), (x2, y2)], fill=fill)
        elif shape_type == "star":
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            outer = min(x2 - x1, y2 - y1) / 2
            inner = outer * 0.5
            points = []
            for i in range(10):
                ang = math.radians(i * 36 - 90)
                r = outer if i % 2 == 0 else inner
                points.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            draw.polygon(points, fill=fill)
        else:
            draw.rectangle((x1, y1, x2, y2), fill=fill)


def _norm_box_to_px(
    box: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return None
    cw, ch = size
    x1 = max(0, int(x * cw))
    y1 = max(0, int(y * ch))
    x2 = min(cw, int((x + w) * cw))
    y2 = min(ch, int((y + h) * ch))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _draw_box_scrim(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], alpha: int) -> None:
    x1, y1, x2, y2 = box
    a = max(0, min(255, int(alpha)))
    draw.rectangle([(x1, y1), (x2, y2)], fill=(0, 0, 0, a))


def _apply_bottom_gradient_scrim(img_rgba: Image.Image, y0: int, max_alpha: int) -> Image.Image:
    """
    Apply a transparent->black gradient starting at y0 to the bottom.
    """
    w, h = img_rgba.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    height = max(1, h - max(0, y0))
    for i in range(height):
        a = int((i / height) * max_alpha)
        y = max(0, y0) + i
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))

    return Image.alpha_composite(img_rgba, overlay)


def _load_font(size: int, font_family: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Prefer a TTF font (system or bundled). If we can't find one, fall back to the
    default bitmap font (which is small and not ideal, but avoids crashing).
    """
    # Allow overriding via env later; for now probe common locations.
    family = (font_family or "").strip().lower()
    if family in ("dejavu", "dejavu sans", "dejavu_sans"):
        candidates = [
            "assets/fonts/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    elif family in ("helvetica", "helvetica neue"):
        candidates = [
            "/System/Library/Fonts/Supplemental/Helvetica.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    elif family in ("inter", "inter regular"):
        candidates = [
            "assets/fonts/Inter-Regular.ttf",
        ]
    else:
        candidates = [
            "assets/fonts/DejaVuSans.ttf",
            "assets/fonts/Inter-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\\\Windows\\\\Fonts\\\\arial.ttf",
        ]
    try:
        from pathlib import Path

        for c in candidates:
            p = Path(c)
            if p.exists():
                return ImageFont.truetype(str(p), size=size)
        fallback = [
            "/System/Library/Fonts/Supplemental/Helvetica.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\\\Windows\\\\Fonts\\\\arial.ttf",
        ]
        for c in fallback:
            p = Path(c)
            if p.exists():
                return ImageFont.truetype(str(p), size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    s = hex_color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) != 6:
        return (38, 97, 86)  # default teal-ish
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return (38, 97, 86)


def _protect_box_for_preset(size: tuple[int, int], preset: str) -> tuple[int, int, int, int] | None:
    """
    A simple rectangular "subject protection" mask. This is a stand-in for segmentation.
    """
    w, h = size
    p = (preset or "").strip().lower()
    if p in ("none", "off", "false", "0", ""):
        return None

    # Heuristic: protect ~42% width, centered vertically, most of the height.
    box_w = int(w * 0.44)
    box_h = int(h * 0.82)
    top = int(h * 0.12)

    if p in ("left", "l"):
        left = int(w * 0.06)
    elif p in ("center", "c", "middle"):
        left = (w - box_w) // 2
    else:
        # default: right
        left = int(w - box_w - w * 0.06)

    return (left, top, left + box_w, top + box_h)


def _apply_motif_overlay(
    base_rgba: Image.Image,
    motif: Image.Image,
    opacity: float,
    tint_hex: str,
    motif_position: str,
    subject_position: str,
) -> Image.Image:
    """
    Apply a brand motif behind everything, but avoid painting over the subject region.
    This uses a rectangular protection mask for v0 (no segmentation yet).
    """
    w, h = base_rgba.size

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    mp = (motif_position or "right").strip().lower()
    if mp in ("full", "cover"):
        # Full-canvas motif (rarely desired once you start doing cover-crop masters).
        motif_rgba = _resize_cover(motif.convert("RGBA"), (w, h))
        x0, y0 = 0, 0
    else:
        # Place motif as a design element on one side, preserving its proportions.
        # Default box: ~55% width on the chosen side, most of the height.
        box_w = int(w * 0.56)
        box_h = int(h * 0.90)
        pad_x = int(w * 0.04)
        pad_y = int(h * 0.05)
        if mp in ("left", "l"):
            box = (pad_x, pad_y, pad_x + box_w, pad_y + box_h)
        elif mp in ("center", "c", "middle"):
            box = ((w - box_w) // 2, pad_y, (w - box_w) // 2 + box_w, pad_y + box_h)
        else:
            box = (w - pad_x - box_w, pad_y, w - pad_x, pad_y + box_h)

        bw = max(1, box[2] - box[0])
        bh = max(1, box[3] - box[1])
        motif_rgba = _contain(motif.convert("RGBA"), (bw, bh))

        # Right-align within the box by default (matches common "logo outline" usage).
        x0 = box[2] - motif_rgba.size[0]
        y0 = box[1] + (bh - motif_rgba.size[1]) // 2

    tinted = _tint_preserving_alpha(motif_rgba, tint_hex)

    # Apply global opacity.
    alpha_scale = max(0.0, min(1.0, opacity))
    if alpha_scale < 1.0:
        ta = tinted.split()[3]
        ta = Image.eval(ta, lambda px: int(px * alpha_scale))
        tinted.putalpha(ta)

    # Punch out the subject region.
    protect = _protect_box_for_preset((w, h), subject_position)
    if protect:
        x1, y1, x2, y2 = protect
        clear = Image.new("L", (x2 - x1, y2 - y1), 0)
        ta = tinted.split()[3]
        # Offset the protection box into the motif's local coordinate space.
        local = (x1 - x0, y1 - y0)
        ta.paste(clear, local)
        tinted.putalpha(ta)

    overlay.paste(tinted, (x0, y0), tinted)
    return Image.alpha_composite(base_rgba, overlay)


def _contain(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """
    Resize to fit within size (no crop), preserving aspect ratio.
    """
    tw, th = size
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img.resize(size, Image.Resampling.LANCZOS)
    scale = min(tw / iw, th / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _tint_preserving_alpha(img_rgba: Image.Image, tint_hex: str) -> Image.Image:
    """
    If tint_hex is empty, keep original colors. Otherwise, recolor using alpha
    (or luminance fallback if alpha is missing/empty).
    """
    if not tint_hex or not tint_hex.strip():
        return img_rgba

    tint = _hex_to_rgb(tint_hex)
    r, g, b, a = img_rgba.split()

    # If alpha looks empty, fallback to luminance to capture line-art.
    alpha_extrema = a.getextrema()
    if alpha_extrema and alpha_extrema[1] == 0:
        lum = Image.merge("RGB", (r, g, b)).convert("L")
        a = lum

    colored = Image.new("RGBA", img_rgba.size, (tint[0], tint[1], tint[2], 255))
    colored.putalpha(a)
    return colored


def _ratio_key_for_size(size: tuple[int, int]) -> str:
    w, h = size
    if w == 0 or h == 0:
        return "1:1"
    # Compare against common ratios with a small tolerance.
    r = w / h
    if abs(r - (9 / 16)) < 0.02:
        return "9:16"
    if abs(r - (4 / 5)) < 0.02:
        return "4:5"
    return "1:1"


def _fit_text_to_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    max_font_px: int,
    min_font_px: int,
    font_family: str | None = None,
) -> tuple[ImageFont.ImageFont, str, int]:
    x1, y1, x2, y2 = box
    max_w = max(1, x2 - x1)
    max_h = max(1, y2 - y1)

    max_font_px = max(min_font_px, max_font_px)

    for px in range(max_font_px, min_font_px - 1, -2):
        font = _load_font(px, font_family=font_family)
        spacing = max(2, int(px * 0.18))
        wrapped = _wrap_to_width(draw, text, font, max_w)
        try:
            bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w <= max_w and h <= max_h:
                return font, wrapped, spacing
        except Exception:
            # Fallback: accept this size if no bbox measurement available.
            return font, wrapped, spacing

    font = _load_font(min_font_px, font_family=font_family)
    spacing = max(2, int(min_font_px * 0.18))
    return font, _wrap_to_width(draw, text, font, max_w), spacing


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    words = [w for w in (text or "").split() if w]
    if not words:
        return ""
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        try:
            bbox = draw.textbbox((0, 0), trial, font=font)
            if (bbox[2] - bbox[0]) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        except Exception:
            # If measurement fails, fallback to a crude char-based wrap.
            if len(trial) <= max(10, int(max_w / 12)):
                cur = trial
            else:
                lines.append(cur)
                cur = w
    lines.append(cur)
    return "\n".join(lines)


def _draw_cta_button(
    draw: ImageDraw.ImageDraw,
    cta: str,
    box: tuple[int, int, int, int],
    fill_hex: str,
    text_fill,
) -> None:
    x1, y1, x2, y2 = box
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)

    # Button geometry: centered horizontally, fixed height.
    btn_h = min(int(h * 0.78), 110)
    btn_w = min(int(w * 0.62), 640)
    btn_x1 = x1 + (w - btn_w) // 2
    btn_y1 = y1 + (h - btn_h) // 2
    btn_x2 = btn_x1 + btn_w
    btn_y2 = btn_y1 + btn_h

    r, g, b = _hex_to_rgb(fill_hex)
    radius = max(10, int(btn_h * 0.22))

    # Pillow >= 8 supports rounded_rectangle.
    try:
        draw.rounded_rectangle([(btn_x1, btn_y1), (btn_x2, btn_y2)], radius=radius, fill=(r, g, b, 255))
    except Exception:
        draw.rectangle([(btn_x1, btn_y1), (btn_x2, btn_y2)], fill=(r, g, b, 255))

    # Fit CTA text into the button.
    max_font = int(btn_h * 0.46)
    min_font = max(16, int(btn_h * 0.28))
    font, wrapped, spacing = _fit_text_to_box(
        draw,
        cta,
        (btn_x1 + 16, btn_y1 + 10, btn_x2 - 16, btn_y2 - 10),
        max_font_px=max_font,
        min_font_px=min_font,
    )
    # Center vertically/horizontally within button for single-line CTAs.
    try:
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = (0, 0)

    tx = btn_x1 + max(0, (btn_w - tw) // 2)
    ty = btn_y1 + max(0, (btn_h - th) // 2)
    _draw_multiline(draw, wrapped, (tx, ty), font=font, fill=text_fill, spacing=spacing, shadow=False)
