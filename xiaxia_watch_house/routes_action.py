from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from .auth import action_token_required, json_error, reject_identity_fields
from .models import (
    Film,
    FleetingTrace,
    SubtitleCue,
    UserAnnotation,
    UserProgress,
    WatchState,
    XiaxiaReply,
    XiaxiaThought,
    XiaxiaViewingState,
)
from .services import (
    DEFAULT_TRANSCRIPT_CUES,
    MAX_RANGE_SECONDS,
    MAX_TRANSCRIPT_CUES,
    ValidationError,
    annotation_dict,
    cleanup_expired_fleeting_traces,
    cue_dict,
    decode_continuation,
    encode_continuation,
    film_dict,
    fleeting_trace_dict,
    new_trace_expiry,
    progress_dict,
    reply_dict,
    require_text,
    seconds,
    subtitle_range,
    thought_dict,
    touch_film,
    utcnow,
    validate_cue_for_film,
    validate_range,
    xiaxia_progress_dict,
)

action_bp = Blueprint("action", __name__, url_prefix="/api/watch")


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("JSON object body required")
    return data


def _film_or_error(film_id: str):
    film = g.db.get(Film, film_id)
    if not film:
        return None, json_error("film_not_found", "Film not found", 404)
    return film, None


def _bounded_int(value, field: str, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer") from None
    if parsed < minimum or parsed > maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum}")
    return parsed


@action_bp.get("/videos")
@action_token_required
def list_videos():
    films = g.db.scalars(select(Film).order_by(Film.last_activity_at.desc())).all()
    return jsonify({"films": [film_dict(g.db, film, include_state=True) for film in films], "count": len(films)})


@action_bp.get("/videos/<film_id>")
@action_token_required
def get_video(film_id: str):
    film, error = _film_or_error(film_id)
    if error:
        return error
    return jsonify({"film": film_dict(g.db, film, include_state=True)})


@action_bp.get("/state")
@action_token_required
def get_watch_state():
    state = g.db.get(WatchState, 1)
    film = g.db.get(Film, state.current_film_id) if state and state.current_film_id else None
    if not film:
        film = g.db.scalar(select(Film).order_by(Film.last_activity_at.desc()).limit(1))
    return jsonify(
        {
            "current_film": film_dict(g.db, film, include_state=True) if film else None,
            "user_progress": progress_dict(g.db.get(UserProgress, film.film_id)) if film else None,
            "xiaxia_viewing_state": xiaxia_progress_dict(g.db.get(XiaxiaViewingState, film.film_id)) if film else None,
        }
    )


@action_bp.get("/videos/<film_id>/context")
@action_token_required
def get_current_context(film_id: str):
    film, error = _film_or_error(film_id)
    if error:
        return error
    try:
        before_seconds = seconds(request.args.get("before_seconds", 120), "before_seconds")
        before_seconds = min(before_seconds, 600.0)
        requested_raw = request.args.get("timestamp_seconds")
        user_progress = g.db.get(UserProgress, film_id)
        if requested_raw is None:
            requested = user_progress.current_seconds if user_progress else 0.0
        else:
            requested = seconds(requested_raw, "timestamp_seconds")
        boundary = min(requested, user_progress.current_seconds) if user_progress else requested
        evidence_start = max(0.0, boundary - before_seconds)

        cues = g.db.scalars(
            select(SubtitleCue)
            .where(
                SubtitleCue.film_id == film_id,
                SubtitleCue.start_seconds >= evidence_start,
                SubtitleCue.start_seconds <= boundary,
            )
            .order_by(SubtitleCue.start_seconds)
            .limit(MAX_TRANSCRIPT_CUES)
        ).all()
        annotations = g.db.scalars(
            select(UserAnnotation).where(
                UserAnnotation.film_id == film_id,
                UserAnnotation.start_seconds >= evidence_start,
                UserAnnotation.start_seconds <= boundary,
            )
        ).all()
        thoughts = g.db.scalars(
            select(XiaxiaThought).where(
                XiaxiaThought.film_id == film_id,
                XiaxiaThought.start_seconds >= evidence_start,
                XiaxiaThought.start_seconds <= boundary,
            )
        ).all()
        replies = g.db.scalars(
            select(XiaxiaReply).where(
                XiaxiaReply.film_id == film_id,
                XiaxiaReply.start_seconds >= evidence_start,
                XiaxiaReply.start_seconds <= boundary,
            )
        ).all()
        fleeting = g.db.scalars(
            select(FleetingTrace).where(
                FleetingTrace.film_id == film_id,
                FleetingTrace.start_seconds >= evidence_start,
                FleetingTrace.start_seconds <= boundary,
                FleetingTrace.expires_at > utcnow(),
            )
        ).all()
        entries = [annotation_dict(x) for x in annotations]
        entries += [thought_dict(x) for x in thoughts]
        entries += [reply_dict(x) for x in replies]
        entries += [fleeting_trace_dict(x) for x in fleeting]
        entries.sort(key=lambda item: (item["start_seconds"], item.get("created_at") or ""))
        return jsonify(
            {
                "film": film_dict(g.db, film),
                "requested_timestamp_seconds": requested,
                "evidence_start_seconds": evidence_start,
                "evidence_end_seconds": boundary,
                "spoiler_boundary_seconds": boundary,
                "subtitle_cues": [cue_dict(cue) for cue in cues],
                "timeline_entries": entries,
                "user_progress": progress_dict(user_progress),
                "xiaxia_viewing_state": xiaxia_progress_dict(g.db.get(XiaxiaViewingState, film_id)),
            }
        )
    except ValidationError as exc:
        return json_error("validation_error", str(exc), 400)


