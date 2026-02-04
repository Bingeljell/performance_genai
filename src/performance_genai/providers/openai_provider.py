from __future__ import annotations

import json
import re

from performance_genai.config import settings


class OpenAITextProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        from openai import OpenAI  # type: ignore

        self.client = OpenAI(api_key=api_key)

    async def generate_copy(self, brief_text: str, count: int = 12) -> list[str]:
        """
        v0: generate headlines only. Keep output as a simple string list.
        """
        prompt = (
            "Generate performance ad headlines.\n"
            f"Return exactly {count} lines, each a distinct headline, no numbering.\n"
            f"Context:\n{brief_text}\n"
        )

        # The Responses API is the forward path; keep it minimal.
        resp = self.client.responses.create(
            model=settings.openai_text_model,
            input=prompt,
        )

        text = ""
        try:
            text = resp.output_text
        except Exception:
            # Fallback: best-effort
            text = str(resp)

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return lines[:count]

    async def generate_copy_sets(self, brief_text: str, count: int = 8) -> list[dict[str, str]]:
        """
        v0: generate headline + subhead + CTA as "copy sets" for the editor.
        """
        prompt = (
            "You are writing performance ad copy.\n"
            f"Return EXACTLY {count} copy sets as a JSON array, and nothing else.\n"
            "Each item must be an object with keys: headline, subhead, cta.\n"
            "- headline: <= 10 words\n"
            "- subhead: <= 18 words\n"
            "- cta: 2-4 words, Title Case\n"
            "No numbering, no markdown, no commentary, no extra keys.\n"
            f"\nContext:\n{brief_text}\n"
        )

        resp = self.client.responses.create(
            model=settings.openai_text_model,
            input=prompt,
        )

        text = ""
        try:
            text = resp.output_text
        except Exception:
            text = str(resp)

        raw = text.strip()

        # Best-effort JSON extraction (handles accidental pre/post text).
        m = re.search(r"```(?:json)?\\s*(\\[.*?\\])\\s*```", raw, re.DOTALL | re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
        else:
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                raw = raw[start : end + 1].strip()

        try:
            data = json.loads(raw)
        except Exception:
            return []

        out: list[dict[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                h = str(item.get("headline", "")).strip()
                s = str(item.get("subhead", "")).strip()
                c = str(item.get("cta", "")).strip()
                if not (h and c):
                    continue
                out.append({"headline": h, "subhead": s, "cta": c})

        return out[:count]
