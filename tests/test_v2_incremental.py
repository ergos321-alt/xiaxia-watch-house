from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from xiaxia_watch_house.models import FleetingTrace, XiaxiaThought
from xiaxia_watch_house.services import utcnow


ROOT = Path(__file__).resolve().parents[1]


def _annotation(web_client, csrf, film_id, start=10, content="我停在这里"):
    response = web_client.post(
        f"/api/web/films/{film_id}/annotations",
        json={"start_seconds": start, "content": content},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.get_json()["annotation"]


def test_v11_thought_rows_remain_permanent_without_model_rewrite(
    app, client, action_headers, make_film
):
    film = make_film("Old Thought")
    created = client.post(
        f"/api/watch/videos/{film['film_id']}/thoughts",
        json={"start_seconds": 8, "content": "V1.1 留下的想法"},
        headers=action_headers,
    ).get_json()["thought"]
    assert created["trace_type"] == "permanent"
    db = app.extensions["db_session_factory"]()
    try:
        row = db.scalar(select(XiaxiaThought).where(XiaxiaThought.thought_id == created["thought_id"]))
        assert row.content == "V1.1 留下的想法"
        assert not hasattr(row, "trace_type")
    finally:
        db.close()
    migration = (ROOT / "migrations/v1_1_to_v2.sql").read_text(encoding="utf-8").lower()
    assert "alter table xiaxia_thoughts" not in migration


def test_fleeting_and_permanent_content_are_separate_with_server_owned_identity(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film("Two Weights")
    thought_response = client.post(
        f"/api/watch/videos/{film['film_id']}/thoughts",
        json={"start_seconds": 10, "content": "永久想法"},
        headers=action_headers,
    )
    casual_response = client.post(
        f"/api/watch/videos/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 11, "content": "哈哈"},
        headers=action_headers,
    )
    user_response = web_client.post(
        f"/api/web/films/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 12, "content": "这里好漂亮"},
        headers={"X-CSRF-Token": csrf},
    )
    assert thought_response.get_json()["thought"]["trace_type"] == "permanent"
    assert casual_response.get_json()["fleeting_trace"]["actor"] == "xiaxia"
    assert user_response.get_json()["fleeting_trace"]["actor"] == "user"
    assert casual_response.get_json()["fleeting_trace"]["trace_type"] == "fleeting"
    assert client.post(
        f"/api/watch/videos/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 13, "content": "bad", "actor": "user"},
        headers=action_headers,
    ).status_code == 400
    assert web_client.post(
        f"/api/web/films/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 13, "content": "bad", "actor": "xiaxia"},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 400


def test_fleeting_trace_retention_and_multi_film_isolation(
    app, client, action_headers, make_film
):
    film_a = make_film("Trace A")
    film_b = make_film("Trace B")
    client.post(
        f"/api/watch/videos/{film_a['film_id']}/fleeting-traces",
        json={"start_seconds": 2, "content": "only A"},
        headers=action_headers,
    )
    db = app.extensions["db_session_factory"]()
    try:
        expired = FleetingTrace(
            film_id=film_a["film_id"], actor="user", content_type="fleeting_trace",
            start_seconds=3, content="expired", expires_at=utcnow() - timedelta(days=1),
        )
        db.add(expired)
        db.commit()
    finally:
        db.close()
    a = client.get(
        f"/api/watch/videos/{film_a['film_id']}/fleeting-traces", headers=action_headers
    ).get_json()["fleeting_traces"]
    b = client.get(
        f"/api/watch/videos/{film_b['film_id']}/fleeting-traces", headers=action_headers
    ).get_json()["fleeting_traces"]
    assert [entry["content"] for entry in a] == ["only A"]
    assert b == []


def test_shared_stop_is_dynamic_stable_and_keeps_source_references(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film("Shared Stop")
    annotation = _annotation(web_client, csrf, film["film_id"], start=40)
    reply = client.post(
        f"/api/watch/annotations/{annotation['annotation_id']}/reply",
        json={"content": "我也停在这里"}, headers=action_headers,
    ).get_json()["reply"]
    first = web_client.get(f"/api/web/films/{film['film_id']}/timeline").get_json()
    second = web_client.get(f"/api/web/films/{film['film_id']}/timeline").get_json()
    assert len(first["shared_stops"]) == 1
    stop = first["shared_stops"][0]
    assert stop["shared_stop_id"] == second["shared_stops"][0]["shared_stop_id"]
    assert stop["user_trace_ref"] == f"annotation:{annotation['annotation_id']}"
    assert stop["xiaxia_trace_ref"] == f"reply:{reply['reply_id']}"
    assert stop["anchor_seconds"] == 40


def test_copresence_uses_independent_progress_without_merging(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film("Together", duration_seconds=300)
    web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 100, "duration_seconds": 300, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    client.post(
        "/api/watch/xiaxia/progress",
        json={"film_id": film["film_id"], "last_timestamp_seconds": 90},
        headers=action_headers,
    )
    timeline = web_client.get(f"/api/web/films/{film['film_id']}/timeline").get_json()
    assert timeline["copresence"]["state"] == "together"
    assert timeline["copresence"]["difference_seconds"] == 10
    detail = client.get(f"/api/watch/videos/{film['film_id']}", headers=action_headers).get_json()["film"]
    assert detail["user_progress"]["current_seconds"] == 100
    assert detail["xiaxia_viewing_state"]["last_timestamp_seconds"] == 90


def test_fleeting_context_remains_spoiler_safe(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film("Safe Casual", duration_seconds=100)
    web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 20, "duration_seconds": 100, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    client.post(
        f"/api/watch/videos/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 10, "content": "safe"}, headers=action_headers,
    )
    web_client.post(
        f"/api/web/films/{film['film_id']}/fleeting-traces",
        json={"start_seconds": 30, "content": "future"},
        headers={"X-CSRF-Token": csrf},
    )
    context = client.get(
        f"/api/watch/videos/{film['film_id']}/context?timestamp_seconds=80",
        headers=action_headers,
    ).get_json()
    assert context["spoiler_boundary_seconds"] == 20
    assert [entry["content"] for entry in context["timeline_entries"]] == ["safe"]


def test_rewatch_intent_is_lightweight_and_clears_when_playing(
    web_client, csrf, make_film
):
    film = make_film("Again", duration_seconds=100)
    web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 100, "duration_seconds": 100, "playback_state": "ended"},
        headers={"X-CSRF-Token": csrf},
    )
    intent = web_client.put(
        f"/api/web/films/{film['film_id']}/watch-intent",
        json={"watch_intent": "rewatch"}, headers={"X-CSRF-Token": csrf},
    ).get_json()["user_progress"]
    assert intent["watch_intent"] == "rewatch" and intent["current_seconds"] == 0
    playing = web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 2, "duration_seconds": 100, "playback_state": "playing"},
        headers={"X-CSRF-Token": csrf},
    ).get_json()["user_progress"]
    assert playing["watch_intent"] is None


def test_additive_migration_shape_preserves_representative_v11_rows(tmp_path):
    database = sqlite3.connect(tmp_path / "migration.sqlite3")
    database.executescript(
        """
        create table films (film_id text primary key, title text not null);
        create table user_progress (film_id text primary key, current_seconds real not null);
        create table xiaxia_thoughts (thought_id text primary key, film_id text not null, content text not null);
        insert into films values ('film-1', 'History');
        insert into user_progress values ('film-1', 55);
        insert into xiaxia_thoughts values ('thought-1', 'film-1', 'kept');
        """
    )
    before = database.execute("select film_id, current_seconds from user_progress").fetchall()
    thought_before = database.execute("select thought_id, content from xiaxia_thoughts").fetchall()
    database.execute("alter table user_progress add column watch_intent text")
    database.execute(
        "create table fleeting_traces (trace_id text primary key, film_id text not null, content text not null)"
    )
    assert database.execute("select film_id, current_seconds from user_progress").fetchall() == before
    assert database.execute("select thought_id, content from xiaxia_thoughts").fetchall() == thought_before
    assert database.execute("select watch_intent from user_progress").fetchone() == (None,)
    database.close()


def test_polling_code_only_updates_timeline_state_not_player():
    js = (ROOT / "xiaxia_watch_house/static/watch.js").read_text(encoding="utf-8")
    polling = js[js.index("const pollTimeline"):js.index("setInterval(() => pollTimeline(false), 12000)")]
    assert "player.currentTime" not in polling
    assert "replaceChildren" not in polling
    assert "textarea.value" not in polling

