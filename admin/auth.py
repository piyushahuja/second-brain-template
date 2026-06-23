import os
from functools import wraps
from flask import request, abort


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_token = os.getenv('ADMIN_TOKEN', '')
        if not admin_token:
            return f(*args, **kwargs)  # No token = open access
        token = request.headers.get('X-Admin-Token') or request.args.get('token')
        if not token or token != admin_token:
            abort(401)
        return f(*args, **kwargs)
    return decorated
