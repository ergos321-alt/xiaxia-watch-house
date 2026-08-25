import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from flask import jsonify, request
from psycopg.types.json import Jsonb

from vision import (
    VisionProviderError,
    build_vision_provider,
)


EYE_STATUSES = (
    "pending",
    "capturing",
    "uploaded",
    "analyzing",
    "completed",
    "failed",
    "expired",
)

EYE_ACTIVE_STATUSES = (
    "pending",
    "capturing",
    "uploaded",
    "analyzing",
)

EYE_TERMINAL_STATUSES = (
    "completed",
    "failed",
    "expired",
)

EYE_DEVICE_ERROR_CODES = (
    "screenshot_permission_denied",
    "screenshot_blocked",
    "secure_screen",
    "capture_failed",
    "device_error",
)

EYE_REQUEST_TTL_SECONDS = 10 * 60
EYE_RESULT_RETENTION_SECONDS = 24 * 60 * 60
EYE_CLEANUP_INTERVAL_SECONDS = 10 * 60
EYE_MAX_IMAGE_BYTES = 8 * 1024 * 1024

_last_eye_cleanup_epoch = 0


def ensure_eye_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eye_requests (
            id UUID PRIMARY KEY,
            request_type TEXT NOT NULL
                DEFAULT 'screen'
                CHECK (request_type = 'screen'),
            frame_count SMALLINT NOT NULL
                DEFAULT 1
                CHECK (frame_count BETWEEN 1 AND 3),
            focus TEXT,
            status TEXT NOT NULL
                DEFAULT 'pending'
                CHECK (status IN (
                    'pending',
                    'capturing',
                    'uploaded',
                    'analyzing',
                    'completed',
                    'failed',
                    'expired'
                )),
            created_at TIMESTAMPTZ NOT NULL,
            claimed_at TIMESTAMPTZ,
            uploaded_at TIMESTAMPTZ,
            analysis_started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            result_expires_at TIMESTAMPTZ NOT NULL,
            visual_facts JSONB,
            error_code TEXT,
            error_message TEXT
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_eye_requests_pending
        ON eye_requests (created_at, id)
        WHERE status = 'pending'
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_eye_requests_status_updated
        ON eye_requests (status, updated_at)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_eye_requests_result_expiry
        ON eye_requests (result_expires_at)
        WHERE status IN ('completed', 'failed', 'expired')
    """)


def _field_error(field, message):
    return {
        "field": field,
        "message": message,
    }


def validate_eye_request(payload):
    if not isinstance(payload, dict):
        return None, None, [
            _field_error(
                "$",
                "request body must be a JSON object",
            )
        ]

    errors = []

    for key in sorted(
        set(payload) - {"frame_count", "focus"}
    ):
        errors.append(
            _field_error(
                key,
                "unsupported request field",
            )
        )

    frame_count = payload.get("frame_count", 1)

    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count != 1
    ):
        errors.append(
            _field_error(
                "frame_count",
                "Screen Sense V1 supports exactly one frame",
            )
        )

    focus = payload.get("focus")

    if focus is not None:
        if not isinstance(focus, str):
            errors.append(
                _field_error(
                    "focus",
                    "must be a string",
                )
            )
        else:
            focus = focus.strip()

            if len(focus) > 300:
                errors.append(
                    _field_error(
                        "focus",
                        "must be at most 300 characters",
                    )
                )

            if not focus:
                focus = None

    return frame_count, focus, errors


def validate_device_failure(payload):
    if not isinstance(payload, dict):
        return None, None, [
            _field_error(
                "$",
                "request body must be a JSON object",
            )
        ]

    errors = []

    for key in sorted(
        set(payload) - {"error_code", "message"}
    ):
        errors.append(
            _field_error(
                key,
                "unsupported request field",
            )
        )

    error_code = payload.get("error_code")

    if error_code not in EYE_DEVICE_ERROR_CODES:
        errors.append(
            _field_error(
                "error_code",
                "must be a supported device capture error",
            )
        )

    message = payload.get("message")

    if message is not None:
        if not isinstance(message, str):
            errors.append(
                _field_error(
                    "message",
                    "must be a string",
                )
            )
        else:
            message = message.strip()[:500]

    return error_code, message, errors


def parse_eye_request_id(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _as_iso(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    return str(value)


def serialize_eye_request(row):
    error = None

    if row.get("error_code") or row.get("error_message"):
        error = {
            "code": row.get("error_code"),
            "message": row.get("error_message"),
        }

    return {
        "request_id": str(row["id"]),
        "request_type": row.get("request_type", "screen"),
        "frame_count": row.get("frame_count", 1),
        "focus": row.get("focus"),
        "status": row["status"],
        "created_at": _as_iso(row.get("created_at")),
        "claimed_at": _as_iso(row.get("claimed_at")),
        "uploaded_at": _as_iso(row.get("uploaded_at")),
        "analysis_started_at": _as_iso(
            row.get("analysis_started_at")
        ),
        "completed_at": _as_iso(row.get("completed_at")),
        "updated_at": _as_iso(row.get("updated_at")),
        "expires_at": _as_iso(row.get("expires_at")),
        "result_expires_at": _as_iso(
            row.get("result_expires_at")
        ),
        "visual_facts": row.get("visual_facts"),
        "error": error,
    }


def detect_image_mime(image_bytes):
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    if (
        len(image_bytes) >= 12
        and image_bytes[:4] == b"RIFF"
        and image_bytes[8:12] == b"WEBP"
    ):
        return "image/webp"

    return None


class PostgresEyeStore:
    def __init__(self, get_db):
        self.get_db = get_db

    @staticmethod
    def _housekeeping(conn):
        global _last_eye_cleanup_epoch

        conn.execute("""
            UPDATE eye_requests
            SET
                status = 'expired',
                completed_at = COALESCE(
                    completed_at,
                    CURRENT_TIMESTAMP
                ),
                updated_at = CURRENT_TIMESTAMP,
                error_code = COALESCE(
                    error_code,
                    'request_expired'
                ),
                error_message = COALESCE(
                    error_message,
                    'Eye request expired before completion.'
                )
            WHERE status IN (
                'pending',
                'capturing',
                'uploaded',
                'analyzing'
            )
              AND expires_at <= CURRENT_TIMESTAMP
        """)

        now_epoch = int(time.time())

        if (
            _last_eye_cleanup_epoch
            and now_epoch - _last_eye_cleanup_epoch
            < EYE_CLEANUP_INTERVAL_SECONDS
        ):
            return

        conn.execute("""
            DELETE FROM eye_requests
            WHERE status IN ('completed', 'failed', 'expired')
              AND result_expires_at <= CURRENT_TIMESTAMP
        """)

        _last_eye_cleanup_epoch = now_epoch

    def create(self, frame_count, focus):
        conn = self.get_db()
        request_id = uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(
            seconds=EYE_REQUEST_TTL_SECONDS
        )
        result_expires_at = now + timedelta(
            seconds=EYE_RESULT_RETENTION_SECONDS
        )

        try:
            self._housekeeping(conn)

            row = conn.execute("""
                INSERT INTO eye_requests (
                    id,
                    request_type,
                    frame_count,
                    focus,
                    status,
                    created_at,
                    updated_at,
                    expires_at,
                    result_expires_at
                )
                VALUES (?, 'screen', ?, ?, 'pending', ?, ?, ?, ?)
                RETURNING *
            """, (
                request_id,
                frame_count,
                focus,
                now,
                now,
                expires_at,
                result_expires_at,
            )).fetchone()

            conn.commit()
            return row

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def claim_next(self):
        conn = self.get_db()

        try:
            self._housekeeping(conn)

            row = conn.execute("""
                WITH next_request AS (
                    SELECT id
                    FROM eye_requests
                    WHERE status = 'pending'
                      AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY created_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE eye_requests AS eye_request
                SET
                    status = 'capturing',
                    claimed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                FROM next_request
                WHERE eye_request.id = next_request.id
                RETURNING eye_request.*
            """).fetchone()

            conn.commit()
            return row

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def get(self, request_id):
        conn = self.get_db()

        try:
            self._housekeeping(conn)

            row = conn.execute("""
                SELECT *
                FROM eye_requests
                WHERE id = ?
            """, (
                request_id,
            )).fetchone()

            conn.commit()
            return row

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def _transition(
        self,
        request_id,
        allowed_statuses,
        target_status,
        assignments,
        assignment_values=(),
    ):
        conn = self.get_db()

        try:
            self._housekeeping(conn)

            current = conn.execute("""
                SELECT *
                FROM eye_requests
                WHERE id = ?
                FOR UPDATE
            """, (
                request_id,
            )).fetchone()

            if current is None:
                conn.commit()
                return None, "eye_request_not_found"

            current_status = current["status"]

            if current_status not in allowed_statuses:
                conn.commit()
                return current, "eye_status_transition_conflict"

            row = conn.execute(f"""
                UPDATE eye_requests
                SET
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    {assignments}
                WHERE id = ?
                  AND status = ?
                RETURNING *
            """, (
                target_status,
                *assignment_values,
                request_id,
                current_status,
            )).fetchone()

            if row is None:
                conn.rollback()
                return current, "eye_status_transition_conflict"

            conn.commit()
            return row, None

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def mark_uploaded(self, request_id):
        return self._transition(
            request_id,
            ("capturing",),
            "uploaded",
            "uploaded_at = CURRENT_TIMESTAMP",
        )

    def mark_analyzing(self, request_id):
        return self._transition(
            request_id,
            ("uploaded",),
            "analyzing",
            "analysis_started_at = CURRENT_TIMESTAMP",
        )

    def complete(self, request_id, visual_facts):
        return self._transition(
            request_id,
            ("analyzing",),
            "completed",
            (
                "completed_at = CURRENT_TIMESTAMP, "
                "visual_facts = ?, "
                "error_code = NULL, "
                "error_message = NULL"
            ),
            (Jsonb(visual_facts),),
        )

    def fail(self, request_id, error_code, error_message):
        current = self.get(request_id)

        if current is None:
            return None, "eye_request_not_found"

        if current["status"] == "failed":
            return current, None

        return self._transition(
            request_id,
            ("capturing", "uploaded", "analyzing"),
            "failed",
            (
                "completed_at = CURRENT_TIMESTAMP, "
                "visual_facts = NULL, "
                "error_code = ?, "
                "error_message = ?"
            ),
            (error_code, error_message),
        )


def _transition_error_response(error, row=None):
    if error == "eye_request_not_found":
        return jsonify({
            "error": error,
        }), 404

    return jsonify({
        "error": error,
        "status": row.get("status") if row else None,
    }), 409


def _read_screen_image():
    content_length = request.content_length

    if (
        content_length is not None
        and content_length > EYE_MAX_IMAGE_BYTES + 1024 * 1024
    ):
        return None, None, "image_too_large"

    upload = request.files.get("screen")

    if upload is not None:
        image_bytes = upload.stream.read(
            EYE_MAX_IMAGE_BYTES + 1
        )
    else:
        image_bytes = request.stream.read(
            EYE_MAX_IMAGE_BYTES + 1
        )

    if not image_bytes:
        return None, None, "screen_image_required"

    if len(image_bytes) > EYE_MAX_IMAGE_BYTES:
        return None, None, "image_too_large"

    mime_type = detect_image_mime(image_bytes)

    if mime_type is None:
        return None, None, "unsupported_image"

    return image_bytes, mime_type, None


def register_eye_routes(
    app,
    get_db,
    check_token,
    store=None,
    vision_provider=None,
):
    eye_store = store or PostgresEyeStore(get_db)
    provider = (
        vision_provider
        if vision_provider is not None
        else build_vision_provider()
    )

    @app.route(
        "/eye/requests",
        methods=["POST"],
    )
    def eye_create_request():
        auth_error = check_token()

        if auth_error:
            return auth_error

        payload = request.get_json(silent=True)
        frame_count, focus, errors = (
            validate_eye_request(payload)
        )

        if errors:
            return jsonify({
                "error": "invalid_eye_request",
                "details": errors,
            }), 400

        row = eye_store.create(
            frame_count,
            focus,
        )

        return jsonify({
            "request_id": str(row["id"]),
            "status": row["status"],
            "expires_at": _as_iso(row.get("expires_at")),
        }), 201

    @app.route(
        "/eye/requests/<request_id>",
        methods=["GET"],
    )
    def eye_get_request(request_id):
        auth_error = check_token()

        if auth_error:
            return auth_error

        parsed_id = parse_eye_request_id(request_id)

        if parsed_id is None:
            return jsonify({
                "error": "invalid_eye_request_id",
            }), 400

        row = eye_store.get(parsed_id)

        if row is None:
            return jsonify({
                "error": "eye_request_not_found",
            }), 404

        return jsonify(
            serialize_eye_request(row)
        )

    @app.route(
        "/eye/device/requests/next",
        methods=["GET"],
    )
    def eye_device_next_request():
        auth_error = check_token()

        if auth_error:
            return auth_error

        row = eye_store.claim_next()

        if row is None:
            return jsonify({
                "status": "empty",
                "request": None,
            })

        return jsonify({
            "status": "capturing",
            "request": serialize_eye_request(row),
        })

    @app.route(
        "/eye/device/requests/<request_id>/screen",
        methods=["POST"],
    )
    def eye_device_upload_screen(request_id):
        auth_error = check_token()

        if auth_error:
            return auth_error

        parsed_id = parse_eye_request_id(request_id)

        if parsed_id is None:
            return jsonify({
                "error": "invalid_eye_request_id",
            }), 400

        image_bytes, mime_type, image_error = (
            _read_screen_image()
        )

        if image_error:
            status_code = (
                413
                if image_error == "image_too_large"
                else 400
            )
            return jsonify({
                "error": image_error,
            }), status_code

        row, transition_error = eye_store.mark_uploaded(
            parsed_id
        )

        if transition_error:
            return _transition_error_response(
                transition_error,
                row,
            )

        row, transition_error = eye_store.mark_analyzing(
            parsed_id
        )

        if transition_error:
            return _transition_error_response(
                transition_error,
                row,
            )

        try:
            visual_facts = provider.analyze(
                image_bytes,
                mime_type,
                focus=row.get("focus"),
            )

            row, transition_error = eye_store.complete(
                parsed_id,
                visual_facts,
            )

            if transition_error:
                return _transition_error_response(
                    transition_error,
                    row,
                )

            return jsonify({
                "request_id": str(row["id"]),
                "status": row["status"],
            })

        except VisionProviderError as error:
            row, _ = eye_store.fail(
                parsed_id,
                error.code,
                error.message,
            )

            status_code = (
                503
                if error.code in (
                    "vision_provider_not_configured",
                    "unsupported_vision_provider",
                )
                else 502
            )

            return jsonify({
                "request_id": str(parsed_id),
                "status": row.get("status") if row else "failed",
                "error": error.code,
            }), status_code

        except Exception:
            row, _ = eye_store.fail(
                parsed_id,
                "vision_analysis_failed",
                "Vision analysis failed unexpectedly.",
            )

            return jsonify({
                "request_id": str(parsed_id),
                "status": row.get("status") if row else "failed",
                "error": "vision_analysis_failed",
            }), 502

        finally:
            image_bytes = b""
            del image_bytes

    @app.route(
        "/eye/device/requests/<request_id>/failure",
        methods=["POST"],
    )
    def eye_device_capture_failure(request_id):
        auth_error = check_token()

        if auth_error:
            return auth_error

        parsed_id = parse_eye_request_id(request_id)

        if parsed_id is None:
            return jsonify({
                "error": "invalid_eye_request_id",
            }), 400

        payload = request.get_json(silent=True)
        error_code, message, errors = (
            validate_device_failure(payload)
        )

        if errors:
            return jsonify({
                "error": "invalid_device_failure",
                "details": errors,
            }), 400

        row, transition_error = eye_store.fail(
            parsed_id,
            error_code,
            message or "Android screen capture failed.",
        )

        if transition_error:
            return _transition_error_response(
                transition_error,
                row,
            )

        return jsonify({
            "request_id": str(row["id"]),
            "status": row["status"],
        })
