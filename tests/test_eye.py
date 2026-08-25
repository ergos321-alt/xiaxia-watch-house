from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from flask import Flask, jsonify, request

from eye import (
    EYE_MAX_IMAGE_BYTES,
    PostgresEyeStore,
    register_eye_routes,
)
from vision import VisionProviderError
from vision import UnconfiguredVisionProvider


AUTH_HEADERS = {
    "Authorization": "Bearer test-token",
}

PNG_BYTES = b"\x89PNG\r\n\x1a\nminimal-test-payload"

FACTS = {
    "scene": "An Android settings screen is visible.",
    "visible_people": [],
    "actions": [],
    "objects": ["settings list"],
    "screen_text": ["Settings"],
    "uncertainties": [],
}


class FakeEyeStore:
    def __init__(self):
        self.rows = []
        self.transitions = []

    def create(self, frame_count, focus):
        now = datetime.now(timezone.utc)
        row = {
            "id": uuid4(),
            "request_type": "screen",
            "frame_count": frame_count,
            "focus": focus,
            "status": "pending",
            "created_at": now,
            "claimed_at": None,
            "uploaded_at": None,
            "analysis_started_at": None,
            "completed_at": None,
            "updated_at": now,
            "expires_at": now + timedelta(minutes=10),
            "result_expires_at": now + timedelta(hours=24),
            "visual_facts": None,
            "error_code": None,
            "error_message": None,
        }
        self.rows.append(row)
        self.transitions.append("pending")
        return row

    def get(self, request_id):
        for row in self.rows:
            if row["id"] == request_id:
                if (
                    row["status"] in (
                        "pending",
                        "capturing",
                        "uploaded",
                        "analyzing",
                    )
                    and row["expires_at"] <= datetime.now(timezone.utc)
                ):
                    row["status"] = "expired"
                    row["completed_at"] = datetime.now(timezone.utc)
                    row["updated_at"] = datetime.now(timezone.utc)
                    row["error_code"] = "request_expired"
                    row["error_message"] = (
                        "Eye request expired before completion."
                    )
                return row
        return None

    def claim_next(self):
        for row in self.rows:
            if row["status"] == "pending":
                row["status"] = "capturing"
                row["claimed_at"] = datetime.now(timezone.utc)
                row["updated_at"] = row["claimed_at"]
                self.transitions.append("capturing")
                return row
        return None

    def _transition(self, request_id, allowed, target):
        row = self.get(request_id)

        if row is None:
            return None, "eye_request_not_found"

        if row["status"] not in allowed:
            return row, "eye_status_transition_conflict"

        row["status"] = target
        row["updated_at"] = datetime.now(timezone.utc)
        self.transitions.append(target)
        return row, None

    def mark_uploaded(self, request_id):
        row, error = self._transition(
            request_id,
            ("capturing",),
            "uploaded",
        )

        if row is not None and error is None:
            row["uploaded_at"] = datetime.now(timezone.utc)
        return row, error

    def mark_analyzing(self, request_id):
        row, error = self._transition(
            request_id,
            ("uploaded",),
            "analyzing",
        )

        if row is not None and error is None:
            row["analysis_started_at"] = datetime.now(timezone.utc)
        return row, error

    def complete(self, request_id, visual_facts):
        row, error = self._transition(
            request_id,
            ("analyzing",),
            "completed",
        )

        if row is not None and error is None:
            row["completed_at"] = datetime.now(timezone.utc)
            row["visual_facts"] = visual_facts
        return row, error

    def fail(self, request_id, error_code, error_message):
        row = self.get(request_id)

        if row is None:
            return None, "eye_request_not_found"

        if row["status"] == "failed":
            return row, None

        row, error = self._transition(
            request_id,
            ("capturing", "uploaded", "analyzing"),
            "failed",
        )

        if row is not None and error is None:
            row["completed_at"] = datetime.now(timezone.utc)
            row["visual_facts"] = None
            row["error_code"] = error_code
            row["error_message"] = error_message
        return row, error


