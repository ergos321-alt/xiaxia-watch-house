from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import delete, or_, select
from werkzeug.security import check_password_hash

from .auth import csrf_required, ensure_csrf_token, json_error, reject_identity_fields, web_login_required
from .models import (
    Film,
    SubtitleCue,
    UserAnnotation,
    UserProgress,
    XiaxiaReply,
    XiaxiaThought,
    XiaxiaViewingState,
)
from .services import (
    ValidationError,
    annotation_dict,
    film_dict,
    progress_dict,
    replace_subtitles,
    reply_dict,
    require_text,
    seconds,
    set_current_film,
    thought_dict,
    touch_film,
    utcnow,
    validate_cue_for_film,
    validate_range,
    xiaxia_progress_dict,
)

web_bp = Blueprint("web", __name__)
SOURCE_TYPES = {"local", "youtube", "bilibili", "iframe", "external"}
PLAYBACK_STATES = {"playing", "paused", "seeking", "ended", "idle"}


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("JSON object body required")
    return data


def _film_or_404(film_id: str):
    film = g.db.get(Film, film_id)
    if not film:
        return None, json_error("film_not_found", "Film not found", 404)
    return film, None


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("since must be an ISO 8601 timestamp") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@web_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)
    password_hash = current_app.config.get("WEB_PASSWORD_HASH", "")
    password = request.form.get("password", "")
    if not password_hash or not check_password_hash(password_hash, password):
        return render_template("login.html", error="密码不正确。"), 401
    session.clear()
    session["web_authenticated"] = True
    ensure_csrf_token()
    next_url = request.args.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("web.watch_library")
    return redirect(next_url)


@web_bp.post("/logout")
@web_login_required()
@csrf_required
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@web_bp.get("/")
def index():
    return redirect(url_for("web.watch_library"))


@web_bp.get("/watch")
@web_login_required()
def watch_library():
    films = g.db.scalars(select(Film).order_by(Film.last_activity_at.desc())).all()
    items = [film_dict(g.db, film, include_state=True) for film in films]
    return render_template("watch_library.html", films=items)


