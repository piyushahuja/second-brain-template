"""
/api/crons — Cron job management
"""

import json
import subprocess
from pathlib import Path
from flask import Blueprint, jsonify, request

bp = Blueprint('crons', __name__)

WORKSPACE = Path(__file__).parent.parent.parent
REGISTRY = WORKSPACE / 'cron' / 'registry.json'


def load_registry() -> dict:
    """Load cron registry from JSON."""
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    return {'jobs': []}


def save_registry(data: dict):
    """Save cron registry to JSON."""
    REGISTRY.write_text(json.dumps(data, indent=2))


@bp.route('/crons')
def list_crons():
    """List all registered cron jobs."""
    registry = load_registry()
    return jsonify(registry.get('jobs', []))


@bp.route('/crons/run/<name>', methods=['POST'])
def run_cron(name: str):
    """Trigger a cron job manually."""
    registry = load_registry()
    job = next((j for j in registry.get('jobs', []) if j['name'] == name), None)

    if not job:
        return jsonify({'error': 'unknown cron'}), 404

    script = WORKSPACE / job['script']
    if not script.exists():
        return jsonify({'error': 'script not found'}), 404

    subprocess.Popen(['bash', str(script)], cwd=str(WORKSPACE))
    return jsonify({'status': 'triggered', 'name': name})


@bp.route('/crons/toggle/<name>', methods=['POST'])
def toggle_cron(name: str):
    """Enable or disable a cron job."""
    registry = load_registry()
    job = next((j for j in registry.get('jobs', []) if j['name'] == name), None)

    if not job:
        return jsonify({'error': 'unknown cron'}), 404

    job['enabled'] = not job.get('enabled', False)
    save_registry(registry)

    return jsonify({'status': 'toggled', 'name': name, 'enabled': job['enabled']})
