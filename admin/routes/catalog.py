import shutil
from pathlib import Path
from flask import Blueprint, jsonify
from admin.auth import require_admin
from admin.manifest_loader import load_manifests, load_catalog, get_catalog_manifest
from admin.routes.crons import _load_registry, _save_registry, _sync_crontab

bp = Blueprint('catalog', __name__)

ROOT = Path(__file__).parents[2]
CATALOG_DIR = ROOT / 'catalog'
INTEGRATIONS_DIR = ROOT / 'integrations'


@bp.route('/catalog')
@require_admin
def list_catalog():
    installed_names = {m['name'] for m in load_manifests()}
    return jsonify([
        {
            'name': m['name'],
            'label': m['label'],
            'description': m['description'],
            'icon': m.get('icon', ''),
            'auth_type': m['auth']['type'],
        }
        for m in load_catalog()
        if m['name'] not in installed_names
    ])


@bp.route('/catalog/<name>/install', methods=['POST'])
@require_admin
def install_catalog(name):
    m = get_catalog_manifest(name)
    if not m:
        return jsonify({'error': 'not found'}), 404

    # Copy manifest into integrations/
    src_dir = CATALOG_DIR / name
    dst_dir = INTEGRATIONS_DIR / name
    dst_dir.mkdir(exist_ok=True)

    if (src_dir / 'manifest.json').exists():
        shutil.copy(src_dir / 'manifest.json', dst_dir / 'manifest.json')

    # Register cron job if manifest specifies one
    cron_entry = m.get('cron')
    if cron_entry and cron_entry.get('id'):
        jobs = _load_registry()
        if not any(j['id'] == cron_entry['id'] for j in jobs):
            jobs.append({
                'id': cron_entry['id'],
                'label': cron_entry.get('label', name),
                'description': cron_entry.get('description', ''),
                'script': cron_entry.get('script', ''),
                'schedule': cron_entry.get('schedule', '0 * * * *'),
                'log': cron_entry.get('log', '/tmp/second-brain-cron.log'),
                'enabled': cron_entry.get('enabled', True),
            })
            _save_registry(jobs)
            _sync_crontab(jobs)

    return jsonify({'status': 'installed', 'name': name})
