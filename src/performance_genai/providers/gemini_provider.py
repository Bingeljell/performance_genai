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

        raw_text: str | None = None
        try:
            raw_text = resp.text
        except Exception:
            raw_text = None

        profile: dict[str, Any] = {}
        if raw_text:
            try:
                profile = json.loads(raw_text)
            except Exception:
                profile = {"_raw_text": raw_text}

        return ObservedProfileResult(
            profile=profile,
            provider=self.name,
            model=settings.gemini_vision_model,
            raw_text=raw_text,
        )

    async def generate(
        self,
        prompt: str,
        reference_images: list[Path],
        n: int,
        aspect_ratio: str,
    ) -> list[GeneratedImage]:
        from google.genai import types  # type: ignore

        # Keep aspect ratios configurable; providers have different accepted strings.
        ratio_map = {"1:1": "1:1", "4:5": "3:4", "9:16": "9:16"}
        provider_ratio = ratio_map.get(aspect_ratio, "1:1")

        # v0: do not attempt complex style compilation; just append strong constraints.
        enriched = f"{prompt}\nNo text. No logos. No watermarks. Keep it photoreal unless told otherwise."

        out: list[GeneratedImage] = []
        resp = self.client.models.generate_image(
            model=settings.gemini_image_model,
            prompt=enriched,
            config=types.GenerateImageConfig(
                number_of_images=n,
                aspect_ratio=provider_ratio,
            ),
        )

        # Response shape varies; handle common cases.
        generated = getattr(resp, "generated_images", None) or []
        for gi in generated:
            img_bytes = gi.image.image_bytes
            image = Image.open(BytesIO(img_bytes))
            out.append(
                GeneratedImage(
                    image=image,
                    prompt_used=enriched,
                    provider=self.name,
                    model=settings.gemini_image_model,
                    seed=None,
                    raw_metadata={},
                )
            )

        return out

