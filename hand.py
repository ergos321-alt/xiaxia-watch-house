import re
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from flask import jsonify, request
from psycopg.types.json import Jsonb


HAND_ACTIONS = (
    "flashlight",
    "volume",
    "open_app",
    "timer",
    "alarm",
    "do_not_disturb",
    "battery_saver",
    "navigation",
    "knock",
)

HAND_STATUSES = (
    "pending",
    "delivered",
    "executed",
    "failed",
    "expired",
)

HAND_RESULT_STATUSES = (
    "executed",
    "failed",
)

NAVIGATION_TRAVEL_MODES = (
    "walking",
    "driving",
    "cycling",
    "electrobike",
)

HAND_COMMAND_TTL_SECONDS = 24 * 60 * 60
HAND_COMMAND_RETENTION_SECONDS = 7 * 24 * 60 * 60
HAND_CLEANUP_INTERVAL_SECONDS = 10 * 60

_last_hand_cleanup_epoch = 0

ALARM_TIME_PATTERN = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d$"
)


def ensure_hand_schema(conn):
    """Create the additive Hand table when the service first connects."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS hand_commands (
            id UUID PRIMARY KEY,

            action TEXT NOT NULL
                CHECK (action IN (
                    'flashlight',
                    'volume',
                    'open_app',
                    'timer',
                    'alarm',
                    'do_not_disturb',
                    'battery_saver',
                    'navigation',
                    'knock'
                )),

            parameters JSONB NOT NULL
                DEFAULT '{}'::jsonb,

            status TEXT NOT NULL
                DEFAULT 'pending'
                CHECK (status IN (
                    'pending',
                    'delivered',
                    'executed',
                    'failed',
                    'expired'
                )),

            created_at TIMESTAMPTZ NOT NULL,
            delivered_at TIMESTAMPTZ,
            executed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL,

            result JSONB,
            error TEXT
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_hand_commands_pending
        ON hand_commands (created_at, id)
        WHERE status = 'pending'
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_hand_commands_status_created
        ON hand_commands (status, created_at)
    """)


def _field_error(field, message):
    return {
        "field": field,
        "message": message,
    }


def _reject_unknown_keys(parameters, allowed_keys):
    return [
        _field_error(
            f"parameters.{key}",
            "unsupported parameter",
        )
        for key in sorted(
            set(parameters) - set(allowed_keys)
        )
    ]


def _normalize_required_string(
    parameters,
    key,
    errors,
    max_length=500,
):
    value = parameters.get(key)

    if not isinstance(value, str) or not value.strip():
        errors.append(
            _field_error(
                f"parameters.{key}",
                "must be a non-empty string",
            )
        )
        return None

    value = value.strip()

    if len(value) > max_length:
        errors.append(
            _field_error(
                f"parameters.{key}",
                f"must be at most {max_length} characters",
            )
        )
        return None

    return value


def _normalize_optional_label(parameters, normalized, errors):
    if "label" not in parameters:
        return

    label = parameters.get("label")

    if not isinstance(label, str):
        errors.append(
            _field_error(
                "parameters.label",
                "must be a string",
            )
        )
        return

    label = label.strip()

    if len(label) > 200:
        errors.append(
            _field_error(
                "parameters.label",
                "must be at most 200 characters",
            )
        )
        return

    normalized["label"] = label


