from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from flask import Flask, jsonify, request

from hand import (
    HAND_ACTIONS,
    register_hand_routes,
    validate_hand_command,
)


AUTH_HEADERS = {
    "Authorization": "Bearer test-token",
}


class FakeHandStore:
    def __init__(self):
        self.commands = []

    def create(self, action, parameters):
        now = datetime.now(timezone.utc)
        row = {
            "id": uuid4(),
            "action": action,
            "parameters": parameters,
            "status": "pending",
            "created_at": now,
            "delivered_at": None,
            "executed_at": None,
            "expires_at": now + timedelta(hours=24),
            "result": None,
            "error": None,
        }
        self.commands.append(row)
        return row

    def claim_next(self):
        for row in self.commands:
            if row["status"] == "pending":
                row["status"] = "delivered"
                row["delivered_at"] = datetime.now(timezone.utc)
                return row
        return None

    def get(self, command_id):
        for row in self.commands:
            if row["id"] == command_id:
                return row
        return None

    def finish(self, command_id, status, result, error):
        row = self.get(command_id)

        if row is None:
            return None, False, "command_not_found"

        if row["status"] == status:
            return row, True, None

        if row["status"] == "pending":
            return row, False, "command_not_delivered"

        if row["status"] == "expired":
            return row, False, "command_expired"

        if row["status"] in ("executed", "failed"):
            return row, False, "command_already_final"

        row["status"] = status
        row["result"] = result
        row["error"] = error
        row["executed_at"] = datetime.now(timezone.utc)
        return row, False, None


@pytest.fixture()
def hand_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    store = FakeHandStore()

    def check_token():
        if request.headers.get("Authorization") != "Bearer test-token":
            return jsonify({"error": "unauthorized"}), 401
        return None

    register_hand_routes(
        app,
        get_db=lambda: None,
        check_token=check_token,
        store=store,
    )

    return app.test_client(), store


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        ("flashlight", {"state": "on"}),
        ("volume", {"stream": "media", "level": 42}),
        ("open_app", {"app": "Spotify"}),
        ("timer", {"duration_seconds": 300, "label": "Tea"}),
        ("alarm", {"time": "07:30", "label": "Wake up"}),
        ("do_not_disturb", {"state": "off"}),
        ("battery_saver", {"state": "on"}),
        (
            "navigation",
            {
                "destination": "Guangzhou South Railway Station",
                "latitude": 22.989,
                "longitude": 113.269,
                "travel_mode": "driving",
            },
        ),
        ("knock", {"pattern": "xiaxia"}),
    ],
)
def test_all_whitelisted_actions_validate(action, parameters):
    normalized_action, normalized_parameters, errors = (
        validate_hand_command({
            "action": action,
            "parameters": parameters,
        })
    )

    assert errors == []
    assert normalized_action == action
    assert normalized_parameters


def test_whitelist_contains_only_v1_actions():
    assert HAND_ACTIONS == (
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


def test_create_flashlight_and_volume_commands(hand_client):
    client, store = hand_client

    flashlight = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "flashlight",
            "parameters": {"state": "on"},
        },
    )

    volume = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "volume",
            "parameters": {
                "stream": "media",
                "level": 65,
            },
        },
    )

    assert flashlight.status_code == 201
    assert flashlight.get_json()["status"] == "pending"
    assert UUID(flashlight.get_json()["command_id"])

    assert volume.status_code == 201
    assert volume.get_json()["status"] == "pending"
    assert len(store.commands) == 2


def test_illegal_action_and_parameters_are_rejected(hand_client):
    client, store = hand_client

    illegal_action = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "execute_anything",
            "parameters": {"script": "anything"},
        },
    )

    illegal_volume = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "volume",
            "parameters": {
                "stream": "ring",
                "level": 101,
            },
        },
    )

    assert illegal_action.status_code == 400
    assert illegal_action.get_json()["error"] == "invalid_parameters"
    assert illegal_volume.status_code == 400
    assert illegal_volume.get_json()["error"] == "invalid_parameters"
    assert store.commands == []


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"pattern": "urgent"},
        {"pattern": [100, 50, 100]},
        {"pattern": "xiaxia", "repeat": 2},
    ],
)
def test_knock_rejects_every_non_v11_pattern(parameters):
    action, normalized, errors = validate_hand_command({
        "action": "knock",
        "parameters": parameters,
    })

    assert action == "knock"
    assert errors


