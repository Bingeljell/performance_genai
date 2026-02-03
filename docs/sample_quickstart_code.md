# Performance Creative Generation Tool - Sample Quickstart Code

This file collects illustrative snippets referenced from `docs/implementation_poa.md`.
These examples are intentionally incomplete/pseudocode and focus on shape and data flow
over production details (auth, retries, observability, error handling, etc.).

---

## Provider Interfaces

```python
# src/performance_genai/providers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class ProviderCapabilities:
    # Keep these in one place so the rest of the code stays provider-agnostic.
    max_reference_images: int
    supports_masks: bool
    supports_region_protection: bool  # "hard" protection semantics vs best-effort prompting


@dataclass
class GeneratedImage:
    image: Image.Image
    prompt_used: str
    provider: str
    model: str
    seed: int | None
    raw_metadata: dict[str, Any]


@dataclass
class ImageEditResult:
    image: Image.Image
    provider: str
    model: str
    raw_metadata: dict[str, Any]


class ImageProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        # Consider splitting refs conceptually:
        # - subject_images (product fidelity, Mode A)
        # - style_images (anchor refs for lighting/mood/style)
        reference_images: list[Path],
        negative_prompt: str | None = None,
        n: int = 1,
        aspect_ratio: str = "1:1",
        style_profile: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> list[GeneratedImage]: ...

    @abstractmethod
    async def edit(
        self,
        image: Path,
        instruction: str,
        mask: Path | None = None,
        reference_images: list[Path] | None = None,
        style_profile: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> ImageEditResult: ...
```

```python
# src/performance_genai/providers/llm_base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def propose_brand_profile(
        self,
        reference_images: list[Path],
        brief: dict,
    ) -> dict:
        # Return Observed Profile (values + confidence + evidence pointers).
        ...

    @abstractmethod
    async def generate_copy(
        self,
        brief: dict,
        enforced_profile: dict,
        count: dict,
    ) -> dict:
        # Return CopyPool (deduped + scored).
        ...

    @abstractmethod
    async def generate_style_directions(
        self,
        enforced_profile: dict,
        brief: dict,
        n_directions: int = 4,
    ) -> list[dict]:
        ...
```

---

## Gemini Provider (Illustrative)

```python
# src/performance_genai/providers/gemini_provider.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from google import genai
from google.genai import types

from performance_genai.providers.base import (
    GeneratedImage,
    ImageEditResult,
    ImageProvider,
    ProviderCapabilities,
)


class GeminiImageProvider(ImageProvider):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def capabilities(self) -> ProviderCapabilities:
        # Set these based on the concrete model chosen.
        return ProviderCapabilities(
            max_reference_images=14,
            supports_masks=True,
            supports_region_protection=False,
        )

    async def generate(
        self,
        prompt: str,
        reference_images: list[Path],
        negative_prompt: str | None = None,
        n: int = 1,
        aspect_ratio: str = "1:1",
        style_profile: dict | None = None,
        seed: int | None = None,
    ) -> list[GeneratedImage]:
        enriched_prompt = self._apply_style_profile(prompt, style_profile)

        ratio_map = {"1:1": "1:1", "4:5": "3:4", "9:16": "9:16"}

        results: list[GeneratedImage] = []
        for _ in range(n):
            response = self.client.models.generate_image(
                model="imagen-3.0-generate-002",
                prompt=enriched_prompt,
                config=types.GenerateImageConfig(
                    aspect_ratio=ratio_map.get(aspect_ratio, "1:1"),
                    number_of_images=1,
                ),
            )

            img_bytes = response.generated_images[0].image.image_bytes
            image = Image.open(BytesIO(img_bytes))
            results.append(
                GeneratedImage(
                    image=image,
                    prompt_used=enriched_prompt,
                    provider=self.name,
                    model="imagen-3.0-generate-002",
                    seed=seed,
                    raw_metadata={
                        "safety_ratings": getattr(response.generated_images[0], "safety_ratings", None)
                    },
                )
            )

        return results

    async def edit(
        self,
        image: Path,
        instruction: str,
        mask: Path | None = None,
        reference_images: list[Path] | None = None,
        style_profile: dict | None = None,
        seed: int | None = None,
    ) -> ImageEditResult:
        pil_image = Image.open(image)
        contents = [instruction, pil_image]
        if mask:
            contents.append(Image.open(mask))

        response = self.client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["image", "text"]),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                edited = Image.open(BytesIO(part.inline_data.data))
                return ImageEditResult(
                    image=edited,
                    provider=self.name,
                    model="gemini-2.0-flash-exp",
                    raw_metadata={},
                )

        raise ValueError("No image returned by provider")
```

---

## KV Generation (Provider-Agnostic)