def validate_hand_command(payload):
    """Validate and normalize the strict Xiaxia Hand V1 whitelist."""

    if not isinstance(payload, dict):
        return None, None, [
            _field_error(
                "$",
                "request body must be a JSON object",
            )
        ]

    errors = []

    for key in sorted(
        set(payload) - {"action", "parameters"}
    ):
        errors.append(
            _field_error(
                key,
                "unsupported request field",
            )
        )

    action = payload.get("action")

    if not isinstance(action, str):
        errors.append(
            _field_error(
                "action",
                "must be a supported action string",
            )
        )
        return None, None, errors

    action = action.strip().lower()

    if action not in HAND_ACTIONS:
        errors.append(
            _field_error(
                "action",
                "unsupported action",
            )
        )
        return None, None, errors

    parameters = payload.get("parameters")

    if not isinstance(parameters, dict):
        errors.append(
            _field_error(
                "parameters",
                "must be a JSON object",
            )
        )
        return action, None, errors

    normalized = {}

    if action in (
        "flashlight",
        "do_not_disturb",
        "battery_saver",
    ):
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"state"},
            )
        )

        state = parameters.get("state")

        if not isinstance(state, str):
            errors.append(
                _field_error(
                    "parameters.state",
                    "must be 'on' or 'off'",
                )
            )
        else:
            state = state.strip().lower()

            if state not in ("on", "off"):
                errors.append(
                    _field_error(
                        "parameters.state",
                        "must be 'on' or 'off'",
                    )
                )
            else:
                normalized["state"] = state

    elif action == "volume":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"stream", "level"},
            )
        )

        stream = parameters.get("stream")

        if not isinstance(stream, str):
            errors.append(
                _field_error(
                    "parameters.stream",
                    "must be 'media'",
                )
            )
        else:
            stream = stream.strip().lower()

            if stream != "media":
                errors.append(
                    _field_error(
                        "parameters.stream",
                        "must be 'media'",
                    )
                )
            else:
                normalized["stream"] = stream

        level = parameters.get("level")

        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 0 <= level <= 100
        ):
            errors.append(
                _field_error(
                    "parameters.level",
                    "must be an integer from 0 to 100",
                )
            )
        else:
            normalized["level"] = level

    elif action == "open_app":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"app"},
            )
        )

        app_name = _normalize_required_string(
            parameters,
            "app",
            errors,
            max_length=120,
        )

        if app_name is not None:
            normalized["app"] = app_name

    elif action == "timer":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"duration_seconds", "label"},
            )
        )

        duration = parameters.get("duration_seconds")

        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 1 <= duration <= 604800
        ):
            errors.append(
                _field_error(
                    "parameters.duration_seconds",
                    "must be an integer from 1 to 604800",
                )
            )
        else:
            normalized["duration_seconds"] = duration

        _normalize_optional_label(
            parameters,
            normalized,
            errors,
        )

    elif action == "alarm":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"time", "label"},
            )
        )

        alarm_time = parameters.get("time")

        if (
            not isinstance(alarm_time, str)
            or not ALARM_TIME_PATTERN.fullmatch(
                alarm_time.strip()
            )
        ):
            errors.append(
                _field_error(
                    "parameters.time",
                    "must use 24-hour device-local HH:MM format",
                )
            )
        else:
            normalized["time"] = alarm_time.strip()

        _normalize_optional_label(
            parameters,
            normalized,
            errors,
        )

    elif action == "knock":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {"pattern"},
            )
        )

        pattern = parameters.get("pattern")

        if not isinstance(pattern, str):
            errors.append(
                _field_error(
                    "parameters.pattern",
                    "must be 'xiaxia'",
                )
            )
        else:
            pattern = pattern.strip().lower()

            if pattern != "xiaxia":
                errors.append(
                    _field_error(
                        "parameters.pattern",
                        "must be 'xiaxia'",
                    )
                )
            else:
                normalized["pattern"] = pattern

    elif action == "navigation":
        errors.extend(
            _reject_unknown_keys(
                parameters,
                {
                    "destination",
                    "latitude",
                    "longitude",
                    "place_id",
                    "travel_mode",
                },
            )
        )

        destination = _normalize_required_string(
            parameters,
            "destination",
            errors,
        )

        if destination is not None:
            normalized["destination"] = destination

        has_latitude = "latitude" in parameters
        has_longitude = "longitude" in parameters

        if has_latitude != has_longitude:
            errors.append(
                _field_error(
                    "parameters.latitude",
                    "latitude and longitude must be supplied together",
                )
            )

        if has_latitude and has_longitude:
            latitude = parameters.get("latitude")
            longitude = parameters.get("longitude")

            valid_latitude = (
                not isinstance(latitude, bool)
                and isinstance(latitude, (int, float))
                and -90 <= latitude <= 90
            )

            valid_longitude = (
                not isinstance(longitude, bool)
                and isinstance(longitude, (int, float))
                and -180 <= longitude <= 180
            )

            if not valid_latitude:
                errors.append(
                    _field_error(
                        "parameters.latitude",
                        "must be a number from -90 to 90",
                    )
                )

            if not valid_longitude:
                errors.append(
                    _field_error(
                        "parameters.longitude",
                        "must be a number from -180 to 180",
                    )
                )

            if valid_latitude and valid_longitude:
                normalized["latitude"] = float(latitude)
                normalized["longitude"] = float(longitude)

        if "place_id" in parameters:
            place_id = _normalize_required_string(
                parameters,
                "place_id",
                errors,
                max_length=200,
            )

            if place_id is not None:
                normalized["place_id"] = place_id

        if "travel_mode" in parameters:
            travel_mode = parameters.get("travel_mode")

            if not isinstance(travel_mode, str):
                errors.append(
                    _field_error(
                        "parameters.travel_mode",
                        "must be a supported Spatial route mode",
                    )
                )
            else:
                travel_mode = travel_mode.strip().lower()

                if travel_mode not in NAVIGATION_TRAVEL_MODES:
                    errors.append(
                        _field_error(
                            "parameters.travel_mode",
                            "must be walking, driving, cycling, or electrobike",
                        )
                    )
                else:
                    normalized["travel_mode"] = travel_mode

    return action, normalized, errors