@web_bp.get("/watch/<film_id>")
@web_login_required()
def watch_detail(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    set_current_film(g.db, film.film_id)
    touch_film(film)
    g.db.commit()
    return render_template("watch_detail.html", film=film_dict(g.db, film, include_state=True))


@web_bp.post("/api/web/films")
@web_login_required(api=True)
@csrf_required
def create_film():
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        title = require_text(data.get("title"), "title", 300)
        source_type = data.get("source_type")
        if source_type not in SOURCE_TYPES:
            raise ValidationError("source_type must be local, youtube, bilibili, iframe, or external")
        source_url = data.get("source_url") or None
        if source_type != "local":
            source_url = require_text(source_url, "source_url", 4000)
            parsed = urlparse(source_url)
            if parsed.scheme not in {"http", "https"}:
                raise ValidationError("source_url must use http or https")
        duration = seconds(data.get("duration_seconds"), "duration_seconds", required=False)
        film = Film(
            title=title,
            source_type=source_type,
            source_url=source_url,
            external_video_id=(data.get("external_video_id") or None),
            duration_seconds=duration,
        )
        g.db.add(film)
        g.db.flush()
        set_current_film(g.db, film.film_id)
        g.db.commit()
        return jsonify({"film": film_dict(g.db, film, include_state=True)}), 201
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.delete("/api/web/films/<film_id>")
@web_login_required(api=True)
@csrf_required
def delete_film(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    if data.get("confirm_title") != film.title:
        return json_error("confirmation_required", "confirm_title must exactly match the film title", 400)
    g.db.delete(film)
    g.db.commit()
    return jsonify({"deleted": True, "film_id": film_id, "storage_objects_deleted": 0})


@web_bp.post("/api/web/films/<film_id>/subtitles")
@web_login_required(api=True)
@csrf_required
def upload_subtitles(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    upload = request.files.get("subtitle")
    if not upload or not upload.filename:
        return json_error("validation_error", "subtitle file is required", 400)
    try:
        content = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return json_error("validation_error", "subtitle must be UTF-8 encoded", 400)
    try:
        count = replace_subtitles(g.db, film, content, upload.filename, request.form.get("language", "und"))
        g.db.commit()
        return jsonify({"film_id": film_id, "subtitle_status": "ready", "cue_count": count})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.put("/api/web/films/<film_id>/progress")
@web_login_required(api=True)
@csrf_required
def update_user_progress(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        current = seconds(data.get("current_seconds"), "current_seconds")
        duration = seconds(data.get("duration_seconds"), "duration_seconds", required=False)
        state = data.get("playback_state", "idle")
        if state not in PLAYBACK_STATES:
            raise ValidationError("Invalid playback_state")
        progress = g.db.get(UserProgress, film_id)
        if not progress:
            progress = UserProgress(film_id=film_id, actor="user")
            g.db.add(progress)
        progress.current_seconds = current
        progress.duration_seconds = duration
        progress.playback_state = state
        progress.updated_at = utcnow()
        if duration is not None:
            film.duration_seconds = duration
        touch_film(film)
        set_current_film(g.db, film_id)
        g.db.commit()
        return jsonify({"user_progress": progress_dict(progress)})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.route("/api/web/films/<film_id>/annotations", methods=["GET", "POST"])
@web_login_required(api=True)
def annotations(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    if request.method == "GET":
        rows = g.db.scalars(
            select(UserAnnotation)
            .where(UserAnnotation.film_id == film_id)
            .order_by(UserAnnotation.start_seconds, UserAnnotation.created_at)
        ).all()
        return jsonify({"annotations": [annotation_dict(row) for row in rows]})
    csrf_result = csrf_required(lambda: None)()
    if csrf_result is not None:
        return csrf_result
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        start = seconds(data.get("start_seconds"), "start_seconds")
        end = seconds(data.get("end_seconds"), "end_seconds", required=False)
        validate_range(start, end)
        cue_id = validate_cue_for_film(g.db, data.get("cue_id"), film_id)
        item = UserAnnotation(
            film_id=film_id,
            actor="user",
            content_type="user_annotation",
            start_seconds=start,
            end_seconds=end,
            cue_id=cue_id,
            content=require_text(data.get("content"), "content"),
        )
        g.db.add(item)
        touch_film(film)
        g.db.commit()
        return jsonify({"annotation": annotation_dict(item)}), 201
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.route("/api/web/annotations/<annotation_id>", methods=["PUT", "DELETE"])
@web_login_required(api=True)
@csrf_required
def annotation_item(annotation_id: str):
    item = g.db.get(UserAnnotation, annotation_id)
    if not item:
        return json_error("annotation_not_found", "Annotation not found", 404)
    if request.method == "DELETE":
        film_id = item.film_id
        g.db.delete(item)
        g.db.commit()
        return jsonify({"deleted": True, "annotation_id": annotation_id, "film_id": film_id})
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        if "content" in data:
            item.content = require_text(data["content"], "content")
        if "start_seconds" in data:
            item.start_seconds = seconds(data["start_seconds"], "start_seconds")
        if "end_seconds" in data:
            item.end_seconds = seconds(data["end_seconds"], "end_seconds", required=False)
        if "cue_id" in data:
            item.cue_id = validate_cue_for_film(g.db, data["cue_id"], item.film_id)
        validate_range(item.start_seconds, item.end_seconds)
        item.updated_at = utcnow()
        g.db.commit()
        return jsonify({"annotation": annotation_dict(item)})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.route("/api/web/thoughts/<thought_id>", methods=["PUT", "DELETE"])
@web_login_required(api=True)
@csrf_required
def thought_item(thought_id: str):
    item = g.db.get(XiaxiaThought, thought_id)
    if not item:
        return json_error("thought_not_found", "Thought not found", 404)
    if request.method == "DELETE":
        g.db.delete(item)
        g.db.commit()
        return jsonify({"deleted": True, "thought_id": thought_id})
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        if "content" in data:
            item.content = require_text(data["content"], "content")
        if "start_seconds" in data:
            item.start_seconds = seconds(data["start_seconds"], "start_seconds")
        if "end_seconds" in data:
            item.end_seconds = seconds(data["end_seconds"], "end_seconds", required=False)
        if "cue_id" in data:
            item.cue_id = validate_cue_for_film(g.db, data["cue_id"], item.film_id)
        validate_range(item.start_seconds, item.end_seconds)
        item.updated_at = utcnow()
        g.db.commit()
        return jsonify({"thought": thought_dict(item)})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.route("/api/web/replies/<reply_id>", methods=["PUT", "DELETE"])
@web_login_required(api=True)
@csrf_required
def reply_item(reply_id: str):
    item = g.db.get(XiaxiaReply, reply_id)
    if not item:
        return json_error("reply_not_found", "Reply not found", 404)
    if request.method == "DELETE":
        annotation_id = item.annotation_id
        g.db.delete(item)
        g.db.commit()
        return jsonify({"deleted": True, "reply_id": reply_id, "annotation_id": annotation_id})
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        if "content" in data:
            item.content = require_text(data["content"], "content")
        item.updated_at = utcnow()
        g.db.commit()
        return jsonify({"reply": reply_dict(item)})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@web_bp.get("/api/web/films/<film_id>/timeline")
@web_login_required(api=True)
def timeline(film_id: str):
    _, error = _film_or_404(film_id)
    if error:
        return error
    try:
        since = _parse_since(request.args.get("since"))
    except ValidationError as exc:
        return json_error("validation_error", str(exc), 400)
    # Return a one-second overlap cursor. The browser deduplicates by stable ID,
    # while the overlap avoids missing rows on databases with coarse timestamp precision.
    server_cursor = utcnow() - timedelta(seconds=1)
    annotation_query = select(UserAnnotation).where(UserAnnotation.film_id == film_id)
    thought_query = select(XiaxiaThought).where(XiaxiaThought.film_id == film_id)
    reply_query = select(XiaxiaReply).where(XiaxiaReply.film_id == film_id)
    if since:
        annotation_query = annotation_query.where(UserAnnotation.updated_at > since)
        thought_query = thought_query.where(XiaxiaThought.updated_at > since)
        reply_query = reply_query.where(XiaxiaReply.updated_at > since)
    annotations = g.db.scalars(annotation_query).all()
    thoughts = g.db.scalars(thought_query).all()
    replies = g.db.scalars(reply_query).all()
    entries = [annotation_dict(x) for x in annotations]
    entries += [thought_dict(x) for x in thoughts]
    entries += [reply_dict(x) for x in replies]
    entries.sort(key=lambda x: (x["start_seconds"], x["created_at"] or ""))
    return jsonify({"entries": entries, "cursor": server_cursor.isoformat().replace("+00:00", "Z")})


@web_bp.get("/api/web/films/<film_id>/state")
@web_login_required(api=True)
def web_film_state(film_id: str):
    film, error = _film_or_404(film_id)
    if error:
        return error
    return jsonify(
        {
            "film": film_dict(g.db, film, include_state=True),
            "user_progress": progress_dict(g.db.get(UserProgress, film_id)),
            "xiaxia_viewing_state": xiaxia_progress_dict(g.db.get(XiaxiaViewingState, film_id)),
        }
    )


@web_bp.get("/api/web/films/<film_id>/subtitles")
@web_login_required(api=True)
def web_subtitles(film_id: str):
    _, error = _film_or_404(film_id)
    if error:
        return error
    try:
        around = seconds(request.args.get("around_seconds", 0), "around_seconds")
    except ValidationError as exc:
        return json_error("validation_error", str(exc), 400)
    rows = g.db.scalars(
        select(SubtitleCue)
        .where(
            SubtitleCue.film_id == film_id,
            SubtitleCue.start_seconds <= around + 8,
            SubtitleCue.end_seconds >= max(0, around - 8),
        )
        .order_by(SubtitleCue.start_seconds)
        .limit(20)
    ).all()
    from .services import cue_dict

    return jsonify({"film_id": film_id, "around_seconds": around, "cues": [cue_dict(row) for row in rows]})