```python
# src/performance_genai/generation/kv_generator.py
from __future__ import annotations

from performance_genai.providers.base import ImageProvider


class KVGenerator:
    def __init__(self, image_provider: ImageProvider):
        self.provider = image_provider

    async def explore_styles(self, enforced_profile: dict, brief: dict, assets: dict) -> list:
        style_variations = [
            "minimal clean composition, bright lighting",
            "detailed lifestyle scene, moody cinematic lighting",
            "premium studio shot, high contrast",
            "friendly casual setting, warm natural light",
        ]

        anchor_ids = enforced_profile.get("anchor_refs", [])
        anchor_paths = [assets[asset_id]["path"] for asset_id in anchor_ids]

        out = []
        for style in style_variations:
            prompt = f"{brief['product']} advertisement. {style}. No text, no logos."
            out.extend(
                await self.provider.generate(
                    prompt=prompt,
                    reference_images=anchor_paths,
                    n=3,
                    aspect_ratio="1:1",
                    style_profile=enforced_profile,
                )
            )
        return out
```

---

## Templates (Declarative)

```python
# src/performance_genai/assembly/templates.py
from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class TextBox(BaseModel):
    id: str
    x: float
    y: float
    width: float
    height: float
    align: Literal["left", "center", "right"]
    valign: Literal["top", "middle", "bottom"]
    font_size_max: int
    font_size_min: int
    color: str  # hex or "auto"
    shadow: bool = False


class SafeArea(BaseModel):
    x: float
    y: float
    width: float
    height: float
    purpose: str


class ScrimConfig(BaseModel):
    enabled: bool
    position: Literal["top", "bottom", "full", "behind_text"]
    opacity: float
    color: str


class TemplateVariant(BaseModel):
    variant_id: str
    description: str
    headline: TextBox
    primary: TextBox | None = None
    cta: TextBox
    disclaimer: TextBox | None = None
    scrim: ScrimConfig
    badge: bool = False
    badge_position: tuple[float, float] | None = None
    image_crop: tuple[float, float, float, float]


class MasterTemplate(BaseModel):
    template_id: str
    ratio: Literal["1:1", "4:5", "9:16"]
    canvas_size: tuple[int, int]
    platform: Literal["meta", "google", "generic"]
    safe_areas: list[SafeArea]
    variants: list[TemplateVariant]
```

---

## Pillow Compositor (Illustrative)

```python
# src/performance_genai/assembly/compositor_pillow.py
from __future__ import annotations

import textwrap
from PIL import Image, ImageDraw


class PillowAssemblyEngine:
    # Illustrative; in the plan this sits behind an AssemblyEngine interface.
    def render(self, render_spec: dict) -> Image.Image:
        raise NotImplementedError


class MasterCompositor:
    def build_master(self, kv_image: Image.Image, template: dict, variant: dict, copy: dict) -> Image.Image:
        canvas_size = tuple(template["canvas_size"])
        canvas = Image.new("RGB", canvas_size, (255, 255, 255))
        canvas.paste(kv_image.resize(canvas_size), (0, 0))

        draw = ImageDraw.Draw(canvas)
        # Apply scrim, draw text, CTA, etc.
        # (Production code should compute contrast and use deterministic rules.)
        return canvas

    def fit_text(self, draw: ImageDraw.ImageDraw, text: str, box_px: tuple[int, int, int, int]) -> str:
        # Simplified: wrap to an approximate width.
        x1, y1, x2, y2 = box_px
        w = max(1, x2 - x1)
        max_chars = max(1, int(w / 12))
        return textwrap.fill(text, width=max_chars)
```

---

## Master Builder + Manifest (Spec 10.5 / 12.3)

```python
# src/performance_genai/assembly/master_builder.py
from __future__ import annotations

import json
from pathlib import Path


class MasterBuilder:
    def __init__(self, compositor):
        self.compositor = compositor

    def build_masters(
        self,
        kv_image,
        template: dict,
        copy: dict,
        run_ctx: dict,
        brand_profile: dict,
        out_dir: Path,
        n_variants: int = 15,
    ) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        for variant in template["variants"][:n_variants]:
            img = self.compositor.build_master(kv_image=kv_image, template=template, variant=variant, copy=copy)

            out_path = out_dir / f"kv_{copy['kv_id']}_copy_{copy['copy_id']}_var_{variant['variant_id']}.png"
            img.save(out_path, quality=95)

            manifest = {
                "file": str(out_path),
                "ratio": template["ratio"],
                "template_id": template["template_id"],
                "variant_id": variant["variant_id"],
                "kv_id": copy["kv_id"],
                "copy_id": copy["copy_id"],
                "profile_version": brand_profile["version"],
                "input_hash": run_ctx["input_hash"],
                "source_hash": run_ctx.get("source_hash"),
                "reserved_zones": template.get("safe_areas", []),
                "quality": {
                    "contrast_scores": run_ctx.get("contrast_scores"),
                    "vaaj": run_ctx.get("vaaj"),
                },
            }

            out_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
            written.append(out_path)

        return written
```

