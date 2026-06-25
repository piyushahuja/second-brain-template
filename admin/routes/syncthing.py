from flask import Blueprint, jsonify, request
from admin.auth import require_admin
from admin.syncthing import accept_device, accept_folder, share_outputs

bp = Blueprint('syncthing', __name__)


@bp.route('/syncthing/accept/device', methods=['POST'])
@require_admin
def syncthing_accept_device():
    body = request.get_json(silent=True) or {}
    ok = accept_device(body.get('device_id', ''), body.get('name', ''))
    return jsonify({'ok': ok})


@bp.route('/syncthing/accept/folder', methods=['POST'])
@require_admin
def syncthing_accept_folder():
    body = request.get_json(silent=True) or {}
    ok = accept_folder(
        body.get('folder_id', ''),
        body.get('label', ''),
        body.get('local_path', ''),
        body.get('device_id', ''),
    )
    return jsonify({'ok': ok})


@bp.route('/syncthing/share/outputs', methods=['POST'])
@require_admin
def syncthing_share_outputs():
    ok = share_outputs()
    status = 'shared' if ok else 'error'
    return jsonify({'ok': ok, 'status': status})
