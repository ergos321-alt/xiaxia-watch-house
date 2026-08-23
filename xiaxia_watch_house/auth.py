from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import current_app, jsonify, redirect, request, session, url_for


def json_error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def web_login_required(api: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("web_authenticated"):
                if api:
                    return json_error("web_auth_required", "Web session authentication required", 401)
                return redirect(url_for("web.login", next=request.path))
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def action_token_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = current_app.config.get("ACTION_BEARER_TOKEN", "")
        header = request.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            return json_error("action_auth_required", "Valid Action bearer token required", 401)
        return fn(*args, **kwargs)

    return wrapped


def ensure_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            return json_error("csrf_failed", "Invalid CSRF token", 403)
        return fn(*args, **kwargs)

    return wrapped


def reject_identity_fields(data: dict):
    forbidden = {"actor", "author", "owner"}.intersection(data)
    if forbidden:
        return json_error(
            "identity_is_server_controlled",
            "actor, author, and owner are server-controlled fields",
            400,
        )
    return None
