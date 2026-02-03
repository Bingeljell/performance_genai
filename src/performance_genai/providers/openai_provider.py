from __future__ import annotations

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

