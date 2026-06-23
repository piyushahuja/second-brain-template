"""
Admin API for bot configuration.

GET  /api/config/providers  → {"default": "claude", "fallback": null}
POST /api/config/providers  → {"default": "claude", "fallback": "codex"}
"""

import subprocess
from pathlib import Path

import yaml
from flask import Blueprint, jsonify, request

from admin.auth import require_admin

bp = Blueprint("config", __name__)

ROOT        = Path(__file__).parent.parent.parent
CONFIG_FILE = ROOT / "bot" / "config.yaml"
VALID_PROVIDERS = {"claude", "codex"}


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


@bp.route("/config/providers")
@require_admin
def get_provider_config():
    cfg  = _load()
    prov = cfg.get("providers", {})
    return jsonify({
        "default":  prov.get("default", "claude"),
        "fallback": prov.get("fallback"),
    })


@bp.route("/config/providers", methods=["POST"])
@require_admin
def set_provider_config():
    body     = request.get_json(force=True)
    default  = body.get("default", "claude")
    fallback = body.get("fallback") or None

    if default not in VALID_PROVIDERS:
        return jsonify({"status": "error", "detail": f"Unknown provider: {default}"}), 400
    if fallback and fallback not in VALID_PROVIDERS:
        return jsonify({"status": "error", "detail": f"Unknown fallback: {fallback}"}), 400
    if fallback == default:
        return jsonify({"status": "error", "detail": "Fallback must differ from default"}), 400

    cfg = _load()
    cfg.setdefault("providers", {})["default"]  = default
    cfg["providers"]["fallback"] = fallback
    _save(cfg)

    subprocess.run(
        ["systemctl", "--user", "restart", "second-brain-bot"],
        capture_output=True, timeout=10,
    )
    return jsonify({"status": "ok", "default": default, "fallback": fallback})