def validate_result_payload(payload):
    if not isinstance(payload, dict):
        return None, None, None, [
            _field_error(
                "$",
                "request body must be a JSON object",
            )
        ]

    errors = []

    for key in sorted(
        set(payload) - {"status", "result", "error"}
    ):
        errors.append(
            _field_error(
                key,
                "unsupported request field",
            )
        )

    status = payload.get("status")

    if status not in HAND_RESULT_STATUSES:
        errors.append(
            _field_error(
                "status",
                "must be 'executed' or 'failed'",
            )
        )

    result = payload.get("result", {})

    if not isinstance(result, dict):
        errors.append(
            _field_error(
                "result",
                "must be a JSON object",
            )
        )

    error = payload.get("error")

    if status == "failed":
        if not isinstance(error, str) or not error.strip():
            errors.append(
                _field_error(
                    "error",
                    "is required when status is 'failed'",
                )
            )
        else:
            error = error.strip()

    elif error not in (None, ""):
        errors.append(
            _field_error(
                "error",
                "must be omitted when status is 'executed'",
            )
        )
    else:
        error = None

    return status, result, error, errors


def parse_command_id(value):
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


def serialize_hand_command(row):
    return {
        "command_id": str(row["id"]),
        "action": row["action"],
        "parameters": row.get("parameters") or {},
        "status": row["status"],
        "created_at": _as_iso(row.get("created_at")),
        "delivered_at": _as_iso(row.get("delivered_at")),
        "executed_at": _as_iso(row.get("executed_at")),
        "expires_at": _as_iso(row.get("expires_at")),
        "result": row.get("result"),
        "error": row.get("error"),
    }


