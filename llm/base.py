"""
LLM client interface — stateless inference, multimodal input, image generation.

Contrast with bot/orchestrator.py (agentic CLIs that run tool loops).
These clients are called directly by the bot for single-shot tasks
(media ingestion, image generation) or by orchestrators as shell tools.
"""

from pathlib import Path


class LLMClient:
    async def ask(self, prompt: str, files: list[Path] | None = None) -> str:
        """Send a text prompt (optionally with media files) and return a text response."""
        raise NotImplementedError

    async def generate_image(self, prompt: str) -> bytes:
        """Generate an image and return raw bytes (PNG)."""
        raise NotImplementedError
