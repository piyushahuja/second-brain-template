"""
OpenRouter LLM client — text inference via OpenAI-compatible API.
Covers DeepSeek, GLM, and any other model OpenRouter hosts.

Usage:
    client = OpenRouterClient(model="deepseek/deepseek-chat")
    client = OpenRouterClient(model="thudm/glm-4-9b")
"""

import os
from pathlib import Path

from llm.base import LLMClient

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient(LLMClient):
    def __init__(self, model: str):
        self.model = model

    async def ask(self, prompt: str, files: list[Path] | None = None) -> str:
        import asyncio
        if files:
            raise NotImplementedError("OpenRouter client does not support file inputs")
        return await asyncio.get_running_loop().run_in_executor(None, self._ask_sync, prompt)

    def _ask_sync(self, prompt: str) -> str:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai not installed — run: pip install openai")

        client = OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or "(No response)"

    async def generate_image(self, prompt: str) -> bytes:
        raise NotImplementedError("Image generation not available via OpenRouter")