class PostgresHandStore:
    def __init__(self, get_db):
        self.get_db = get_db

    @staticmethod
    def _expire_stale(conn):
        global _last_hand_cleanup_epoch

        conn.execute("""
            UPDATE hand_commands
            SET
                status = 'expired',
                error = COALESCE(
                    error,
                    'command expired before execution'
                )
            WHERE status IN ('pending', 'delivered')
              AND expires_at <= CURRENT_TIMESTAMP
        """)

        # Hand polling is continuous, so use it as a lightweight housekeeping
        # heartbeat. Cleanup itself is throttled to once per 10 minutes per
        # worker and only removes commands that have been final for 7 days.
        now_epoch = int(time.time())

        if (
            _last_hand_cleanup_epoch
            and now_epoch - _last_hand_cleanup_epoch
            < HAND_CLEANUP_INTERVAL_SECONDS
        ):
            return

        retention_cutoff = (
            datetime.now(timezone.utc)
            - timedelta(seconds=HAND_COMMAND_RETENTION_SECONDS)
        )

        conn.execute("""
            DELETE FROM hand_commands
            WHERE status IN ('executed', 'failed', 'expired')
              AND COALESCE(executed_at, expires_at, created_at) < ?
        """, (
            retention_cutoff,
        ))

        _last_hand_cleanup_epoch = now_epoch

    def create(self, action, parameters):
        conn = self.get_db()
        command_id = uuid4()
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(
            seconds=HAND_COMMAND_TTL_SECONDS
        )

        try:
            row = conn.execute("""
                INSERT INTO hand_commands (
                    id,
                    action,
                    parameters,
                    status,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, 'pending', ?, ?)
                RETURNING *
            """, (
                command_id,
                action,
                Jsonb(parameters),
                created_at,
                expires_at,
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
            self._expire_stale(conn)

            row = conn.execute("""
                WITH next_command AS (
                    SELECT id
                    FROM hand_commands
                    WHERE status = 'pending'
                      AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY created_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE hand_commands AS command
                SET
                    status = 'delivered',
                    delivered_at = CURRENT_TIMESTAMP
                FROM next_command
                WHERE command.id = next_command.id
                RETURNING command.*
            """).fetchone()

            conn.commit()
            return row

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def get(self, command_id):
        conn = self.get_db()

        try:
            self._expire_stale(conn)

            row = conn.execute("""
                SELECT *
                FROM hand_commands
                WHERE id = ?
            """, (
                command_id,
            )).fetchone()

            conn.commit()
            return row

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def finish(
        self,
        command_id,
        status,
        result,
        error,
    ):
        conn = self.get_db()

        try:
            self._expire_stale(conn)

            current = conn.execute("""
                SELECT *
                FROM hand_commands
                WHERE id = ?
                FOR UPDATE
            """, (
                command_id,
            )).fetchone()

            if current is None:
                conn.commit()
                return None, False, "command_not_found"

            current_status = current["status"]

            if current_status == status:
                conn.commit()
                return current, True, None

            if current_status == "pending":
                conn.commit()
                return current, False, "command_not_delivered"

            if current_status == "expired":
                conn.commit()
                return current, False, "command_expired"

            if current_status in ("executed", "failed"):
                conn.commit()
                return current, False, "command_already_final"

            row = conn.execute("""
                UPDATE hand_commands
                SET
                    status = ?,
                    executed_at = CURRENT_TIMESTAMP,
                    result = ?,
                    error = ?
                WHERE id = ?
                  AND status = 'delivered'
                RETURNING *
            """, (
                status,
                Jsonb(result),
                error,
                command_id,
            )).fetchone()

            if row is None:
                conn.rollback()
                return current, False, "status_transition_conflict"

            conn.commit()
            return row, False, None

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()


def register_hand_routes(
    app,
    get_db,
    check_token,
    store=None,
):
    hand_store = store or PostgresHandStore(get_db)

    @app.route(
        "/hand/commands",
        methods=["POST"],
    )
    def hand_create_command():
        auth_error = check_token()

        if auth_error:
            return auth_error

        payload = request.get_json(silent=True)

        action, parameters, errors = (
            validate_hand_command(payload)
        )

        if errors:
            return jsonify({
                "error": "invalid_parameters",
                "details": errors,
            }), 400

        row = hand_store.create(
            action,
            parameters,
        )

        return jsonify({
            "command_id": str(row["id"]),
            "status": row["status"],
        }), 201

    @app.route(
        "/hand/commands/next",
        methods=["GET"],
    )
    def hand_next_command():
        auth_error = check_token()

        if auth_error:
            return auth_error

        row = hand_store.claim_next()

        if row is None:
            return jsonify({
                "status": "empty",
                "command": None,
            })

        return jsonify({
            "status": "delivered",
            "command": serialize_hand_command(row),
        })

    @app.route(
        "/hand/commands/<command_id>/result",
        methods=["POST"],
    )
    def hand_command_result(command_id):
        auth_error = check_token()

        if auth_error:
            return auth_error

        parsed_id = parse_command_id(command_id)

        if parsed_id is None:
            return jsonify({
                "error": "invalid_command_id",
            }), 400

        payload = request.get_json(silent=True)

        status, result, error, errors = (
            validate_result_payload(payload)
        )

        if errors:
            return jsonify({
                "error": "invalid_result",
                "details": errors,
            }), 400

        row, idempotent, transition_error = (
            hand_store.finish(
                parsed_id,
                status,
                result,
                error,
            )
        )

        if transition_error == "command_not_found":
            return jsonify({
                "error": transition_error,
            }), 404

        if transition_error:
            return jsonify({
                "error": transition_error,
                "command_id": str(parsed_id),
                "status": (
                    row.get("status")
                    if row
                    else None
                ),
            }), 409

        return jsonify({
            "command_id": str(row["id"]),
            "status": row["status"],
            "idempotent": idempotent,
        })

    @app.route(
        "/hand/commands/<command_id>",
        methods=["GET"],
    )
    def hand_command_status(command_id):
        auth_error = check_token()

        if auth_error:
            return auth_error

        parsed_id = parse_command_id(command_id)

        if parsed_id is None:
            return jsonify({
                "error": "invalid_command_id",
            }), 400

        row = hand_store.get(parsed_id)

        if row is None:
            return jsonify({
                "error": "command_not_found",
            }), 404

        return jsonify(
            serialize_hand_command(row)
        )
