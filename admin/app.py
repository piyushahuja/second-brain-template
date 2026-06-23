#!/usr/bin/env python3
"""
Second Brain Admin Panel — minimal Flask scaffold.
Serves at http://VPS_IP:8080/admin (protected by ADMIN_TOKEN header).
"""

import os
import sys
from pathlib import Path
from functools import wraps

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / 'deploy' / '.env')
except ImportError:
    pass  # Rely on systemd EnvironmentFile

from flask import Flask, jsonify, request, send_from_directory, abort
import shutil
import subprocess

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())

WORKSPACE_ROOT = ROOT


def require_admin(f):
    """Decorator to require ADMIN_TOKEN header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_token = os.getenv('ADMIN_TOKEN', '')
        if not admin_token:
            return f(*args, **kwargs)  # No token configured = open access
        token = request.headers.get('X-Admin-Token') or request.args.get('token')
        if token != admin_token:
            abort(401)
        return f(*args, **kwargs)
    return decorated


# Make decorator available to blueprints
app.require_admin = require_admin


@app.route('/admin')
def admin_panel():
    """Serve the admin UI."""
    return send_from_directory(Path(__file__).parent / 'templates', 'admin.html')


@app.route('/dashboards/<path:filename>')
def dashboard(filename):
    """Serve dashboard files."""
    return send_from_directory(ROOT / 'outputs' / 'dashboards', filename)


@app.route('/api/status')
@require_admin
def api_status():
    """Return basic status info."""
    # Check bot service status
    bot_running = False
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', 'second-brain-bot'],
            capture_output=True, text=True, timeout=5
        )
        bot_running = result.stdout.strip() == 'active'
    except Exception:
        pass

    # Check admin service status
    admin_running = False
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', 'second-brain-admin'],
            capture_output=True, text=True, timeout=5
        )
        admin_running = result.stdout.strip() == 'active'
    except Exception:
        pass

    # Disk usage
    total, used, free = shutil.disk_usage(WORKSPACE_ROOT)

    # Memory (Linux only)
    mem_percent = None
    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {l.split(':')[0]: int(l.split()[1]) for l in lines[:3]}
        mem_percent = round((1 - mem['MemAvailable'] / mem['MemTotal']) * 100, 1)
    except Exception:
        pass

    return jsonify({
        'services': {
            'bot': bot_running,
            'admin': admin_running,
        },
        'disk': {
            'total_gb': round(total / 1e9, 1),
            'used_gb': round(used / 1e9, 1),
            'free_gb': round(free / 1e9, 1),
            'percent': round(used / total * 100, 1)
        },
        'memory_percent': mem_percent,
        'workspace': str(WORKSPACE_ROOT)
    })


@app.route('/api/health')
def api_health():
    """Unauthenticated health check for monitoring."""
    return jsonify({'status': 'ok'})


# Register route blueprints
from admin.routes.crons import bp as crons_bp
from admin.routes.env import bp as env_bp
from admin.routes.pipelines import bp as pipelines_bp

app.register_blueprint(crons_bp, url_prefix='/api')
app.register_blueprint(env_bp, url_prefix='/api')
app.register_blueprint(pipelines_bp, url_prefix='/api')


if __name__ == '__main__':
    port = int(os.getenv('ADMIN_PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
