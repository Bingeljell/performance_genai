from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image


@dataclass(frozen=True)
class GeneratedImage:
    image: Image.Image
    prompt_used: str
    provider: str
    model: str
    seed: int | None
    raw_metadata: dict[str, Any]


@dataclass(frozen=True)
class ObservedProfileResult:
    # Keep this intentionally loose for v0; store raw provider response too.
    profile: dict[str, Any]
    provider: str
    model: str
    raw_text: str | None


class ImageProvider(Protocol):
    name: str

    async def generate(
        self,
        prompt: str,
        reference_images: list[Path],
        n: int,
        aspect_ratio: str,
    ) -> list[GeneratedImage]: ...


class VisionProvider(Protocol):
    name: str

    async def propose_observed_profile(
        self,
        reference_images: list[Path],
        brief_text: str,
    ) -> ObservedProfileResult: ...

