import os
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Optional: use psutil if available for better resource info
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def _resolve(value: str) -> str:
    """Replace $ENV_VAR tokens with actual env values."""
    if value and value.startswith('$'):
        return os.getenv(value[1:], '')
    return value


def check_integration(manifest: dict) -> dict:
    """Run the health check defined in a manifest. Returns {status, detail}."""
    auth = manifest.get('auth', {})
    health = manifest.get('health', {})
    auth_type = auth.get('type')

    # Check credentials are present first
    if auth_type == 'oauth2':
        client_id = os.getenv(auth.get('client_id_env', ''), '')
        client_secret = os.getenv(auth.get('client_secret_env', ''), '')
        if not client_id or not client_secret:
            return {'status': 'no_credentials', 'detail': 'OAuth credentials not configured'}
        token = os.getenv(auth.get('token_env_keys', [''])[0], '')
        if not token:
            return {'status': 'awaiting_auth', 'detail': 'Awaiting sign-in'}
    elif auth_type in ('personal_access_token', 'api_key'):
        token = os.getenv(auth.get('env_key', ''), '')
        if not token:
            return {'status': 'unconfigured', 'detail': 'Token not set'}
    elif auth_type == 'setup_token':
        return _check_setup_token(auth, health)
    elif auth_type == 'file_sync':
        return _check_file_sync(auth, health)
    elif auth_type == 'cli':
        pass  # health check determines status

    check_type = health.get('type')

    if check_type == 'api_call':
        return _check_api(health)
    elif check_type == 'command':
        return _check_command(health)

    return {'status': 'unknown', 'detail': 'No health check defined'}


def _check_setup_token(auth: dict, health: dict) -> dict:
    """Check Claude Code setup token — show who is authenticated."""
    import json as _json
    env_key = auth.get('env_key', 'ANTHROPIC_AUTH_TOKEN')
    token = os.getenv(env_key, '')

    try:
        env = {**os.environ}
        if token:
            env[env_key] = token

        result = subprocess.run(
            ['claude', 'auth', 'status'],
            capture_output=True, text=True, timeout=10, env=env
        )
        if result.returncode == 0:
            try:
                data = _json.loads(result.stdout.strip())
                email = data.get('email', '')
                sub = data.get('subscriptionType', '')
                via = f'setup token ···{token[-6:]}' if token else 'developer account'
                detail = f'{email} · {sub} · via {via}' if email else via
                return {'status': 'ok', 'detail': detail}
            except _json.JSONDecodeError:
                pass
        return {'status': 'ok' if token else 'unconfigured',
                'detail': 'Token set' if token else auth.get('fallback_note', 'No token set')}
    except Exception as e:
        return {'status': 'error', 'detail': str(e)}


def _check_file_sync(auth: dict, health: dict) -> dict:
    rel = health.get('path') or auth.get('expected_path', '')
    path = ROOT / rel
    if not path.exists():
        return {'status': 'pending_setup', 'detail': 'Waiting for sync — path not yet received'}
    # For directories use the most recently modified file inside
    if path.is_dir():
        mtimes = []
        for p in path.rglob('*'):
            try:
                mtimes.append(p.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
        mtime_src = max(mtimes) if mtimes else path.stat().st_mtime
    else:
        mtime_src = path.stat().st_mtime
    mtime = datetime.fromtimestamp(mtime_src, tz=timezone.utc)
    age_h = (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 3600
    max_age = health.get('max_age_hours', auth.get('max_age_hours', 48))
    if age_h > max_age:
        return {'status': 'stale', 'detail': f'Last updated {int(age_h)}h ago — check Syncthing on Mac'}
    return {'status': 'ok', 'detail': f'Updated {int(age_h)}h ago'}


def _check_api(health: dict) -> dict:
    try:
        import requests
    except ImportError:
        return {'status': 'error', 'detail': 'requests not installed'}

    url = health['url']
    expect = health.get('expect_status', 200)
    params = {k: _resolve(v) for k, v in health.get('params', {}).items()}
    headers = {}

    if 'auth_header' in health:
        raw = health['auth_header']
        parts = raw.split(' ', 1)
        if len(parts) == 2:
            headers[parts[0]] = _resolve(parts[1])
        else:
            headers['Authorization'] = _resolve(raw)

    for k, v in health.get('extra_headers', {}).items():
        headers[k] = v

    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        if r.status_code == expect:
            return {'status': 'ok', 'detail': f'HTTP {r.status_code}'}
        return {'status': 'error', 'detail': f'HTTP {r.status_code}'}
    except requests.RequestException as e:
        return {'status': 'error', 'detail': str(e)}


def _check_command(health: dict) -> dict:
    cmd = health.get('command', [])
    expect_exit = health.get('expect_exit_code', 0)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == expect_exit:
            out = result.stdout.decode().strip().splitlines()
            return {'status': 'ok', 'detail': out[0] if out else 'ok'}
        return {'status': 'error', 'detail': f'exit code {result.returncode}'}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {'status': 'error', 'detail': str(e)}


def check_service(name: str) -> str:
    """Returns 'active', 'inactive', or 'unknown'."""
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', name],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


def check_resources() -> dict:
    if HAS_PSUTIL:
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return {
            'ram_used_mb': round(ram.used / 1024 / 1024),
            'ram_total_mb': round(ram.total / 1024 / 1024),
            'ram_pct': ram.percent,
            'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 1),
            'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 1),
            'disk_pct': round(disk.percent, 1),
            'cpu_pct': psutil.cpu_percent(interval=0.5),
        }
    else:
        # Fallback without psutil
        disk = shutil.disk_usage('/')
        return {
            'ram_used_mb': 0,
            'ram_total_mb': 0,
            'ram_pct': 0,
            'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 1),
            'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 1),
            'disk_pct': round(disk.used / disk.total * 100, 1),
            'cpu_pct': 0,
        }
