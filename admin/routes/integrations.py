import os
import subprocess
import threading
import queue
import uuid
from flask import Blueprint, jsonify, request
from admin.auth import require_admin
from admin.health import check_integration
from admin.manifest_loader import load_manifests, get_manifest
from admin.routes.env import write_env_key

bp = Blueprint('integrations', __name__)

_claude_auth_sessions: dict = {}


def _integration_dict(m, health):
    auth = m['auth']
    return {
        'name': m['name'],
        'label': m['label'],
        'description': m['description'],
        'icon': m.get('icon', ''),
        'auth_type': auth.get('type'),
        'env_key': auth.get('env_key', ''),
        'setup_url': auth.get('setup_url'),
        'setup_note': auth.get('setup_note'),
        'setup_guide': auth.get('setup_guide', ''),
        'status': health['status'],
        'detail': health['detail'],
        'pipelines': m.get('pipelines', []),
    }


@bp.route('/integrations')
@require_admin
def list_integrations():
    return jsonify([_integration_dict(m, check_integration(m)) for m in load_manifests()])


@bp.route('/integrations/<name>/health')
@require_admin
def integration_health(name):
    m = get_manifest(name)
    if not m:
        return jsonify({'error': 'not found'}), 404
    return jsonify(check_integration(m))


@bp.route('/integrations/<name>/configure', methods=['POST'])
@require_admin
def configure_integration(name):
    m = get_manifest(name)
    if not m:
        return jsonify({'error': 'not found'}), 404

    body = request.get_json(silent=True) or {}
    env_key = body.get('env_key', '').strip()
    value = body.get('value', '').strip()

    if not env_key or not value:
        return jsonify({'status': 'error', 'detail': 'env_key and value required'}), 400

    write_env_key(env_key, value)
    result = check_integration(m)

    # For setup_token integrations, also write the token into ~/.claude/.credentials.json
    # so that manual `claude` invocations use the same account without needing the env var.
    if m['auth'].get('type') == 'setup_token' and result.get('status') == 'ok':
        import json as _json
        import time as _time
        import pathlib as _pl
        creds_path = _pl.Path.home() / '.claude' / '.credentials.json'
        try:
            creds = _json.loads(creds_path.read_text()) if creds_path.exists() else {}
            creds['claudeAiOauth'] = {
                'accessToken': value,
                'refreshToken': None,
                'expiresAt': int((_time.time() + 365 * 86400) * 1000),
                'scopes': ['user:inference', 'user:profile', 'user:sessions:claude_code'],
            }
            creds_path.parent.mkdir(parents=True, exist_ok=True)
            creds_path.write_text(_json.dumps(creds))
        except Exception:
            pass  # non-fatal; env var auth still works

    # Restart dependent service if manifest requests it
    restart = m.get('restart_service')
    if restart and result.get('status') == 'ok':
        subprocess.run(['systemctl', '--user', 'restart', restart], capture_output=True, timeout=10)

    return jsonify(result)


@bp.route('/integrations/<name>/disconnect', methods=['POST'])
@require_admin
def disconnect_integration(name):
    m = get_manifest(name)
    if not m:
        return jsonify({'error': 'not found'}), 404

    auth = m['auth']
    for key in auth.get('token_env_keys', []):
        write_env_key(key, '')
        os.environ.pop(key, None)

    if name == 'google':
        write_env_key('GOOGLE_EMAIL', '')
        os.environ.pop('GOOGLE_EMAIL', None)

    return jsonify({'status': 'ok'})