def test_knock_uses_existing_command_lifecycle(hand_client):
    client, _ = hand_client

    created = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "knock",
            "parameters": {"pattern": "xiaxia"},
        },
    )

    assert created.status_code == 201
    command_id = created.get_json()["command_id"]

    claimed = client.get(
        "/hand/commands/next",
        headers=AUTH_HEADERS,
    )

    assert claimed.get_json()["command"]["action"] == "knock"
    assert claimed.get_json()["command"]["parameters"] == {
        "pattern": "xiaxia",
    }

    completed = client.post(
        f"/hand/commands/{command_id}/result",
        headers=AUTH_HEADERS,
        json={
            "status": "executed",
            "result": {"tasker_task": "Xiaxia Knock"},
        },
    )

    assert completed.status_code == 200
    assert completed.get_json()["status"] == "executed"


def test_tasker_claim_result_status_and_idempotency(hand_client):
    client, _ = hand_client

    created = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "flashlight",
            "parameters": {"state": "off"},
        },
    ).get_json()

    command_id = created["command_id"]

    claimed = client.get(
        "/hand/commands/next",
        headers=AUTH_HEADERS,
    )

    assert claimed.status_code == 200
    assert claimed.get_json()["status"] == "delivered"
    assert claimed.get_json()["command"]["command_id"] == command_id
    assert claimed.get_json()["command"]["status"] == "delivered"

    empty = client.get(
        "/hand/commands/next",
        headers=AUTH_HEADERS,
    )

    assert empty.status_code == 200
    assert empty.get_json() == {
        "command": None,
        "status": "empty",
    }

    executed = client.post(
        f"/hand/commands/{command_id}/result",
        headers=AUTH_HEADERS,
        json={
            "status": "executed",
            "result": {"tasker_task": "Hand Flashlight"},
        },
    )

    assert executed.status_code == 200
    assert executed.get_json()["status"] == "executed"
    assert executed.get_json()["idempotent"] is False

    status = client.get(
        f"/hand/commands/{command_id}",
        headers=AUTH_HEADERS,
    )

    assert status.status_code == 200
    assert status.get_json()["status"] == "executed"
    assert status.get_json()["result"] == {
        "tasker_task": "Hand Flashlight",
    }

    repeated = client.post(
        f"/hand/commands/{command_id}/result",
        headers=AUTH_HEADERS,
        json={
            "status": "executed",
            "result": {},
        },
    )

    assert repeated.status_code == 200
    assert repeated.get_json()["idempotent"] is True

    conflicting = client.post(
        f"/hand/commands/{command_id}/result",
        headers=AUTH_HEADERS,
        json={
            "status": "failed",
            "result": {},
            "error": "late conflicting result",
        },
    )

    assert conflicting.status_code == 409
    assert conflicting.get_json()["error"] == "command_already_final"


def test_result_before_delivery_is_rejected(hand_client):
    client, _ = hand_client

    command_id = client.post(
        "/hand/commands",
        headers=AUTH_HEADERS,
        json={
            "action": "timer",
            "parameters": {"duration_seconds": 60},
        },
    ).get_json()["command_id"]

    response = client.post(
        f"/hand/commands/{command_id}/result",
        headers=AUTH_HEADERS,
        json={
            "status": "executed",
            "result": {},
        },
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "command_not_delivered"


def test_tasker_and_gpt_routes_require_bearer_auth(hand_client):
    client, _ = hand_client

    assert client.post(
        "/hand/commands",
        json={
            "action": "flashlight",
            "parameters": {"state": "on"},
        },
    ).status_code == 401

    assert client.get(
        "/hand/commands/next"
    ).status_code == 401