@action_bp.get("/videos/<film_id>/transcript")
@action_token_required
def get_transcript(film_id: str):
    film, error = _film_or_error(film_id)
    if error:
        return error
    available = subtitle_range(g.db, film_id)
    if not available["available"]:
        return jsonify(
            {
                "film_id": film_id,
                "available_start_seconds": None,
                "available_end_seconds": None,
                "cue_count": 0,
                "cues": [],
                "chunk_index": 0,
                "chunk_size_cues": 0,
                "has_previous": False,
                "has_next": False,
            }
        )
    try:
        chunk_size = _bounded_int(
            request.args.get("chunk_size_cues"), "chunk_size_cues", DEFAULT_TRANSCRIPT_CUES, 1, MAX_TRANSCRIPT_CUES
        )
        chunk_index = _bounded_int(request.args.get("chunk_index"), "chunk_index", 0, 0, 1_000_000)
        requested_start = request.args.get("start_seconds")
        requested_end = request.args.get("end_seconds")
        continuation = request.args.get("continuation")
        from_checkpoint = request.args.get("from_checkpoint", "false").lower() in {"1", "true", "yes"}
        offset = chunk_index * chunk_size
        if continuation:
            payload = decode_continuation(continuation)
            if payload.get("film_id") != film_id:
                raise ValidationError("Continuation token belongs to another film")
            offset = int(payload.get("offset", 0))
            requested_start = payload.get("start_seconds")
            requested_end = payload.get("end_seconds")
            chunk_size = _bounded_int(payload.get("chunk_size_cues"), "chunk_size_cues", chunk_size, 1, MAX_TRANSCRIPT_CUES)
            chunk_index = offset // chunk_size

        if from_checkpoint and not continuation and requested_start is None and requested_end is None:
            checkpoint = g.db.get(XiaxiaViewingState, film_id)
            requested_start = checkpoint.last_timestamp_seconds if checkpoint else 0.0
            requested_end = float(requested_start) + MAX_RANGE_SECONDS

        start = seconds(requested_start, "start_seconds", required=False)
        end = seconds(requested_end, "end_seconds", required=False)
        if start is not None and end is None:
            end = start + MAX_RANGE_SECONDS
        if start is None and end is not None:
            start = max(0.0, end - MAX_RANGE_SECONDS)
        if start is not None and end is not None:
            validate_range(start, end)
            end = min(end, start + MAX_RANGE_SECONDS)

        filters = [SubtitleCue.film_id == film_id]
        if start is not None:
            filters.append(SubtitleCue.end_seconds >= start)
        if end is not None:
            filters.append(SubtitleCue.start_seconds <= end)
        total = int(g.db.scalar(select(func.count()).select_from(SubtitleCue).where(*filters)) or 0)
        rows = g.db.scalars(
            select(SubtitleCue)
            .where(*filters)
            .order_by(SubtitleCue.sequence_number)
            .offset(offset)
            .limit(chunk_size)
        ).all()
        has_previous = offset > 0
        has_next = offset + len(rows) < total
        response = {
            "film_id": film_id,
            "available_start_seconds": available["start_seconds"],
            "available_end_seconds": available["end_seconds"],
            "range_start_seconds": start if start is not None else available["start_seconds"],
            "range_end_seconds": end if end is not None else available["end_seconds"],
            "cue_count": len(rows),
            "chunk_index": chunk_index,
            "chunk_size_cues": chunk_size,
            "cues": [cue_dict(cue) for cue in rows],
            "has_previous": has_previous,
            "has_next": has_next,
        }
        if has_previous:
            response["previous_chunk_index"] = max(0, chunk_index - 1)
        if has_next:
            response["next_chunk_index"] = chunk_index + 1
            response["continuation"] = encode_continuation(
                {
                    "film_id": film_id,
                    "offset": offset + len(rows),
                    "start_seconds": start,
                    "end_seconds": end,
                    "chunk_size_cues": chunk_size,
                }
            )
        return jsonify(response)
    except (ValidationError, TypeError, ValueError) as exc:
        return json_error("validation_error", str(exc), 400)


@action_bp.get("/videos/<film_id>/annotations")
@action_token_required
def list_annotations(film_id: str):
    _, error = _film_or_error(film_id)
    if error:
        return error
    rows = g.db.scalars(
        select(UserAnnotation)
        .where(UserAnnotation.film_id == film_id)
        .order_by(UserAnnotation.start_seconds, UserAnnotation.created_at)
    ).all()
    return jsonify({"film_id": film_id, "annotations": [annotation_dict(row) for row in rows]})


