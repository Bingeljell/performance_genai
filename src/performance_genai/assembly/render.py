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
) -> RenderedMaster:
    """
    Minimal deterministic renderer:
    - resize KV to target size
    - add a bottom scrim rectangle
    - draw headline + CTA

    This is intentionally "v0 ugly but works". Templates come next.
    """
    canvas = kv.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)

    # Bottom scrim
    scrim_h = int(size[1] * 0.28)
    scrim_y0 = size[1] - scrim_h
    draw.rectangle([(0, scrim_y0), (size[0], size[1])], fill=(0, 0, 0, 170))

    # Use PIL's default bitmap font for v0 (no font assets yet).
    font_head = ImageFont.load_default()
    font_cta = ImageFont.load_default()

    pad = int(size[0] * 0.06)
    headline_box = (pad, scrim_y0 + pad, size[0] - pad, scrim_y0 + int(scrim_h * 0.6))
    cta_box = (pad, scrim_y0 + int(scrim_h * 0.62), size[0] - pad, size[1] - pad)

    _draw_wrapped(draw, headline, headline_box, font_head, fill=(255, 255, 255))
    _draw_wrapped(draw, cta, cta_box, font_cta, fill=(255, 255, 255))

    return RenderedMaster(image=canvas, scrim_applied=True)


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], font, fill):
    x1, y1, x2, y2 = box
    max_w = max(1, x2 - x1)
    # Crude wrap heuristic; good enough to see outputs.
    max_chars = max(10, int(max_w / 12))
    lines: list[str] = []
    words = text.split()
    cur: list[str] = []
    for w in words:
        test = " ".join(cur + [w])
        if len(test) > max_chars and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))

    y = y1
    for ln in lines:
        if y > y2:
            break
        draw.text((x1, y), ln, font=font, fill=fill)
        y += 14