@bp.route('/integrations/claude_code/auth/start', methods=['POST'])
@require_admin
def claude_auth_start():
    import time

    # Kill any existing session
    for s in list(_claude_auth_sessions.values()):
        try:
            s['proc'].kill()
        except Exception:
            pass
    _claude_auth_sessions.clear()

    try:
        proc = subprocess.Popen(
            ['claude', 'auth', 'login'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        return jsonify({'status': 'error', 'detail': 'claude CLI not found'}), 500

    # Read stdout in a thread — the prompt line has no newline so readline() would block on it
    line_q: queue.Queue = queue.Queue()

    def _reader():
        try:
            for line in proc.stdout:
                line_q.put(line)
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()

    url = None
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            line = line_q.get(timeout=1)
            if 'visit:' in line:
                url = line.strip().split('visit: ')[-1].strip()
                break
        except queue.Empty:
            if proc.poll() is not None:
                break

    if not url:
        proc.kill()
        return jsonify({'status': 'error', 'detail': 'Could not read auth URL from claude'}), 500

    sid = uuid.uuid4().hex[:12]
    _claude_auth_sessions[sid] = {'proc': proc}
    return jsonify({'status': 'ok', 'session_id': sid, 'url': url})


@bp.route('/integrations/claude_code/auth/submit', methods=['POST'])
@require_admin
def claude_auth_submit():
    import json as _json
    import pathlib as _pl

    body = request.get_json(silent=True) or {}
    sid = body.get('session_id', '').strip()
    code = body.get('code', '').strip()

    if not sid or not code:
        return jsonify({'status': 'error', 'detail': 'session_id and code required'}), 400

    s = _claude_auth_sessions.get(sid)
    if not s:
        return jsonify({'status': 'error', 'detail': 'No active session — click Login with Claude again'}), 400

    proc = s['proc']
    try:
        proc.stdin.write(code + '\n')
        proc.stdin.flush()
        proc.wait(timeout=20)
        _claude_auth_sessions.pop(sid, None)
    except subprocess.TimeoutExpired:
        proc.kill()
        _claude_auth_sessions.pop(sid, None)
        return jsonify({'status': 'error', 'detail': 'Auth timed out after 20s'}), 500
    except Exception as e:
        proc.kill()
        _claude_auth_sessions.pop(sid, None)
        return jsonify({'status': 'error', 'detail': str(e)}), 500

    if proc.returncode != 0:
        return jsonify({'status': 'error', 'detail': f'claude exited with code {proc.returncode}'}), 500

    # Sync new token from ~/.claude/.credentials.json → .env so the bot picks it up
    try:
        creds_path = _pl.Path.home() / '.claude' / '.credentials.json'
        creds = _json.loads(creds_path.read_text())
        new_token = creds.get('claudeAiOauth', {}).get('accessToken', '')
        if new_token:
            write_env_key('ANTHROPIC_AUTH_TOKEN', new_token)
            subprocess.run(['systemctl', '--user', 'restart', 'second-brain-bot'],
                           capture_output=True, timeout=10)
    except Exception:
        pass

    # Mark onboarding complete so interactive CLI doesn't prompt again
    try:
        claude_dir = _pl.Path.home() / '.claude'
        claude_dir.mkdir(parents=True, exist_ok=True)

        # Update settings.json with onboarding-complete markers
        settings_path = claude_dir / 'settings.json'
        settings = {}
        if settings_path.exists():
            try:
                settings = _json.loads(settings_path.read_text())
            except Exception:
                pass
        settings.setdefault('theme', 'dark')
        settings['hasCompletedOnboarding'] = True
        settings['skipDangerousModePermissionPrompt'] = True
        settings_path.write_text(_json.dumps(settings, indent=2))

        # Create settings.local.json if missing (indicates setup is complete)
        local_settings_path = claude_dir / 'settings.local.json'
        if not local_settings_path.exists():
            local_settings_path.write_text(_json.dumps({
                "permissions": {"allow": [], "deny": [], "ask": []}
            }, indent=2))
    except Exception:
        pass

    result = subprocess.run(['claude', 'auth', 'status'], capture_output=True, text=True, timeout=10)
    try:
        data = _json.loads(result.stdout.strip())
        return jsonify({'status': 'ok', 'email': data.get('email', ''), 'subscription': data.get('subscriptionType', '')})
    except Exception:
        return jsonify({'status': 'ok', 'email': ''})
