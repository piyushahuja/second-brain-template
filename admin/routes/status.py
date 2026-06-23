import os
from flask import Blueprint, jsonify
from admin.auth import require_admin
from admin.health import check_service, check_resources, check_integration
from admin.manifest_loader import load_manifests
from admin.syncthing import get_info as syncthing_info

bp = Blueprint('status', __name__)

SERVICES = ['second-brain-bot', 'second-brain-admin']


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


@bp.route('/status')
@require_admin
def status():
    services = {svc: check_service(svc) for svc in SERVICES}
    resources = check_resources()

    integrations = []
    for m in load_manifests():
        health = check_integration(m)
        entry = _integration_dict(m, health)
        if m['name'] == 'google':
            entry['email'] = os.getenv('GOOGLE_EMAIL', '')
            granted_raw = os.getenv('GOOGLE_GRANTED_SCOPES', '')
            entry['granted_pipelines'] = [p for p in granted_raw.split(',') if p]
        integrations.append(entry)

    return jsonify({
        'services': services,
        'resources': resources,
        'integrations': integrations,
        'syncthing': syncthing_info(),
    })