class FakeVisionProvider:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def analyze(self, image_bytes, mime_type, focus=None):
        self.calls.append({
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "focus": focus,
        })

        if self.error is not None:
            raise self.error

        return FACTS


def make_client(provider=None):
    app = Flask(__name__)
    app.config["TESTING"] = True
    store = FakeEyeStore()
    provider = provider or FakeVisionProvider()

    def check_token():
        if request.headers.get("Authorization") != "Bearer test-token":
            return jsonify({"error": "unauthorized"}), 401
        return None

    register_eye_routes(
        app,
        get_db=lambda: None,
        check_token=check_token,
        store=store,
        vision_provider=provider,
    )

    return app.test_client(), store, provider


def create_and_claim(client, focus=None):
    body = {"frame_count": 1}

    if focus is not None:
        body["focus"] = focus

    created = client.post(
        "/eye/requests",
        headers=AUTH_HEADERS,
        json=body,
    )
    request_id = created.get_json()["request_id"]
    claimed = client.get(
        "/eye/device/requests/next",
        headers=AUTH_HEADERS,
    )

    assert created.status_code == 201
    assert UUID(request_id)
    assert claimed.get_json()["status"] == "capturing"
    return request_id


def test_eye_create_claim_upload_complete_and_query():
    client, store, provider = make_client()
    request_id = create_and_claim(
        client,
        focus="Read the visible error message",
    )

    uploaded = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers={
            **AUTH_HEADERS,
            "Content-Type": "image/png",
        },
        data=PNG_BYTES,
    )

    assert uploaded.status_code == 200
    assert uploaded.get_json()["status"] == "completed"
    assert provider.calls == [{
        "image_bytes": PNG_BYTES,
        "mime_type": "image/png",
        "focus": "Read the visible error message",
    }]

    queried = client.get(
        f"/eye/requests/{request_id}",
        headers=AUTH_HEADERS,
    )

    assert queried.status_code == 200
    assert queried.get_json()["status"] == "completed"
    assert queried.get_json()["visual_facts"] == FACTS
    assert [row["status"] for row in store.rows] == ["completed"]
    assert store.transitions == [
        "pending",
        "capturing",
        "uploaded",
        "analyzing",
        "completed",
    ]

    # The store contains structured facts only, never raw screenshot bytes,
    # storage object keys, or public URLs.
    assert "image" not in store.rows[0]
    assert "image_bytes" not in store.rows[0]
    assert "storage_path" not in store.rows[0]


