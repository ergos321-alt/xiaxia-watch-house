from __future__ import annotations

import importlib
import json
from typing import Any

import pytest
from starlette.testclient import TestClient


EXPECTED_TOOLS = {
    "list_videos",
    "get_video",
    "get_watch_state",
    "get_current_context",
    "get_transcript",
    "list_annotations",
    "list_thoughts",
    "create_thought",
    "list_fleeting_traces",
    "create_fleeting_trace",
    "create_reply",
    "update_xiaxia_progress",
}


def _message(response):
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"MCP response did not include a message: {response.text}")


@pytest.fixture(scope="module")
def mcp_server(tmp_path_factory):
    import os

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path_factory.mktemp('watch-mcp') / 'mcp-watch-test.sqlite3'}",
    )
    monkeypatch.setenv("SESSION_SECRET", "local-test-secret")
    monkeypatch.setenv("ACTION_BEARER_TOKEN", "local-test-token")
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("WATCH_PUBLIC_HOST", "testserver")
    monkeypatch.setenv("PORT", "10000")
    module = importlib.import_module("mcp_app")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    client_context = TestClient(module.app)
    client = client_context.__enter__()
    initialize = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "watch-house-tests", "version": "1"},
            },
        },
        headers=headers,
    )
    assert initialize.status_code == 200
    assert initialize.headers["content-type"].startswith("text/event-stream")
    assert _message(initialize)["result"]["serverInfo"]["name"] == "Xiaxia Watching House"
    headers["Mcp-Session-Id"] = initialize.headers["Mcp-Session-Id"]
    headers["MCP-Protocol-Version"] = "2025-06-18"
    initialized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    assert initialized.status_code == 202
    yield module, client, headers
    client_context.__exit__(None, None, None)
    monkeypatch.undo()


def test_mcp_initialize_and_discovery_matches_action_operations(mcp_server):
    _, client, headers = mcp_server
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=headers,
    )
    assert response.status_code == 200
    tools = _message(response)["result"]["tools"]
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
    assert len(tools) == 12

    schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
    assert schemas["get_transcript"]["required"] == ["film_id"]
    assert schemas["create_thought"]["required"] == ["film_id", "start_seconds", "content"]
    assert schemas["create_fleeting_trace"]["required"] == [
        "film_id",
        "start_seconds",
        "content",
    ]
    assert schemas["create_reply"]["required"] == ["annotation_id", "content"]
    assert schemas["update_xiaxia_progress"]["required"] == ["film_id", "last_timestamp_seconds"]


def test_all_read_tools_call_existing_action_api_and_forward_bearer(mcp_server, monkeypatch):
    module, client, headers = mcp_server
    calls: list[dict[str, Any]] = []
    api_client_context = module.watching_app.test_client()

    class LocalApiClient:
        def __enter__(self):
            self.client = api_client_context.__enter__()
            return self

        def __exit__(self, *args):
            return api_client_context.__exit__(*args)

        def request(self, method, path, *, params=None, json=None, headers=None):
            calls.append({"method": method, "path": path, "headers": headers})
            response = self.client.open(
                path,
                method=method,
                query_string=params,
                json=json,
                headers=headers,
            )
            return type("APIResponse", (), {"json": lambda _self: response.get_json()})()

    monkeypatch.setattr(module.httpx, "Client", lambda *args, **kwargs: LocalApiClient())
    reads = [
        ("list_videos", {}, "/api/watch/videos", None),
        ("get_video", {"film_id": "missing-film-id"}, "/api/watch/videos/missing-film-id", "film_not_found"),
        ("get_watch_state", {}, "/api/watch/state", None),
        (
            "get_current_context",
            {"film_id": "missing-film-id"},
            "/api/watch/videos/missing-film-id/context",
            "film_not_found",
        ),
        (
            "get_transcript",
            {"film_id": "missing-film-id"},
            "/api/watch/videos/missing-film-id/transcript",
            "film_not_found",
        ),
        (
            "list_annotations",
            {"film_id": "missing-film-id"},
            "/api/watch/videos/missing-film-id/annotations",
            "film_not_found",
        ),
        (
            "list_thoughts",
            {"film_id": "missing-film-id"},
            "/api/watch/videos/missing-film-id/thoughts",
            "film_not_found",
        ),
        (
            "list_fleeting_traces",
            {"film_id": "missing-film-id"},
            "/api/watch/videos/missing-film-id/fleeting-traces",
            "film_not_found",
        ),
    ]
    for request_id, (name, arguments, path, error_code) in enumerate(reads, start=3):
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers=headers,
        )
        assert response.status_code == 200
        result = _message(response)["result"]
        assert result["isError"] is not True
        payload = json.loads(result["content"][0]["text"])
        if error_code:
            assert payload["error"]["code"] == error_code
        else:
            assert "error" not in payload
        assert calls[-1] == {
            "method": "GET",
            "path": path,
            "headers": {"Authorization": "Bearer local-test-token"},
        }
    assert len(calls) == len(reads)


def test_write_tool_boundaries_use_existing_not_found_validation(mcp_server, monkeypatch):
    module, client, headers = mcp_server
    api_client_context = module.watching_app.test_client()

    class LocalApiClient:
        def __enter__(self):
            self.client = api_client_context.__enter__()
            return self

        def __exit__(self, *args):
            return api_client_context.__exit__(*args)

        def request(self, method, path, *, params=None, json=None, headers=None):
            response = self.client.open(
                path,
                method=method,
                query_string=params,
                json=json,
                headers=headers,
            )
            return type("APIResponse", (), {"json": lambda _self: response.get_json()})()

    monkeypatch.setattr(module.httpx, "Client", lambda *args, **kwargs: LocalApiClient())
    writes = [
        (
            "create_thought",
            {"film_id": "missing-film-id", "start_seconds": 1, "content": "local validation boundary"},
            "film_not_found",
        ),
        (
            "create_fleeting_trace",
            {"film_id": "missing-film-id", "start_seconds": 1, "content": "local trace boundary"},
            "film_not_found",
        ),
        (
            "create_reply",
            {"annotation_id": "missing-annotation-id", "content": "local reply boundary"},
            "annotation_not_found",
        ),
        (
            "update_xiaxia_progress",
            {"film_id": "missing-film-id", "last_timestamp_seconds": 1},
            "film_not_found",
        ),
    ]
    for request_id, (name, arguments, error_code) in enumerate(writes, start=20):
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers=headers,
        )
        assert response.status_code == 200
        result = _message(response)["result"]
        assert result["isError"] is not True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"]["code"] == error_code
    assert module.watching_app.test_client().get("/api/watch/videos", headers={"Authorization": "Bearer local-test-token"}).get_json() == {
        "films": [],
        "count": 0,
    }
    assert module.watching_app.test_client().get("/health").get_json() == {
        "status": "ok",
        "service": "xiaxia-watch-house",
    }
