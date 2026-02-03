from __future__ import annotations

from dataclasses import dataclass

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
    protect_preset: str = "right",
) -> RenderedMaster:
    """
    Minimal deterministic renderer:
    - resize KV to target size without stretching (cover-crop)
    - add a bottom gradient scrim overlay
    - draw headline + CTA over the image

    This is intentionally "v0 ugly but works". Templates come next.
    """
    base = _resize_cover(kv.convert("RGB"), size).convert("RGBA")

    if motif is not None:
        base = _apply_motif_overlay(
            base,
            motif=motif,
            opacity=motif_opacity,
            tint_hex=motif_tint_hex,
            protect_preset=protect_preset,
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


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Prefer a TTF font (system or bundled). If we can't find one, fall back to the
    default bitmap font (which is small and not ideal, but avoids crashing).
    """
    # Allow overriding via env later; for now probe common locations.
    candidates: list[str] = [
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
    protect_preset: str,
) -> Image.Image:
    """
    Apply a brand motif behind everything, but avoid painting over the subject region.
    This uses a rectangular protection mask for v0 (no segmentation yet).
    """
    w, h = base_rgba.size

    # Scale motif to cover the canvas (similar to cover-crop) so it reads as a background element.
    motif_rgba = _resize_cover(motif.convert("RGBA"), (w, h))

    # Recolor/tint the motif to a brand color, keeping alpha from the original.
    tint = _hex_to_rgb(tint_hex)
    r, g, b, a = motif_rgba.split()
    # Use luminance as a mask to capture line-art even if alpha is missing/weak.
    lum = Image.merge("RGB", (r, g, b)).convert("L")
    mask = Image.eval(lum, lambda px: px)  # identity; kept for clarity
    tinted = Image.new("RGBA", (w, h), (tint[0], tint[1], tint[2], 255))
    tinted.putalpha(mask)

    # Apply global opacity.
    alpha_scale = max(0.0, min(1.0, opacity))
    if alpha_scale < 1.0:
        ta = tinted.split()[3]
        ta = Image.eval(ta, lambda px: int(px * alpha_scale))
        tinted.putalpha(ta)

    # Punch out the subject region.
    protect = _protect_box_for_preset((w, h), protect_preset)
    if protect:
        x1, y1, x2, y2 = protect
        clear = Image.new("L", (x2 - x1, y2 - y1), 0)
        ta = tinted.split()[3]
        ta.paste(clear, (x1, y1))
        tinted.putalpha(ta)

    return Image.alpha_composite(base_rgba, tinted)


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
) -> tuple[ImageFont.ImageFont, str, int]:
    x1, y1, x2, y2 = box
    max_w = max(1, x2 - x1)
    max_h = max(1, y2 - y1)

    max_font_px = max(min_font_px, max_font_px)

    for px in range(max_font_px, min_font_px - 1, -2):
        font = _load_font(px)
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

    font = _load_font(min_font_px)
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