def test_eye_accepts_multipart_screen_upload():
    client, _, _ = make_client()
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers=AUTH_HEADERS,
        data={
            "screen": (
                BytesIO(PNG_BYTES),
                "screen.png",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"


def test_eye_without_screenshot_never_creates_visual_facts():
    client, store, provider = make_client()
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers=AUTH_HEADERS,
        data=b"",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "screen_image_required"
    assert store.rows[0]["status"] == "capturing"
    assert store.rows[0]["visual_facts"] is None
    assert provider.calls == []


def test_eye_device_failure_is_observable_without_visual_facts():
    client, store, _ = make_client()
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/failure",
        headers=AUTH_HEADERS,
        json={
            "error_code": "secure_screen",
            "message": "The foreground app blocks screenshots.",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "failed"
    assert store.rows[0]["visual_facts"] is None

    queried = client.get(
        f"/eye/requests/{request_id}",
        headers=AUTH_HEADERS,
    ).get_json()

    assert queried["error"] == {
        "code": "secure_screen",
        "message": "The foreground app blocks screenshots.",
    }


def test_vision_provider_failure_marks_request_failed():
    provider = FakeVisionProvider(
        VisionProviderError(
            "vision_provider_unavailable",
            "Vision provider could not be reached.",
        )
    )
    client, store, _ = make_client(provider)
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers={
            **AUTH_HEADERS,
            "Content-Type": "image/png",
        },
        data=PNG_BYTES,
    )

    assert response.status_code == 502
    assert response.get_json()["status"] == "failed"
    assert store.rows[0]["visual_facts"] is None
    assert store.rows[0]["error_code"] == "vision_provider_unavailable"


def test_unconfigured_provider_is_explicit_failure_not_mock_success():
    client, store, _ = make_client(UnconfiguredVisionProvider())
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers={
            **AUTH_HEADERS,
            "Content-Type": "image/png",
        },
        data=PNG_BYTES,
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "vision_provider_not_configured"
    assert store.rows[0]["status"] == "failed"
    assert store.rows[0]["visual_facts"] is None


def test_eye_expired_request_is_visible_and_not_claimed():
    client, store, _ = make_client()
    created = client.post(
        "/eye/requests",
        headers=AUTH_HEADERS,
        json={},
    ).get_json()

    store.rows[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )

    queried = client.get(
        f"/eye/requests/{created['request_id']}",
        headers=AUTH_HEADERS,
    )

    assert queried.get_json()["status"] == "expired"
    assert queried.get_json()["visual_facts"] is None

    empty = client.get(
        "/eye/device/requests/next",
        headers=AUTH_HEADERS,
    )
    assert empty.get_json() == {
        "request": None,
        "status": "empty",
    }


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"frame_count": 2},
        {"frame_count": True},
        {"unknown": "field"},
        {"focus": "x" * 301},
    ],
)
def test_eye_rejects_invalid_create_payloads(body):
    client, store, _ = make_client()

    response = client.post(
        "/eye/requests",
        headers=AUTH_HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_eye_request"
    assert store.rows == []


def test_eye_routes_require_existing_bearer_auth():
    client, _, _ = make_client()

    assert client.post(
        "/eye/requests",
        json={},
    ).status_code == 401
    assert client.get(
        "/eye/device/requests/next"
    ).status_code == 401
    assert client.post(
        f"/eye/device/requests/{uuid4()}/failure",
        json={
            "error_code": "capture_failed",
        },
    ).status_code == 401


def test_eye_rejects_oversized_raw_upload_before_provider_call():
    client, _, provider = make_client()
    request_id = create_and_claim(client)

    response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers={
            **AUTH_HEADERS,
            "Content-Type": "image/png",
        },
        data=PNG_BYTES[:8] + b"x" * EYE_MAX_IMAGE_BYTES,
    )

    assert response.status_code == 413
    assert provider.calls == []


def test_eye_rejects_invalid_image_and_device_failure_payload():
    client, store, provider = make_client()
    request_id = create_and_claim(client)

    image_response = client.post(
        f"/eye/device/requests/{request_id}/screen",
        headers={
            **AUTH_HEADERS,
            "Content-Type": "application/octet-stream",
        },
        data=b"not-an-image",
    )
    failure_response = client.post(
        f"/eye/device/requests/{request_id}/failure",
        headers=AUTH_HEADERS,
        json={
            "error_code": "bypass_secure_screen",
        },
    )

    assert image_response.status_code == 400
    assert image_response.get_json()["error"] == "unsupported_image"
    assert failure_response.status_code == 400
    assert failure_response.get_json()["error"] == "invalid_device_failure"
    assert store.rows[0]["status"] == "capturing"
    assert provider.calls == []


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)


def test_postgres_housekeeping_expires_active_and_deletes_retained_rows():
    conn = RecordingConnection()

    PostgresEyeStore._housekeeping(conn)

    sql = "\n".join(conn.statements)
    assert "status = 'expired'" in sql
    assert "expires_at <= CURRENT_TIMESTAMP" in sql
    assert "DELETE FROM eye_requests" in sql
    assert "result_expires_at <= CURRENT_TIMESTAMP" in sql
