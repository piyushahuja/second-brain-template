#!/usr/bin/env python3
"""
CLI wrapper — send a prompt (optionally with files) to an LLM client.
Called by orchestrators as a shell tool, or directly for quick queries.

Usage:
    python query.py "describe this image" image.jpg
    python query.py --llm openrouter --model deepseek/deepseek-chat "explain X"
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from repo root or from llm/scripts/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--llm", default="gemini", choices=["gemini", "openrouter"])
    parser.add_argument("--model", default=None, help="Model override (openrouter only)")
    args = parser.parse_args()

    if args.llm == "gemini":
        from llm.gemini.client import GeminiClient
        client = GeminiClient()
    else:
        model = args.model or "deepseek/deepseek-chat"
        from llm.openrouter.client import OpenRouterClient
        client = OpenRouterClient(model=model)

    result = asyncio.run(client.ask(args.prompt, args.files or None))
    print(result)


if __name__ == "__main__":
    main()
