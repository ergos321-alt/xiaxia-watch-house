from unittest.mock import patch

import pytest

import app as app_module


AUTH_HEADERS = {
    "Authorization": "Bearer regression-token",
}


@pytest.fixture()
def client():
    previous_token = app_module.SENSE_TOKEN
    app_module.SENSE_TOKEN = "regression-token"
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as test_client:
        yield test_client

    app_module.SENSE_TOKEN = previous_token


def current_context_fixture():
    return {
        "sensors": {},
        "semantic": {},
        "weather": {},
        "spatial": {"available": True},
        "reality": {
            "summary": {
                "location_quality": "good",
                "mobility": "stationary",
            },
            "inferences": {},
            "environment": {},
            "weather": {},
            "device": {},
            "network": {},
            "location": {"available": True},
            "spatial": {"available": True},
        },
        "phone_activity": {"available": True},
        "phone_activity_summary": {"current_app": "Test"},
    }


def test_stable_route_map_is_preserved():
    routes = {
        (rule.rule, method)
        for rule in app_module.app.url_map.iter_rules()
        for method in rule.methods
        if method not in {"HEAD", "OPTIONS"}
    }

    stable_v1_routes = {
        ("/static/<path:filename>", "GET"),
        ("/ping", "GET"),
        ("/data", "POST"),
        ("/phone/activity", "POST"),
        ("/context", "GET"),
        ("/context-check", "GET"),
        ("/context-check", "POST"),
        ("/phone-timeline-check", "GET"),
        ("/phone-timeline-check", "POST"),
        ("/reality/context", "GET"),
        ("/reality/summary", "GET"),
        ("/reality/environment", "GET"),
        ("/reality/device", "GET"),
        ("/reality/phone", "GET"),
        ("/reality/phone/timeline", "GET"),
        ("/reality/phone/history", "GET"),
        ("/reality/spatial", "GET"),
        ("/reality/spatial/history", "GET"),
        ("/reality/spatial/places", "GET"),
        ("/reality/spatial/places", "POST"),
        ("/reality/spatial/places/<name>", "GET"),
        ("/reality/spatial/places/<name>", "DELETE"),
        ("/reality/spatial/places/from-poi", "POST"),
        ("/reality/spatial/nearby", "GET"),
        ("/reality/spatial/route", "GET"),
        ("/reality/location", "GET"),
        ("/reality/status", "GET"),
        ("/hand/commands", "POST"),
        ("/hand/commands/next", "GET"),
        ("/hand/commands/<command_id>", "GET"),
        ("/hand/commands/<command_id>/result", "POST"),
    }

    v11_eye_routes = {
        ("/eye/requests", "POST"),
        ("/eye/requests/<request_id>", "GET"),
        ("/eye/device/requests/next", "GET"),
        ("/eye/device/requests/<request_id>/screen", "POST"),
        ("/eye/device/requests/<request_id>/failure", "POST"),
    }

    assert routes == stable_v1_routes | v11_eye_routes


def test_health_ping(client):
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


@pytest.mark.parametrize(
    "path",
    [
        "/context",
        "/reality/context",
        "/reality/summary",
        "/reality/environment",
        "/reality/device",
        "/reality/location",
        "/reality/phone",
    ],
)
def test_reality_context_family(client, path):
    with patch.object(
        app_module,
        "build_current_context",
        return_value=current_context_fixture(),
    ):
        response = client.get(path, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_phone_timeline(client):
    with patch.object(
        app_module,
        "build_phone_timeline",
        return_value=[{"event_type": "app"}],
    ):
        response = client.get(
            "/reality/phone/timeline?minutes=30&limit=10",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["event_count"] == 1
    assert response.get_json()["window_minutes"] == 30


def test_phone_history(client):
    time_range = {
        "start_epoch": 100,
        "end_epoch": 200,
        "start": "1970-01-01T00:01:40+00:00",
        "end": "1970-01-01T00:03:20+00:00",
        "query_mode": "absolute_range",
        "was_clamped": False,
        "max_window_minutes": 2880,
    }

    with (
        patch.object(
            app_module,
            "get_phone_history_time_range",
            return_value=(time_range, None),
        ),
        patch.object(
            app_module,
            "load_phone_history_events",
            return_value=[],
        ),
        patch.object(
            app_module,
            "build_phone_history_summary",
            return_value={"available": True},
        ),
    ):
        response = client.get(
            "/reality/phone/history",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["history"] == {"available": True}


def test_spatial_reality(client):
    with (
        patch.object(app_module, "load_latest_sensors", return_value={}),
        patch.object(app_module, "build_semantic_context", return_value={}),
        patch.object(
            app_module,
            "build_spatial_context",
            return_value={"available": True},
        ),
    ):
        response = client.get(
            "/reality/spatial",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["spatial"]["available"] is True


def test_spatial_history(client):
    with (
        patch.object(app_module, "load_spatial_history", return_value=[]),
        patch.object(app_module, "load_latest_sensors", return_value={}),
        patch.object(app_module, "build_semantic_context", return_value={}),
        patch.object(app_module, "get_activity_state", return_value=None),
        patch.object(
            app_module,
            "analyze_movement",
            return_value={"available": False},
        ),
        patch.object(app_module, "load_personal_places", return_value=[]),
        patch.object(app_module, "build_place_trends", return_value=[]),
    ):
        response = client.get(
            "/reality/spatial/history?minutes=30",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["point_count"] == 0


def test_personal_places(client):
    places = [{
        "name": "Home",
        "latitude": 23.1,
        "longitude": 113.3,
    }]

    with (
        patch.object(app_module, "load_personal_places", return_value=places),
        patch.object(app_module, "load_latest_sensors", return_value={}),
        patch.object(app_module, "build_semantic_context", return_value={}),
        patch.object(
            app_module,
            "latest_location_from_semantic",
            return_value=None,
        ),
    ):
        response = client.get(
            "/reality/spatial/places",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["count"] == 1
    assert response.get_json()["places"][0]["name"] == "Home"


def test_nearby(client):
    with (
        patch.object(app_module, "load_latest_sensors", return_value={}),
        patch.object(app_module, "build_semantic_context", return_value={}),
        patch.object(
            app_module,
            "latest_location_from_semantic",
            return_value={"latitude": 23.1, "longitude": 113.3},
        ),
        patch.object(
            app_module,
            "convert_gps_to_amap",
            return_value={
                "available": True,
                "latitude": 23.1,
                "longitude": 113.3,
            },
        ),
        patch.object(
            app_module,
            "nearby_search",
            return_value={"available": True, "pois": []},
        ),
    ):
        response = client.get(
            "/reality/spatial/nearby?radius=500",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["nearby"]["available"] is True


def test_route(client):
    with (
        patch.object(app_module, "load_latest_sensors", return_value={}),
        patch.object(app_module, "build_semantic_context", return_value={}),
        patch.object(
            app_module,
            "latest_location_from_semantic",
            return_value={"latitude": 23.1, "longitude": 113.3},
        ),
        patch.object(
            app_module,
            "amap_route",
            return_value={"available": True, "paths": []},
        ),
        patch.object(app_module, "haversine_m", return_value=1000.0),
        patch.object(
            app_module,
            "attach_route_summary",
            side_effect=lambda value: value,
        ),
    ):
        response = client.get(
            "/reality/spatial/route"
            "?latitude=23.2&longitude=113.4&mode=walking",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["route"]["available"] is True
    assert response.get_json()["route"]["destination_type"] == "coordinates"
