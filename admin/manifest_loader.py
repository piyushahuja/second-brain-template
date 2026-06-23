import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTEGRATIONS_DIR = ROOT / 'integrations'
CATALOG_DIR = ROOT / 'catalog'

REQUIRED_KEYS = {'name', 'label', 'description', 'auth'}


def load_manifests() -> list[dict]:
    manifests = []
    for path in sorted(INTEGRATIONS_DIR.glob('*/manifest.json')):
        try:
            data = json.loads(path.read_text())
            missing = REQUIRED_KEYS - data.keys()
            if missing:
                continue
            # Ensure health key exists
            if 'health' not in data:
                data['health'] = {}
            manifests.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return manifests


def get_manifest(name: str) -> dict | None:
    for m in load_manifests():
        if m['name'] == name:
            return m
    return None


def load_catalog() -> list[dict]:
    manifests = []
    if not CATALOG_DIR.exists():
        return manifests
    for path in sorted(CATALOG_DIR.glob('*/manifest.json')):
        try:
            data = json.loads(path.read_text())
            if {'name', 'label', 'description', 'auth'}.issubset(data.keys()):
                manifests.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return manifests


def get_catalog_manifest(name: str) -> dict | None:
    for m in load_catalog():
        if m['name'] == name:
            return m
    return None
