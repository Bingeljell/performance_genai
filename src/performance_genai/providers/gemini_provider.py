from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from performance_genai.config import settings
from performance_genai.providers.base import GeneratedImage, ObservedProfileResult


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        # Imported lazily so the app can start without the dependency installed.
        from google import genai  # type: ignore

        self._genai = genai
        self.client = genai.Client(api_key=api_key)

    async def propose_observed_profile(
        self,
        reference_images: list[Path],
        brief_text: str,
    ) -> ObservedProfileResult:
        """
        Very simple v0: ask for JSON. Persist the raw response.
        """
        prompt = (
            "You are analyzing ad creative reference images to propose a Brand Style Profile.\n"
            "Return STRICT JSON only (no markdown) with keys:\n"
            "- palette: {primary_hex, secondary_hex, avoid_hex: []}\n"
            "- lighting: {temperature, contrast_0_100, saturation_0_100, grain, style_tag}\n"
            "- composition: {shot_type, framing, depth_of_field, negative_space_zone}\n"
            "- do_list: [string]\n"
            "- dont_list: [string]\n"
            f"\nBrand/product context:\n{brief_text}\n"
        )

        # The google-genai SDK supports passing PIL Images in contents for multimodal models.
        contents: list[Any] = [prompt]
        for p in reference_images:
            contents.append(Image.open(p))

        resp = self.client.models.generate_content(
            model=settings.gemini_vision_model,
            contents=contents,
        )

        raw_text: str | None = getattr(resp, "text", None)
        parsed = _parse_jsonish(raw_text) if raw_text else None

        # Persist an envelope so the UI can show both the structured result and raw output.
        profile: dict[str, Any] = {
            "_meta": {"provider": self.name, "model": settings.gemini_vision_model},
            "profile": parsed or {},
            "raw_text": raw_text,
        }

        return ObservedProfileResult(
            profile=profile,
            provider=self.name,
            model=settings.gemini_vision_model,
            raw_text=raw_text,
        )

    async def summarize_brand_language_for_copy(
        self,
        reference_images: list[Path],
        brief_text: str,
    ) -> str:
        """
        v0: extract brand-language cues (tone, phrasing, claims, CTA patterns) from images.
        This helps copy generation stay aligned with existing creative language.
        """
        prompt = (
            "You are analyzing existing ad creatives to extract brand language.\n"
            "Return a concise bullet list (plain text) with:\n"
            "- Brand voice/tone\n"
            "- Common headline patterns\n"
            "- Common CTAs\n"
            "- Any explicit claims/offer details seen (numbers, %s, rates)\n"
            "- Words/phrases that look important to keep\n"
            "- Things to avoid (if implied)\n"
            f"\nContext:\n{brief_text}\n"
        )

        contents: list[Any] = [prompt]
        for p in reference_images[:8]:
            try:
                contents.append(Image.open(p))
            except Exception:
                continue

        resp = self.client.models.generate_content(
            model=settings.gemini_vision_model,
            contents=contents,
        )
        return getattr(resp, "text", "") or ""

    async def generate(
        self,
        prompt: str,
        reference_images: list[Path],
        n: int,
        aspect_ratio: str,
    ) -> list[GeneratedImage]:
        """
        v0 supports two paths depending on model family:
        - Imagen models: `models.generate_images(...)` (text-to-image)
        - Gemini image preview models: `models.generate_content(...)` with image response modality
        """
        from google.genai import types  # type: ignore

        # Keep aspect ratios configurable; providers have different accepted strings.
        ratio_map = {"1:1": "1:1", "4:5": "3:4", "9:16": "9:16"}
        provider_ratio = ratio_map.get(aspect_ratio, "1:1")

        # v0: do not attempt complex style compilation; just append strong constraints.
        enriched = f"{prompt}\nNo text. No logos. No watermarks."

        model = settings.gemini_image_model
        out: list[GeneratedImage] = []

        if model.startswith("imagen-"):
            resp = self.client.models.generate_images(
                model=model,
                prompt=enriched,
                config=types.GenerateImagesConfig(
                    number_of_images=n,
                    aspect_ratio=provider_ratio,
                ),
            )
            for gi in getattr(resp, "generated_images", []) or []:
                img_bytes = getattr(getattr(gi, "image", None), "image_bytes", None)
                if not img_bytes:
                    continue
                image = Image.open(BytesIO(img_bytes))
                out.append(
                    GeneratedImage(
                        image=image,
                        prompt_used=enriched,
                        provider=self.name,
                        model=model,
                        seed=None,
                        raw_metadata={},
                    )
                )
            return out

        # Gemini image-preview style models: use generate_content. Many models return
        # only one image per call, so loop until we hit n (or the model refuses).
        for _ in range(max(1, n)):
            contents = [f"{enriched}\nDesired aspect ratio: {aspect_ratio}."]
            for p in reference_images[:8]:
                try:
                    contents.append(Image.open(p))
                except Exception:
                    continue

            resp = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(response_modalities=["image", "text"]),
            )

            extracted = _extract_images_from_generate_content(resp)
            for img, meta in extracted:
                out.append(
                    GeneratedImage(
                        image=img,
                        prompt_used=enriched,
                        provider=self.name,
                        model=model,
                        seed=None,
                        raw_metadata=meta,
                    )
                )
                if len(out) >= n:
                    return out

            # Stop early if we didn't get anything back this attempt.
            if not extracted:
                break

        return out


def _strip_code_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # Remove leading fence line
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        # Remove trailing fence
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _parse_jsonish(raw_text: str | None) -> dict[str, Any] | None:
    if not raw_text:
        return None
    s = _strip_code_fences(raw_text)
    try:
        return json.loads(s)
    except Exception:
        return None


def _extract_images_from_generate_content(resp: Any) -> list[tuple[Image.Image, dict[str, Any]]]:
    out: list[tuple[Image.Image, dict[str, Any]]] = []
    for cand in getattr(resp, "candidates", []) or []:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if not inline:
                continue
            mime = getattr(inline, "mime_type", None) or ""
            data = getattr(inline, "data", None)
            if not data:
                continue
            if mime and not mime.startswith("image/"):
                continue
            try:
                img = Image.open(BytesIO(data))
            except Exception:
                continue
            out.append((img, {"mime_type": mime}))
    return out
