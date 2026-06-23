"""
/api/pipelines — Data pipeline management
"""

import json
from pathlib import Path
from flask import Blueprint, jsonify

bp = Blueprint('pipelines', __name__)

WORKSPACE = Path(__file__).parent.parent.parent
PIPELINES_DIR = WORKSPACE / 'pipelines'
INTEGRATIONS_DIR = WORKSPACE / 'integrations'


def discover_pipelines() -> list:
    """Discover all configured pipelines from integrations/."""
    pipelines = []

    # Check integrations directory for manifests
    if INTEGRATIONS_DIR.exists():
        for manifest_path in INTEGRATIONS_DIR.glob('*/manifest.json'):
            try:
                with open(manifest_path) as f:
                    cfg = json.load(f)
                cfg['path'] = str(manifest_path.parent)
                pipelines.append(cfg)
            except Exception:
                pass

    return pipelines


@bp.route('/pipelines')
def list_pipelines():
    """List all discovered pipelines with their status."""
    pipelines = discover_pipelines()

    result = []
    for cfg in pipelines:
        result.append({
            'name': cfg.get('name', 'unknown'),
            'label': cfg.get('label', cfg.get('name', 'Unknown')),
            'description': cfg.get('description', ''),
            'auth_type': cfg.get('auth', {}).get('type', 'none'),
            'configured': _is_configured(cfg),
            'last_sync': _last_sync(cfg.get('name', '')),
        })

    return jsonify(result)


@bp.route('/pipelines/run/<name>', methods=['POST'])
def run_pipeline(name: str):
    """Trigger a pipeline sync manually."""
    # TODO: Import and run pipeline sync module
    return jsonify({'status': 'not_implemented', 'name': name}), 501


def _is_configured(cfg: dict) -> bool:
    """Check if required credentials are present."""
    import os
    auth = cfg.get('auth', {})
    env_key = auth.get('env_key')
    if env_key:
        return bool(os.getenv(env_key))
    return True  # No auth required


def _last_sync(name: str) -> str | None:
    """Get last sync timestamp for a pipeline."""
    state_file = WORKSPACE / 'raw_sources' / name / '.last_sync'
    if state_file.exists():
        return state_file.read_text().strip()
    return None
