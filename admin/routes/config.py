"""
Admin API for bot configuration.

GET  /api/config/orchestrators  → {"default": "claude", "fallback": null}
POST /api/config/orchestrators  → {"default": "claude", "fallback": "codex"}
"""

import subprocess
from pathlib import Path

import yaml
from flask import Blueprint, jsonify, request

from admin.auth import require_admin

bp = Blueprint("config", __name__)

ROOT        = Path(__file__).parent.parent.parent
CONFIG_FILE = ROOT / "bot" / "config.yaml"
VALID_ORCHESTRATORS = {"claude", "codex"}


def _load() -> dict:
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def _save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


@bp.route("/config/orchestrators")
@require_admin
def get_orchestrator_config():
    cfg  = _load()
    orch = cfg.get("orchestrators", {})
    return jsonify({
        "default":  orch.get("default", "claude"),
        "fallback": orch.get("fallback"),
    })


@bp.route("/config/orchestrators", methods=["POST"])
@require_admin
def set_orchestrator_config():
    body     = request.get_json(force=True)
    default  = body.get("default", "claude")
    fallback = body.get("fallback") or None

    if default not in VALID_ORCHESTRATORS:
        return jsonify({"status": "error", "detail": f"Unknown orchestrator: {default}"}), 400
    if fallback and fallback not in VALID_ORCHESTRATORS:
        return jsonify({"status": "error", "detail": f"Unknown fallback: {fallback}"}), 400
    if fallback == default:
        return jsonify({"status": "error", "detail": "Fallback must differ from default"}), 400

    cfg = _load()
    cfg.setdefault("orchestrators", {})["default"]  = default
    cfg["orchestrators"]["fallback"] = fallback
    _save(cfg)

    subprocess.run(
        ["systemctl", "--user", "restart", "second-brain-bot"],
        capture_output=True, timeout=10,
    )
    return jsonify({"status": "ok", "default": default, "fallback": fallback})
