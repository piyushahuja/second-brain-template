"""
/api/env — Environment variable management
"""

import os
import re
from pathlib import Path
from flask import Blueprint, jsonify, request

bp = Blueprint('env', __name__)

WORKSPACE = Path(__file__).parent.parent.parent
ENV_PATH = WORKSPACE / 'deploy' / '.env'

SECRET_PATTERNS = re.compile(r'TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|OAUTH', re.I)


def read_env() -> dict:
    """Read .env file into dict."""
    if not ENV_PATH.exists():
        return {}
    pairs = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            pairs[k.strip()] = v.strip()
    return pairs


def write_env(pairs: dict):
    """Write dict to .env file."""
    lines = [f'{k}={v}' for k, v in pairs.items()]
    ENV_PATH.write_text('\n'.join(lines) + '\n')


def write_env_key(key: str, value: str):
    """Write or update a single key in deploy/.env. Also sets os.environ."""
    pairs = read_env()
    pairs[key] = value
    write_env(pairs)
    os.environ[key] = value


@bp.route('/env')
def get_env():
    """Return all env vars (secrets masked)."""
    pairs = read_env()
    result = {}
    for k, v in pairs.items():
        is_secret = bool(SECRET_PATTERNS.search(k))
        result[k] = {
            'value': '********' if is_secret else v,
            'secret': is_secret
        }
    return jsonify(result)


@bp.route('/env/reveal/<key>', methods=['POST'])
def reveal_env(key: str):
    """Return plaintext value of a specific key."""
    pairs = read_env()
    if key not in pairs:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'key': key, 'value': pairs[key]})


@bp.route('/env', methods=['POST'])
def update_env():
    """Update a single env var. Body: {key, value}"""
    body = request.json
    if not body or 'key' not in body or 'value' not in body:
        return jsonify({'error': 'missing key or value'}), 400

    pairs = read_env()
    pairs[body['key']] = body['value']
    write_env(pairs)

    return jsonify({'status': 'saved', 'key': body['key']})
