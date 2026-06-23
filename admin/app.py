#!/usr/bin/env python3
"""
Second Brain Admin Panel — minimal Flask scaffold.
Serves at http://VPS_IP:8080/admin (protected by ADMIN_TOKEN header).
"""

import os
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Register route blueprints
from admin.routes.crons import bp as crons_bp
from admin.routes.env import bp as env_bp
from admin.routes.pipelines import bp as pipelines_bp

app.register_blueprint(crons_bp, url_prefix='/api')
app.register_blueprint(env_bp, url_prefix='/api')
app.register_blueprint(pipelines_bp, url_prefix='/api')

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def require_auth(f):
    """Decorator to require ADMIN_TOKEN header."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_TOKEN:
            return f(*args, **kwargs)  # No token configured = open access
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/admin")
@require_auth
def admin_page():
    """Serve the admin UI."""
    return render_template("admin.html")


@app.route("/api/status")
@require_auth
def api_status():
    """Return basic status info."""
    import subprocess
    import shutil

    # Check bot service status
    bot_running = False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "second-brain-bot"],
            capture_output=True, text=True, timeout=5
        )
        bot_running = result.stdout.strip() == "active"
    except Exception:
        pass

    # Disk usage
    total, used, free = shutil.disk_usage(WORKSPACE_ROOT)

    # Memory (Linux only)
    mem_percent = None
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {l.split(":")[0]: int(l.split()[1]) for l in lines[:3]}
        mem_percent = round((1 - mem["MemAvailable"] / mem["MemTotal"]) * 100, 1)
    except Exception:
        pass

    return jsonify({
        "bot_running": bot_running,
        "disk": {
            "total_gb": round(total / 1e9, 1),
            "used_gb": round(used / 1e9, 1),
            "free_gb": round(free / 1e9, 1),
            "percent": round(used / total * 100, 1)
        },
        "memory_percent": mem_percent,
        "workspace": WORKSPACE_ROOT
    })


@app.route("/api/health")
def api_health():
    """Unauthenticated health check for monitoring."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("ADMIN_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
