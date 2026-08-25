from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select

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

MAX_CONTENT_LENGTH = 8000
MAX_TRANSCRIPT_CUES = 200
DEFAULT_TRANSCRIPT_CUES = 80
MAX_RANGE_SECONDS = 1800.0
FLEETING_TRACE_MAX_LENGTH = 160
FLEETING_TRACE_RETENTION_DAYS = 30
TOGETHER_WINDOW_SECONDS = 15.0
NEARBY_WINDOW_SECONDS = 120.0
SHARED_STOP_WINDOW_SECONDS = 15.0


class ValidationError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def require_text(value: Any, field: str, maximum: int = MAX_CONTENT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required")
    result = value.strip()
    if len(result) > maximum:
        raise ValidationError(f"{field} exceeds {maximum} characters")
    return result


def seconds(value: Any, field: str, *, required: bool = True) -> float | None:
    if value is None and not required:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be seconds as a number") from None
    if result < 0:
        raise ValidationError(f"{field} must be at least 0 seconds")
    return round(result, 3)


def validate_range(start: float, end: float | None) -> None:
    if end is not None and end < start:
        raise ValidationError("end_seconds must be greater than or equal to start_seconds")


def parse_timestamp(raw: str) -> float:
    value = raw.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, secs = parts
    elif len(parts) == 2:
        hours, minutes, secs = "0", parts[0], parts[1]
    else:
        raise ValidationError(f"Invalid subtitle timestamp: {raw}")
    try:
        return round(int(hours) * 3600 + int(minutes) * 60 + float(secs), 3)
    except ValueError:
        raise ValidationError(f"Invalid subtitle timestamp: {raw}") from None


def _parse_blocks(content: str, is_vtt: bool) -> list[tuple[float, float, str]]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[tuple[float, float, str]] = []
    timing = re.compile(
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})"
    )
    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if is_vtt and (lines[0].startswith("WEBVTT") or lines[0].startswith(("NOTE", "STYLE", "REGION"))):
            if lines[0].startswith("WEBVTT") and len(lines) > 1:
                lines = lines[1:]
            else:
                continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = timing.search(lines[timing_index])
        if not match:
            raise ValidationError(f"Invalid subtitle timing line: {lines[timing_index]}")
        start = parse_timestamp(match.group("start"))
        end = parse_timestamp(match.group("end"))
        validate_range(start, end)
        text = "\n".join(lines[timing_index + 1 :]).strip()
        if text:
            cues.append((start, end, text))
    if not cues:
        raise ValidationError("No valid subtitle cues were found")
    return cues


def parse_subtitles(content: str, filename: str) -> list[tuple[float, float, str]]:
    lower = filename.lower()
    is_vtt = lower.endswith(".vtt") or content.lstrip("\ufeff\n ").startswith("WEBVTT")
    if not is_vtt and not lower.endswith(".srt"):
        raise ValidationError("Only .srt and .vtt subtitle files are supported")
    return _parse_blocks(content, is_vtt)


def stable_cue_id(film_id: str, language: str, sequence_number: int, start: float, end: float) -> str:
    namespace = uuid.UUID(film_id)
    anchor = f"{language}:{sequence_number}:{start:.3f}:{end:.3f}"
    return str(uuid.uuid5(namespace, anchor))


def replace_subtitles(session, film: Film, content: str, filename: str, language: str) -> int:
    language = require_text(language or "und", "language", 40)
    parsed = parse_subtitles(content, filename)
    session.execute(delete(SubtitleCue).where(SubtitleCue.film_id == film.film_id))
    for index, (start, end, text) in enumerate(parsed, start=1):
        session.add(
            SubtitleCue(
                cue_id=stable_cue_id(film.film_id, language, index, start, end),
                film_id=film.film_id,
                sequence_number=index,
                start_seconds=start,
                end_seconds=end,
                text=text,
                language=language,
            )
        )
    film.subtitle_status = "ready"
    film.subtitle_language = language
    film.last_activity_at = utcnow()
    session.flush()
    return len(parsed)


def cue_dict(cue: SubtitleCue) -> dict[str, Any]:
    return {
        "cue_id": cue.cue_id,
        "sequence_number": cue.sequence_number,
        "start_seconds": cue.start_seconds,
        "end_seconds": cue.end_seconds,
        "text": cue.text,
        "language": cue.language,
    }


