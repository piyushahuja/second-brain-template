import os
import secrets
import time
from flask import Blueprint, redirect, request
from admin.manifest_loader import get_manifest
from admin.routes.env import write_env_key

bp = Blueprint('oauth', __name__)

# Single-user admin: store OAuth state in env vars rather than session cookies.
# Avoids cross-domain cookie issues when the admin panel is accessed via IP:port
# but the OAuth callback comes back via the tunnel domain (or vice versa).
_STATE_KEY    = 'OAUTH_PENDING_STATE'
_PIPELINES_KEY = 'OAUTH_PENDING_PIPELINES'
_RETRACT_KEY  = 'OAUTH_PENDING_RETRACT'


def _pipeline_scopes(manifest, pipeline_ids):
    """Return scopes for the given pipeline IDs from a manifest."""
    scopes = []
    for p in manifest.get('pipelines', []):
        if isinstance(p, dict) and p['id'] in pipeline_ids:
            scopes.extend(p.get('scopes', []))
    return scopes


def _save_pending(state, selected, is_retraction):
    for key, val in [(_STATE_KEY, state),
                     (_PIPELINES_KEY, ','.join(selected)),
                     (_RETRACT_KEY, '1' if is_retraction else '0')]:
        write_env_key(key, val)
        os.environ[key] = val


def _pop_pending():
    state        = os.environ.pop(_STATE_KEY, '')
    selected     = [p for p in os.environ.pop(_PIPELINES_KEY, '').split(',') if p]
    is_retraction = os.environ.pop(_RETRACT_KEY, '0') == '1'
    for key in (_STATE_KEY, _PIPELINES_KEY, _RETRACT_KEY):
        write_env_key(key, '')
    return state, selected, is_retraction


@bp.route('/oauth/<provider>')
def oauth_start(provider):
    m = get_manifest(provider)
    if not m or m['auth'].get('type') != 'oauth2':
        return f'Unknown provider: {provider}', 404

    auth = m['auth']
    client_id = os.getenv(auth['client_id_env'], '')
    if not client_id:
        return f'{auth["client_id_env"]} not set in .env', 400

    selected_raw = request.args.get('pipelines', '')
    selected = [p for p in selected_raw.split(',') if p]
    if not selected:
        selected = [p['id'] for p in m.get('pipelines', []) if isinstance(p, dict)]

    scopes = _pipeline_scopes(m, selected)
    if not scopes:
        scopes = auth.get('scopes', [])

    currently_granted = [p for p in os.getenv('GOOGLE_GRANTED_SCOPES', '').split(',') if p]
    is_retraction = any(p in currently_granted and p not in selected for p in currently_granted)

    state = secrets.token_urlsafe(16)
    _save_pending(state, selected, is_retraction)

    vps_base = os.getenv('VPS_BASE_URL', f'http://localhost:{os.getenv("ADMIN_PORT", 8080)}')
    redirect_uri = f'{vps_base}/oauth/callback/{provider}'

    from urllib.parse import urlencode
    params = {
        'client_id':     client_id,
        'redirect_uri':  redirect_uri,
        'response_type': 'code',
        'scope':         ' '.join(scopes),
        'access_type':   'offline',
        'state':         state,
    }
    if is_retraction:
        params['prompt'] = 'consent'
    else:
        params['include_granted_scopes'] = 'true'

    return redirect(auth['auth_url'] + '?' + urlencode(params))


@bp.route('/oauth/callback/<provider>')
def oauth_callback(provider):
    m = get_manifest(provider)
    if not m or m['auth'].get('type') != 'oauth2':
        return f'Unknown provider: {provider}', 404

    auth = m['auth']
    state = request.args.get('state', '')
    expected_state, selected, is_retraction = _pop_pending()

    if not expected_state or state != expected_state:
        return 'State mismatch — possible CSRF', 400

    code = request.args.get('code')
    if not code:
        return f'OAuth error: {request.args.get("error", "no code")}', 400

    vps_base = os.getenv('VPS_BASE_URL', f'http://localhost:{os.getenv("ADMIN_PORT", 8080)}')
    redirect_uri = f'{vps_base}/oauth/callback/{provider}'

    import requests as http
    resp = http.post(auth['token_url'], data={
        'code':          code,
        'client_id':     os.getenv(auth['client_id_env'], ''),
        'client_secret': os.getenv(auth['client_secret_env'], ''),
        'redirect_uri':  redirect_uri,
        'grant_type':    'authorization_code',
    }, timeout=10)

    if not resp.ok:
        return f'Token exchange failed: {resp.text}', 500

    data = resp.json()
    keys = auth.get('token_env_keys', [])

    if len(keys) >= 1 and 'access_token' in data:
        write_env_key(keys[0], data['access_token'])
        os.environ[keys[0]] = data['access_token']
    if len(keys) >= 2 and 'refresh_token' in data:
        write_env_key(keys[1], data['refresh_token'])
        os.environ[keys[1]] = data['refresh_token']
    if len(keys) >= 3 and 'expires_in' in data:
        expiry = str(int(time.time()) + int(data['expires_in']))
        write_env_key(keys[2], expiry)
        os.environ[keys[2]] = expiry

    # Update granted scopes: retraction = selected only; addition = union with existing
    if is_retraction:
        new_granted = selected
    else:
        existing = [p for p in os.getenv('GOOGLE_GRANTED_SCOPES', '').split(',') if p]
        new_granted = list(dict.fromkeys(existing + selected))  # ordered, deduplicated

    write_env_key('GOOGLE_GRANTED_SCOPES', ','.join(new_granted))
    os.environ['GOOGLE_GRANTED_SCOPES'] = ','.join(new_granted)

    # Fetch and store email
    access_token = data.get('access_token', '')
    if access_token:
        try:
            info = http.get('https://www.googleapis.com/oauth2/v1/userinfo',
                            headers={'Authorization': f'Bearer {access_token}'}, timeout=5)
            if info.ok:
                email = info.json().get('email', '')
                if email:
                    write_env_key('GOOGLE_EMAIL', email)
                    os.environ['GOOGLE_EMAIL'] = email
        except Exception:
            pass

    return redirect('/admin#sources')