@action_bp.route("/videos/<film_id>/thoughts", methods=["GET", "POST"])
@action_token_required
def thoughts(film_id: str):
    film, error = _film_or_error(film_id)
    if error:
        return error
    if request.method == "GET":
        rows = g.db.scalars(
            select(XiaxiaThought)
            .where(XiaxiaThought.film_id == film_id)
            .order_by(XiaxiaThought.start_seconds, XiaxiaThought.created_at)
        ).all()
        return jsonify({"film_id": film_id, "thoughts": [thought_dict(row) for row in rows]})
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        start = seconds(data.get("start_seconds"), "start_seconds")
        end = seconds(data.get("end_seconds"), "end_seconds", required=False)
        validate_range(start, end)
        item = XiaxiaThought(
            film_id=film_id,
            actor="xiaxia",
            content_type="xiaxia_thought",
            start_seconds=start,
            end_seconds=end,
            cue_id=validate_cue_for_film(g.db, data.get("cue_id"), film_id),
            content=require_text(data.get("content"), "content"),
        )
        g.db.add(item)
        touch_film(film)
        g.db.commit()
        return jsonify({"thought": thought_dict(item)}), 201
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@action_bp.route("/videos/<film_id>/fleeting-traces", methods=["GET", "POST"])
@action_token_required
def fleeting_traces(film_id: str):
    film, error = _film_or_error(film_id)
    if error:
        return error
    if request.method == "GET":
        rows = g.db.scalars(
            select(FleetingTrace)
            .where(FleetingTrace.film_id == film_id, FleetingTrace.expires_at > utcnow())
            .order_by(FleetingTrace.start_seconds, FleetingTrace.created_at)
        ).all()
        return jsonify({"film_id": film_id, "fleeting_traces": [fleeting_trace_dict(row) for row in rows]})
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        start = seconds(data.get("start_seconds"), "start_seconds")
        end = seconds(data.get("end_seconds"), "end_seconds", required=False)
        validate_range(start, end)
        cleanup_expired_fleeting_traces(g.db)
        item = FleetingTrace(
            film_id=film_id,
            actor="xiaxia",
            content_type="fleeting_trace",
            start_seconds=start,
            end_seconds=end,
            cue_id=validate_cue_for_film(g.db, data.get("cue_id"), film_id),
            content=require_text(data.get("content"), "content", 160),
            expires_at=new_trace_expiry(),
        )
        g.db.add(item)
        touch_film(film)
        g.db.commit()
        return jsonify({"fleeting_trace": fleeting_trace_dict(item)}), 201
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@action_bp.post("/annotations/<annotation_id>/reply")
@action_token_required
def create_reply(annotation_id: str):
    annotation = g.db.get(UserAnnotation, annotation_id)
    if not annotation:
        return json_error("annotation_not_found", "Annotation not found", 404)
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        start = seconds(data.get("start_seconds"), "start_seconds", required=False)
        end = seconds(data.get("end_seconds"), "end_seconds", required=False)
        start = annotation.start_seconds if start is None else start
        end = annotation.end_seconds if end is None else end
        validate_range(start, end)
        cue_id = data.get("cue_id", annotation.cue_id)
        item = XiaxiaReply(
            annotation_id=annotation.annotation_id,
            film_id=annotation.film_id,
            actor="xiaxia",
            content_type="xiaxia_reply",
            start_seconds=start,
            end_seconds=end,
            cue_id=validate_cue_for_film(g.db, cue_id, annotation.film_id),
            content=require_text(data.get("content"), "content"),
        )
        g.db.add(item)
        film = g.db.get(Film, annotation.film_id)
        touch_film(film)
        g.db.commit()
        return jsonify({"reply": reply_dict(item)}), 201
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)


@action_bp.post("/xiaxia/progress")
@action_token_required
def update_xiaxia_progress():
    try:
        data = _json()
        identity_error = reject_identity_fields(data)
        if identity_error:
            return identity_error
        film_id = require_text(data.get("film_id"), "film_id", 36)
        film, error = _film_or_error(film_id)
        if error:
            return error
        last_timestamp = seconds(data.get("last_timestamp_seconds"), "last_timestamp_seconds")
        cue_id = validate_cue_for_film(g.db, data.get("last_subtitle_cue_id"), film_id)
        checkpoint = data.get("chunk_checkpoint")
        if checkpoint is not None:
            checkpoint = _bounded_int(checkpoint, "chunk_checkpoint", 0, 0, 1_000_000)
        completed = data.get("completed", False)
        if not isinstance(completed, bool):
            raise ValidationError("completed must be boolean")
        state = g.db.get(XiaxiaViewingState, film_id)
        if not state:
            state = XiaxiaViewingState(film_id=film_id, actor="xiaxia")
            g.db.add(state)
        state.last_timestamp_seconds = last_timestamp
        state.last_subtitle_cue_id = cue_id
        state.chunk_checkpoint = checkpoint
        state.completed = completed
        state.updated_at = utcnow()
        touch_film(film)
        g.db.commit()
        return jsonify({"xiaxia_viewing_state": xiaxia_progress_dict(state)})
    except ValidationError as exc:
        g.db.rollback()
        return json_error("validation_error", str(exc), 400)
