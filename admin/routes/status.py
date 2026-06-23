"""
/api/status — System health and service status
"""

import subprocess
from flask import Blueprint, jsonify

bp = Blueprint('status', __name__)


@bp.route('/status')
def status():
    """Return system health: services, uptime, disk, memory."""
    # Bot service status
    bot_status = _check_service('second-brain-bot')

    # Disk usage
    disk = _disk_usage()

    return jsonify({
        'bot': bot_status,
        'disk': disk,
    })


def _check_service(name: str) -> dict:
    """Check if a systemd user service is running."""
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', name],
            capture_output=True, text=True, timeout=5
        )
        return {
            'name': name,
            'active': result.stdout.strip() == 'active',
            'status': result.stdout.strip()
        }
    except Exception as e:
        return {'name': name, 'active': False, 'status': str(e)}


def _disk_usage() -> dict:
    """Get disk usage for workspace."""
    try:
        result = subprocess.run(
            ['df', '-h', '.'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            return {
                'total': parts[1],
                'used': parts[2],
                'available': parts[3],
                'percent': parts[4]
            }
    except Exception:
        pass
    return {}