def progress_dict(progress: UserProgress | None) -> dict[str, Any] | None:
    if not progress:
        return None
    return {
        "film_id": progress.film_id,
        "actor": "user",
        "current_seconds": progress.current_seconds,
        "duration_seconds": progress.duration_seconds,
        "playback_state": progress.playback_state,
        "watch_intent": progress.watch_intent,
        "updated_at": iso(progress.updated_at),
    }


def xiaxia_progress_dict(state: XiaxiaViewingState | None) -> dict[str, Any] | None:
    if not state:
        return None
    return {
        "film_id": state.film_id,
        "actor": "xiaxia",
        "last_timestamp_seconds": state.last_timestamp_seconds,
        "last_subtitle_cue_id": state.last_subtitle_cue_id,
        "chunk_checkpoint": state.chunk_checkpoint,
        "completed": bool(state.completed),
        "updated_at": iso(state.updated_at),
    }


def subtitle_range(session, film_id: str) -> dict[str, Any]:
    row = session.execute(
        select(func.min(SubtitleCue.start_seconds), func.max(SubtitleCue.end_seconds), func.count())
        .where(SubtitleCue.film_id == film_id)
    ).one()
    count = int(row[2] or 0)
    return {
        "available": count > 0,
        "start_seconds": float(row[0]) if row[0] is not None else None,
        "end_seconds": float(row[1]) if row[1] is not None else None,
        "cue_count": count,
    }


def film_dict(session, film: Film, *, include_state: bool = False) -> dict[str, Any]:
    data = {
        "film_id": film.film_id,
        "title": film.title,
        "source_type": film.source_type,
        "source_url": film.source_url,
        "external_video_id": film.external_video_id,
        "duration_seconds": film.duration_seconds,
        "subtitle_status": film.subtitle_status,
        "subtitle_language": film.subtitle_language,
        "last_activity_at": iso(film.last_activity_at),
        "created_at": iso(film.created_at),
        "updated_at": iso(film.updated_at),
    }
    if include_state:
        user_progress = session.get(UserProgress, film.film_id)
        xiaxia_state = session.get(XiaxiaViewingState, film.film_id)
        data["subtitle_range"] = subtitle_range(session, film.film_id)
        data["user_progress"] = progress_dict(user_progress)
        data["xiaxia_viewing_state"] = xiaxia_progress_dict(xiaxia_state)
        data["copresence"] = derive_copresence(user_progress, xiaxia_state)
    return data


