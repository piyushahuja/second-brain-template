import json
import subprocess
from pathlib import Path
from flask import Blueprint, jsonify, request
from admin.auth import require_admin

bp = Blueprint('crons', __name__)

ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / 'cron' / 'registry.json'

PRESETS = {
    'hourly': '0 * * * *',
    'daily_2am': '0 2 * * *',
    'daily_7am': '0 7 * * *',
    'daily_10pm': '0 22 * * *',
    'sunday_4am': '30 4 * * 0',
    'every_50min': '*/50 * * * *',
}


def _load_registry() -> list:
    if not REGISTRY.exists():
        return []
    try:
        return json.loads(REGISTRY.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(jobs: list):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(jobs, indent=2))


def _read_crontab() -> str:
    r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def _write_crontab(content: str):
    subprocess.run(['crontab', '-'], input=content, text=True, check=True)


def _sync_crontab(jobs: list):
    """Rebuild crontab from registry — enabled jobs only."""
    existing = _read_crontab()
    # Keep non-second-brain lines (user may have other cron jobs)
    other = [l for l in existing.splitlines()
             if l.strip() and not any(j['script'] in l for j in jobs)]

    new_lines = other[:]
    for job in jobs:
        if job.get('enabled'):
            log = job.get('log', '/tmp/second-brain-cron.log')
            script = ROOT / job['script']
            new_lines.append(
                f'{job["schedule"]} {script} >> {log} 2>&1'
            )

    _write_crontab('\n'.join(new_lines) + '\n')


def _last_log_lines(log_path: str, n: int = 3) -> list[str]:
    p = Path(log_path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(errors='replace').splitlines()
        return lines[-n:]
    except Exception:
        return []


@bp.route('/cron')
@require_admin
def list_jobs():
    jobs = _load_registry()
    result = []
    for job in jobs:
        result.append({
            **job,
            'last_lines': _last_log_lines(job.get('log', ''), 5),
            'presets': PRESETS,
        })
    return jsonify(result)


@bp.route('/cron', methods=['POST'])
@require_admin
def add_job():
    body = request.get_json(silent=True) or {}
    required = {'id', 'label', 'script', 'schedule'}
    if not required.issubset(body):
        return jsonify({'error': f'required: {required}'}), 400

    jobs = _load_registry()
    if any(j['id'] == body['id'] for j in jobs):
        return jsonify({'error': 'id already exists'}), 409

    job = {
        'id': body['id'],
        'label': body['label'],
        'description': body.get('description', ''),
        'script': body['script'],
        'schedule': body['schedule'],
        'log': body.get('log', '/tmp/second-brain-cron.log'),
        'enabled': body.get('enabled', True),
    }
    jobs.append(job)
    _save_registry(jobs)
    _sync_crontab(jobs)
    return jsonify(job), 201


@bp.route('/cron/<job_id>', methods=['PATCH'])
@require_admin
def update_job(job_id):
    jobs = _load_registry()
    job = next((j for j in jobs if j['id'] == job_id), None)
    if not job:
        return jsonify({'error': 'not found'}), 404

    body = request.get_json(silent=True) or {}
    for field in ('label', 'description', 'schedule', 'enabled', 'log'):
        if field in body:
            job[field] = body[field]

    _save_registry(jobs)
    _sync_crontab(jobs)
    return jsonify(job)


@bp.route('/cron/<job_id>', methods=['DELETE'])
@require_admin
def delete_job(job_id):
    jobs = _load_registry()
    jobs = [j for j in jobs if j['id'] != job_id]
    _save_registry(jobs)
    _sync_crontab(jobs)
    return jsonify({'status': 'ok'})


@bp.route('/cron/<job_id>/run', methods=['POST'])
@require_admin
def run_job(job_id):
    jobs = _load_registry()
    job = next((j for j in jobs if j['id'] == job_id), None)
    if not job:
        return jsonify({'error': 'not found'}), 404

    script = ROOT / job['script']
    log = job.get('log', '/tmp/second-brain-cron.log')
    subprocess.Popen(
        ['bash', str(script)],
        stdout=open(log, 'a'), stderr=subprocess.STDOUT,
        start_new_session=True
    )
    return jsonify({'status': 'started', 'log': log})
