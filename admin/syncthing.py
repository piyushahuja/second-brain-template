import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

SYNCTHING_URL = 'http://localhost:8384'
_TIMEOUT = 3


def _api_key() -> str:
    key = os.getenv('SYNCTHING_API_KEY', '')
    if key:
        return key
    for p in [
        Path.home() / '.local/state/syncthing/config.xml',
        Path.home() / '.config/syncthing/config.xml',
    ]:
        if p.exists():
            try:
                tree = ET.parse(p)
                el = tree.find('.//apikey')
                if el is not None and el.text:
                    return el.text
            except Exception:
                pass
    return ''


def _age(iso: str) -> str:
    """Return human-readable age string from ISO timestamp."""
    if not iso:
        return '?'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        secs = (datetime.now(tz=timezone.utc) - dt).total_seconds()
        if secs < 120:
            return 'just now'
        if secs < 3600:
            return f'{int(secs/60)}m ago'
        if secs < 86400:
            return f'{int(secs/3600)}h ago'
        return f'{int(secs/86400)}d ago'
    except Exception:
        return '?'


def get_info() -> dict:
    if not HAS_REQUESTS:
        return {'available': False, 'error': 'requests not installed'}

    api_key = _api_key()
    if not api_key:
        return {'available': False, 'error': 'No API key'}

    headers = {'X-API-Key': api_key}
    try:
        status = requests.get(f'{SYNCTHING_URL}/rest/system/status',
                              headers=headers, timeout=_TIMEOUT).json()
        device_id = status.get('myID', '')

        conns = requests.get(f'{SYNCTHING_URL}/rest/system/connections',
                             headers=headers, timeout=_TIMEOUT).json()
        connections = conns.get('connections', {})
        connected = sum(1 for v in connections.values() if v.get('connected'))

        folder_configs = requests.get(f'{SYNCTHING_URL}/rest/config/folders',
                                      headers=headers, timeout=_TIMEOUT).json()
        folders = []
        for fc in folder_configs:
            fid = fc.get('id', '')
            label = fc.get('label') or fid
            path = fc.get('path', '').replace(str(Path.home()), '~')
            try:
                db = requests.get(f'{SYNCTHING_URL}/rest/db/status',
                                  headers=headers, params={'folder': fid},
                                  timeout=_TIMEOUT).json()
                state = db.get('state', 'unknown')
                need_files = db.get('needFiles', 0)
                changed_at = db.get('stateChanged', '')
                if state == 'idle' and need_files == 0:
                    sync = 'synced'
                elif state in ('syncing', 'scanning'):
                    sync = state
                elif need_files > 0:
                    sync = 'behind'
                else:
                    sync = 'unknown'
            except Exception:
                sync = 'unknown'
                changed_at = ''

            folders.append({
                'label': label,
                'path': path,
                'status': sync,
                'updated': _age(changed_at),
            })

        pending = _get_pending(headers)

        return {
            'available': True,
            'device_id': device_id,
            'connected_devices': connected,
            'total_devices': len(connections),
            'folders': folders,
            'pending': pending,
        }
    except Exception as e:
        return {'available': False, 'error': str(e)}


def _get_pending(headers: dict) -> dict:
    devices, folders = [], []
    try:
        r = requests.get(f'{SYNCTHING_URL}/rest/cluster/pending/devices',
                         headers=headers, timeout=_TIMEOUT)
        if r.ok:
            for did, info in r.json().items():
                devices.append({'device_id': did, 'name': info.get('name', did[:7])})
    except Exception:
        pass
    try:
        r = requests.get(f'{SYNCTHING_URL}/rest/cluster/pending/folders',
                         headers=headers, timeout=_TIMEOUT)
        if r.ok:
            for fid, info in r.json().items():
                for did, dinfo in info.get('offeredBy', {}).items():
                    folders.append({
                        'folder_id': fid,
                        'label': dinfo.get('label', fid),
                        'from_device': did,
                    })
    except Exception:
        pass
    return {'devices': devices, 'folders': folders}


def accept_device(device_id: str, name: str) -> bool:
    if not HAS_REQUESTS:
        return False
    api_key = _api_key()
    if not api_key:
        return False
    headers = {'X-API-Key': api_key, 'Content-Type': 'application/json'}
    try:
        cfg = requests.get(f'{SYNCTHING_URL}/rest/config',
                           headers=headers, timeout=_TIMEOUT).json()
        if any(d['deviceID'] == device_id for d in cfg.get('devices', [])):
            return True
        cfg['devices'].append({
            'deviceID': device_id,
            'name': name or device_id[:7],
            'addresses': ['dynamic'],
        })
        r = requests.put(f'{SYNCTHING_URL}/rest/config', headers=headers,
                         json=cfg, timeout=_TIMEOUT)
        return r.ok
    except Exception:
        return False


def accept_folder(folder_id: str, label: str, local_path: str, device_id: str) -> bool:
    if not HAS_REQUESTS:
        return False
    api_key = _api_key()
    if not api_key:
        return False
    headers = {'X-API-Key': api_key, 'Content-Type': 'application/json'}
    try:
        cfg = requests.get(f'{SYNCTHING_URL}/rest/config',
                           headers=headers, timeout=_TIMEOUT).json()
        if any(f['id'] == folder_id for f in cfg.get('folders', [])):
            return True
        full_path = str(Path(__file__).parent.parent / local_path)
        cfg['folders'].append({
            'id': folder_id,
            'label': label,
            'path': full_path,
            'type': 'receiveonly',
            'rescanIntervalS': 3600,
            'devices': [{'deviceID': device_id}],
        })
        r = requests.put(f'{SYNCTHING_URL}/rest/config', headers=headers,
                         json=cfg, timeout=_TIMEOUT)
        return r.ok
    except Exception:
        return False