def annotation_dict(item: UserAnnotation) -> dict[str, Any]:
    return {
        "annotation_id": item.annotation_id,
        "film_id": item.film_id,
        "actor": "user",
        "content_type": "user_annotation",
        "start_seconds": item.start_seconds,
        "end_seconds": item.end_seconds,
        "cue_id": item.cue_id,
        "content": item.content,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def thought_dict(item: XiaxiaThought) -> dict[str, Any]:
    return {
        "thought_id": item.thought_id,
        "film_id": item.film_id,
        "actor": "xiaxia",
        "content_type": "xiaxia_thought",
        "trace_type": "permanent",
        "start_seconds": item.start_seconds,
        "end_seconds": item.end_seconds,
        "cue_id": item.cue_id,
        "content": item.content,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def reply_dict(item: XiaxiaReply) -> dict[str, Any]:
    return {
        "reply_id": item.reply_id,
        "annotation_id": item.annotation_id,
        "film_id": item.film_id,
        "actor": "xiaxia",
        "content_type": "xiaxia_reply",
        "start_seconds": item.start_seconds,
        "end_seconds": item.end_seconds,
        "cue_id": item.cue_id,
        "content": item.content,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def fleeting_trace_dict(item: FleetingTrace) -> dict[str, Any]:
    return {
        "trace_id": item.trace_id,
        "film_id": item.film_id,
        "actor": item.actor,
        "content_type": "fleeting_trace",
        "trace_type": "fleeting",
        "start_seconds": item.start_seconds,
        "end_seconds": item.end_seconds,
        "cue_id": item.cue_id,
        "content": item.content,
        "expires_at": iso(item.expires_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def new_trace_expiry() -> datetime:
    return utcnow() + timedelta(days=FLEETING_TRACE_RETENTION_DAYS)


def cleanup_expired_fleeting_traces(session) -> int:
    result = session.execute(delete(FleetingTrace).where(FleetingTrace.expires_at <= utcnow()))
    return int(result.rowcount or 0)


def derive_copresence(
    user_progress: UserProgress | None, xiaxia_state: XiaxiaViewingState | None
) -> dict[str, Any]:
    user_seconds = float(user_progress.current_seconds if user_progress else 0.0)
    xiaxia_seconds = float(xiaxia_state.last_timestamp_seconds if xiaxia_state else 0.0)
    difference = round(user_seconds - xiaxia_seconds, 3)
    distance = abs(difference)
    if user_seconds <= 1 and xiaxia_seconds <= 1:
        state, message = "not_started", "银幕还没有亮起来"
    elif distance <= TOGETHER_WINDOW_SECONDS:
        state, message = "together", "我们正在这里"
    elif distance <= NEARBY_WINDOW_SECONDS and difference > 0:
        state, message = "user_ahead", "🐶在前面一点"
    elif distance <= NEARBY_WINDOW_SECONDS:
        state, message = "xiaxia_ahead", "🐱在前面一点"
    elif difference > 0:
        state, message = "far_apart", "🐱正在追上来"
    else:
        state, message = "far_apart", "🐶正在追上来"
    return {
        "state": state,
        "message": message,
        "user_seconds": round(user_seconds, 3),
        "xiaxia_seconds": round(xiaxia_seconds, 3),
        "difference_seconds": difference,
        "together_window_seconds": TOGETHER_WINDOW_SECONDS,
    }


def _entry_reference(entry: dict[str, Any]) -> str:
    if entry["content_type"] == "user_annotation":
        return f"annotation:{entry['annotation_id']}"
    if entry["content_type"] == "xiaxia_thought":
        return f"thought:{entry['thought_id']}"
    if entry["content_type"] == "xiaxia_reply":
        return f"reply:{entry['reply_id']}"
    return f"fleeting:{entry['trace_id']}"


def derive_shared_stops(film_id: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_entries = [item for item in entries if item.get("actor") == "user"]
    xiaxia_entries = [item for item in entries if item.get("actor") == "xiaxia"]
    used_xiaxia: set[str] = set()
    stops: list[dict[str, Any]] = []
    namespace = uuid.UUID(film_id)
    for user_item in user_entries:
        candidates = [
            item for item in xiaxia_entries
            if _entry_reference(item) not in used_xiaxia
            and abs(float(item["start_seconds"]) - float(user_item["start_seconds"]))
            <= SHARED_STOP_WINDOW_SECONDS
        ]
        if not candidates:
            continue
        xiaxia_item = min(
            candidates,
            key=lambda item: abs(float(item["start_seconds"]) - float(user_item["start_seconds"])),
        )
        user_ref = _entry_reference(user_item)
        xiaxia_ref = _entry_reference(xiaxia_item)
        used_xiaxia.add(xiaxia_ref)
        anchor = f"shared-stop:{user_ref}:{xiaxia_ref}"
        start = min(float(user_item["start_seconds"]), float(xiaxia_item["start_seconds"]))
        end = max(float(user_item["start_seconds"]), float(xiaxia_item["start_seconds"]))
        stops.append(
            {
                "shared_stop_id": str(uuid.uuid5(namespace, anchor)),
                "film_id": film_id,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "anchor_seconds": round((start + end) / 2, 3),
                "user_trace_ref": user_ref,
                "xiaxia_trace_ref": xiaxia_ref,
                "label": "我们都在这里停过",
            }
        )
    return sorted(stops, key=lambda item: item["anchor_seconds"])


def validate_cue_for_film(session, cue_id: str | None, film_id: str) -> str | None:
    if not cue_id:
        return None
    cue = session.get(SubtitleCue, cue_id)
    if not cue or cue.film_id != film_id:
        raise ValidationError("cue_id does not belong to this film")
    return cue_id


def touch_film(film: Film) -> None:
    film.last_activity_at = utcnow()


def set_current_film(session, film_id: str | None) -> None:
    state = session.get(WatchState, 1)
    if not state:
        state = WatchState(singleton_id=1, current_film_id=film_id)
        session.add(state)
    else:
        state.current_film_id = film_id
        state.updated_at = utcnow()


def encode_continuation(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_continuation(token: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw)
    except Exception:
        raise ValidationError("Invalid continuation token") from None
    if not isinstance(payload, dict):
        raise ValidationError("Invalid continuation token")
    return payload
