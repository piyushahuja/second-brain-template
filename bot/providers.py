"""
Provider abstraction layer — Claude Code CLI and Codex CLI.

Each provider implements query() with the same signature.
The bot calls the interface; concrete classes handle CLI details.

Codex CLI usage (non-interactive):
  codex exec "prompt" --ask-for-approval never --sandbox workspace-write
  Auth: CODEX_API_KEY or OPENAI_API_KEY
  Sessions: Codex tracks by recency; resume via `codex exec resume --last "prompt"`
  Output: final message on stdout, progress on stderr
"""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("second-brain-bot.providers")

WORKSPACE_ROOT = Path(__file__).parent.parent
CLAUDE_PATH    = os.environ.get("CLAUDE_PATH", "claude")
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "120"))
CODEX_PATH     = os.environ.get("CODEX_PATH", "codex")
CODEX_TIMEOUT  = int(os.environ.get("CODEX_TIMEOUT", "120"))


class ProviderUnavailable(Exception):
    """Provider is down, unauthenticated, or not installed."""


class Provider:
    async def query(
        self, prompt: str, session_id: str | None, system_prompt: str
    ) -> tuple[str, str | None]:
        """
        Send a prompt and return (response_text, new_session_id).
        new_session_id is None for providers without session resumption.
        Raises ProviderUnavailable on auth/connectivity failures.
        Raises RuntimeError on other failures.
        """
        raise NotImplementedError

    def is_session_invalid(self, error: str) -> bool:
        """True if the error indicates a stale session that should be cleared."""
        return False


class ClaudeProvider(Provider):
    async def query(
        self, prompt: str, session_id: str | None, system_prompt: str
    ) -> tuple[str, str | None]:
        cmd = [
            CLAUDE_PATH,
            "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]
        if session_id:
            cmd.extend(["--resume", session_id])
        else:
            cmd.extend(["--system-prompt", system_prompt])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=WORKSPACE_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "LANG": "en_US.UTF-8"},
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=CLAUDE_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise ProviderUnavailable(f"Claude timed out after {CLAUDE_TIMEOUT}s")

            if proc.returncode != 0:
                err = stderr.decode().strip()
                if any(x in err.lower() for x in ("auth", "unauthorized")):
                    raise ProviderUnavailable(f"Claude auth error: {err[:200]}")
                raise RuntimeError(err[:300])

            try:
                data = json.loads(stdout.decode())
                return data.get("result", "(No response)"), data.get("session_id")
            except json.JSONDecodeError:
                return stdout.decode().strip() or "(No response)", session_id

        except FileNotFoundError:
            raise ProviderUnavailable(f"Claude CLI not found at: {CLAUDE_PATH}")

    def is_session_invalid(self, error: str) -> bool:
        return "session" in error.lower() and "not found" in error.lower()


class CodexProvider(Provider):
    async def query(
        self, prompt: str, session_id: str | None, system_prompt: str
    ) -> tuple[str, str | None]:
        has_key = bool(os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"))
        if not has_key:
            raise ProviderUnavailable("CODEX_API_KEY or OPENAI_API_KEY not set")

        # Codex has no --system-prompt flag; prepend context to the prompt
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        if session_id == "codex-active":
            # Resume last Codex session (tracks by recency, not by ID)
            cmd = [
                CODEX_PATH, "exec", "resume", "--last", full_prompt,
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        else:
            cmd = [
                CODEX_PATH, "exec", full_prompt,
                "--dangerously-bypass-approvals-and-sandbox",
            ]

        # codex is a symlink in nvm's bin dir; realpath() resolves it to node_modules/
        # which has no `node`. Use dirname(CODEX_PATH) to stay in the bin dir.
        codex_dir = os.path.dirname(CODEX_PATH)
        env = {**os.environ, "LANG": "en_US.UTF-8",
               "PATH": codex_dir + ":" + os.environ.get("PATH", "")}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=WORKSPACE_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=CODEX_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise ProviderUnavailable(f"Codex timed out after {CODEX_TIMEOUT}s")

            if proc.returncode != 0:
                err = stderr.decode().strip()
                if any(x in err.lower() for x in ("auth", "unauthorized", "api key", "invalid key")):
                    raise ProviderUnavailable(f"Codex auth error: {err[:200]}")
                raise RuntimeError(err[:300])

            response = stdout.decode().strip() or "(No response)"
            # Sentinel session_id — Codex resumes by recency, not by explicit ID
            return response, "codex-active"

        except FileNotFoundError:
            raise ProviderUnavailable(
                f"Codex CLI not found at: {CODEX_PATH}. "
                "Install with: npm install -g @openai/codex"
            )


def create_provider(name: str) -> Provider:
    if name == "claude":
        return ClaudeProvider()
    if name == "codex":
        return CodexProvider()
    raise ValueError(f"Unknown provider: {name!r}. Valid options: claude, codex")
