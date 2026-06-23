import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTEGRATIONS_DIR = ROOT / 'integrations'
LLM_DIR          = ROOT / 'llm'
CATALOG_DIR      = ROOT / 'catalog'

REQUIRED_KEYS = {'name', 'label', 'description', 'auth'}


def load_manifests() -> list[dict]:
    manifests = []
    sources = [
        (INTEGRATIONS_DIR, 'integration'),
        (LLM_DIR,          'llm'),
    ]
    for directory, category in sources:
        for path in sorted(directory.glob('*/manifest.json')):
            try:
                data = json.loads(path.read_text())
                if REQUIRED_KEYS - data.keys():
                    continue
                if 'health' not in data:
                    data['health'] = {}
                data.setdefault('category', category)
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
