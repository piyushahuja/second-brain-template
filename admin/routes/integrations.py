import logging
import os
import subprocess
import threading
import queue
import uuid

log = logging.getLogger("second-brain-admin")
from flask import Blueprint, jsonify, request
from admin.auth import require_admin
from admin.health import check_integration
from admin.manifest_loader import load_manifests, get_manifest
from admin.routes.env import write_env_key

bp = Blueprint('integrations', __name__)

_claude_auth_sessions: dict = {}
_codex_auth_sessions:  dict = {}


def _integration_dict(m, health):
    auth = m['auth']
    return {
        'name': m['name'],
        'label': m['label'],
        'description': m['description'],
        'icon': m.get('icon', ''),
        'category': m.get('category', 'integration'),
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
        settings['tui'] = 'fullscreen'
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


# ---------------------------------------------------------------------------
# Codex device-auth flow
# ---------------------------------------------------------------------------

@bp.route('/integrations/codex/auth/start', methods=['POST'])
@require_admin
def codex_auth_start():
    import re, time, pty, os as _os, select as _select

    for s in list(_codex_auth_sessions.values()):
        try:
            s['proc'].kill()
        except Exception:
            pass
        try:
            import os as _os2; _os2.close(s['master_fd'])
        except Exception:
            pass
    _codex_auth_sessions.clear()

    codex_path = os.environ.get('CODEX_PATH', 'codex')

    # Codex is a Node.js symlink in nvm's bin dir; realpath() would resolve it into
    # lib/node_modules/.../bin which has no `node`. Use dirname(codex_path) to stay
    # in the nvm bin dir where both codex and node live.
    codex_dir = _os.path.dirname(codex_path)
    env = {**os.environ, "PATH": codex_dir + ":" + os.environ.get("PATH", "")}

    # Use a PTY so Codex line-flushes its output (pipe buffering would stall reads)
    try:
        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            [codex_path, 'login', '--device-auth'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
        _os.close(slave_fd)
    except FileNotFoundError:
        return jsonify({'status': 'error', 'detail': 'codex CLI not found'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 500

    ansi = re.compile(rb'\x1b\[[0-9;]*[mGKABCDEFHJK]')
    url = code = None
    raw_buf = b""
    deadline = time.time() + 12

    while time.time() < deadline and not (url and code):
        try:
            r, _, _ = _select.select([master_fd], [], [], 1.0)
            if r:
                chunk = _os.read(master_fd, 4096)
                raw_buf += chunk
                for raw_line in raw_buf.split(b'\n'):
                    line = ansi.sub(b'', raw_line).decode('utf-8', errors='replace').strip()
                    if 'https://' in line:
                        for part in line.split():
                            if part.startswith('https://'):
                                url = part
                    elif re.match(r'^[A-Z0-9]+-[A-Z0-9]+$', line):
                        code = line
        except OSError:
            break
        if proc.poll() is not None:
            break

    if not url or not code:
        try:
            _os.close(master_fd)
        except OSError:
            pass
        proc.kill()
        log.error("codex auth failed — url=%r code=%r buf=%r pid=%s rc=%s",
                  url, code, raw_buf[:500], proc.pid, proc.poll())
        detail = ansi.sub(b'', raw_buf[:300]).decode('utf-8', errors='replace').strip() or 'Could not read auth URL from codex'
        return jsonify({'status': 'error', 'detail': detail}), 500

    # Drain master_fd in a background thread so the PTY buffer never fills and blocks
    # codex. We also capture the tail of output for error diagnosis.
    tail: list[bytes] = []

    def _drain():
        import select as _sel, os as _o
        while True:
            try:
                r, _, _ = _sel.select([master_fd], [], [], 1.0)
                if r:
                    chunk = _o.read(master_fd, 4096)
                    tail.append(chunk)
                    if len(tail) > 20:
                        tail.pop(0)
            except OSError:
                break
            if proc.poll() is not None:
                break

    threading.Thread(target=_drain, daemon=True).start()

    sid = uuid.uuid4().hex[:12]
    _codex_auth_sessions[sid] = {'proc': proc, 'master_fd': master_fd, 'tail': tail}
    return jsonify({'status': 'ok', 'session_id': sid, 'url': url, 'code': code})


@bp.route('/integrations/codex/auth/poll', methods=['POST'])
@require_admin
def codex_auth_poll():
    body = request.get_json(silent=True) or {}
    sid  = body.get('session_id', '').strip()

    if not sid:
        return jsonify({'status': 'error', 'detail': 'session_id required'}), 400

    s = _codex_auth_sessions.get(sid)
    if not s:
        return jsonify({'status': 'error', 'detail': 'No active session — click Login again'}), 400

    ret = s['proc'].poll()

    if ret is None:
        return jsonify({'status': 'pending'})

    _codex_auth_sessions.pop(sid, None)
    try:
        import os as _os3; _os3.close(s['master_fd'])
    except Exception:
        pass

    if ret != 0:
        import re as _re
        ansi = _re.compile(rb'\x1b\[[0-9;]*[mGKABCDEFHJK]')
        raw = b''.join(s.get('tail', []))
        detail = ansi.sub(b'', raw).decode('utf-8', errors='replace').strip()
        detail = detail or f'codex login exited with code {ret}'
        return jsonify({'status': 'error', 'detail': detail[-300:]})

    subprocess.run(['systemctl', '--user', 'restart', 'second-brain-bot'],
                   capture_output=True, timeout=10)
    return jsonify({'status': 'ok'})
