#!/usr/bin/env python3
"""
CLI wrapper — generate an image and write it to a file.
Called by orchestrators as a shell tool.

Usage:
    python imagine.py "a sunset over mountains" --out /tmp/output.png
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--out", type=Path, required=True, help="Output PNG path")
    parser.add_argument("--llm", default="gemini", choices=["gemini"])
    args = parser.parse_args()

    if args.llm == "gemini":
        from llm.gemini.client import GeminiClient
        client = GeminiClient()
    else:
        raise SystemExit(f"Image generation not supported for llm={args.llm}")

    image_bytes = asyncio.run(client.generate_image(args.prompt))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(image_bytes)
    print(args.out)  # orchestrator reads this path to send the file


if __name__ == "__main__":
    main()
