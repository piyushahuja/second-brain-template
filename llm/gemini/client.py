"""
Gemini LLM client — multimodal input via gemini-2.0-flash,
image generation via Imagen 3.
"""

import mimetypes
import os
from pathlib import Path

from llm.base import LLMClient

GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
ASK_MODEL        = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
IMAGE_GEN_MODEL  = "imagen-3.0-generate-002"


def _get_client():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    try:
        from google import genai
        return genai.Client(api_key=GEMINI_API_KEY)
    except ImportError:
        raise RuntimeError("google-genai not installed — run: pip install google-genai")


class GeminiClient(LLMClient):
    async def ask(self, prompt: str, files: list[Path] | None = None) -> str:
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, self._ask_sync, prompt, files)

    def _ask_sync(self, prompt: str, files: list[Path] | None) -> str:
        from google.genai import types

        client = _get_client()
        parts = []

        for path in (files or []):
            mime, _ = mimetypes.guess_type(str(path))
            mime = mime or "application/octet-stream"
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type=mime))

        parts.append(prompt)

        response = client.models.generate_content(model=ASK_MODEL, contents=parts)
        return response.text or "(No response)"

    async def generate_image(self, prompt: str) -> bytes:
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, self._generate_image_sync, prompt)

    def _generate_image_sync(self, prompt: str) -> bytes:
        client = _get_client()
        response = client.models.generate_images(
            model=IMAGE_GEN_MODEL,
            prompt=prompt,
            config={"number_of_images": 1},
        )
        return response.generated_images[0].image.image_bytes
