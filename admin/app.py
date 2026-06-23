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

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())


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
    resp = send_from_directory(Path(__file__).parent / 'templates', 'admin.html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.after_request
def no_cache_api(resp):
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/dashboards/<path:filename>')
def dashboard(filename):
    """Serve dashboard files."""
    return send_from_directory(ROOT / 'outputs' / 'dashboards', filename)




@app.route('/api/health')
def api_health():
    """Unauthenticated health check for monitoring."""
    return jsonify({'status': 'ok'})


# Register route blueprints
from admin.routes.status import bp as status_bp
from admin.routes.integrations import bp as integrations_bp
from admin.routes.oauth import bp as oauth_bp
from admin.routes.env import bp as env_bp
from admin.routes.crons import bp as crons_bp
from admin.routes.catalog import bp as catalog_bp
from admin.routes.syncthing import bp as syncthing_bp
from admin.routes.config import bp as config_bp

app.register_blueprint(status_bp,       url_prefix='/api')
app.register_blueprint(integrations_bp, url_prefix='/api')
app.register_blueprint(oauth_bp)
app.register_blueprint(env_bp,          url_prefix='/api')
app.register_blueprint(crons_bp,        url_prefix='/api')
app.register_blueprint(catalog_bp,      url_prefix='/api')
app.register_blueprint(syncthing_bp,    url_prefix='/api')
app.register_blueprint(config_bp,       url_prefix='/api')


if __name__ == '__main__':
    port = int(os.getenv('ADMIN_PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
