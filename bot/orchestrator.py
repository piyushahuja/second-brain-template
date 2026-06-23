"""
Orchestrator abstraction layer — Claude Code CLI and Codex CLI.

Orchestrators run agentic loops: they use tools, manage sessions, and
coordinate multi-step tasks. The bot delegates prompts to one; concrete
classes handle CLI invocation details.

Contrast with llm/ (stateless inference clients used by orchestrators
or called directly for single-shot tasks like multimodal ingestion).
"""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("second-brain-bot.orchestrator")

WORKSPACE_ROOT  = Path(__file__).parent.parent
CLAUDE_PATH     = os.environ.get("CLAUDE_PATH", "claude")
CLAUDE_TIMEOUT  = int(os.environ.get("CLAUDE_TIMEOUT", "120"))
CODEX_PATH      = os.environ.get("CODEX_PATH", "codex")
CODEX_TIMEOUT   = int(os.environ.get("CODEX_TIMEOUT", "120"))


class OrchestratorUnavailable(Exception):
    """Orchestrator is down, unauthenticated, or not installed."""


class Orchestrator:
    async def query(
        self, prompt: str, session_id: str | None, system_prompt: str
    ) -> tuple[str, str | None]:
        """
        Send a prompt and return (response_text, new_session_id).
        new_session_id is None for orchestrators without session resumption.
        Raises OrchestratorUnavailable on auth/connectivity failures.
        Raises RuntimeError on other failures.
        """
        raise NotImplementedError

    def is_session_invalid(self, error: str) -> bool:
        """True if the error indicates a stale session that should be cleared."""
        return False


class ClaudeOrchestrator(Orchestrator):
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
                raise OrchestratorUnavailable(f"Claude timed out after {CLAUDE_TIMEOUT}s")

            if proc.returncode != 0:
                err = stderr.decode().strip()
                if any(x in err.lower() for x in ("auth", "unauthorized")):
                    raise OrchestratorUnavailable(f"Claude auth error: {err[:200]}")
                raise RuntimeError(err[:300])

            try:
                data = json.loads(stdout.decode())
                return data.get("result", "(No response)"), data.get("session_id")
            except json.JSONDecodeError:
                return stdout.decode().strip() or "(No response)", session_id

        except FileNotFoundError:
            raise OrchestratorUnavailable(f"Claude CLI not found at: {CLAUDE_PATH}")

    def is_session_invalid(self, error: str) -> bool:
        return "session" in error.lower() and "not found" in error.lower()


class CodexOrchestrator(Orchestrator):
    async def query(
        self, prompt: str, session_id: str | None, system_prompt: str
    ) -> tuple[str, str | None]:
        # Codex has no --system-prompt flag; prepend context to the prompt
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        if session_id == "codex-active":
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
                raise OrchestratorUnavailable(f"Codex timed out after {CODEX_TIMEOUT}s")

            if proc.returncode != 0:
                err = stderr.decode().strip()
                if any(x in err.lower() for x in ("auth", "unauthorized", "api key", "invalid key", "not logged in", "login")):
                    raise OrchestratorUnavailable(f"Codex auth error: {err[:200]}")
                raise RuntimeError(err[:300])

            response = stdout.decode().strip() or "(No response)"
            return response, "codex-active"

        except FileNotFoundError:
            raise OrchestratorUnavailable(
                f"Codex CLI not found at: {CODEX_PATH}. "
                "Install with: npm install -g @openai/codex"
            )


def create_orchestrator(name: str) -> Orchestrator:
    if name == "claude":
        return ClaudeOrchestrator()
    if name == "codex":
        return CodexOrchestrator()
    raise ValueError(f"Unknown orchestrator: {name!r}. Valid options: claude, codex")
