from sqlalchemy import func, select

from xiaxia_watch_house.models import (
    Film,
    SubtitleCue,
    UserAnnotation,
    UserProgress,
    WatchState,
    XiaxiaReply,
    XiaxiaThought,
    XiaxiaViewingState,
)


def create_annotation(web_client, csrf, film_id, content="note", start=10):
    response = web_client.post(
        f"/api/web/films/{film_id}/annotations",
        json={"start_seconds": start, "content": content},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.get_json()["annotation"]


def test_multi_film_isolation(client, web_client, csrf, action_headers, make_film):
    film_a = make_film("Film A")
    film_b = make_film("Film B")
    create_annotation(web_client, csrf, film_a["film_id"], "only A")
    a = client.get(f"/api/watch/videos/{film_a['film_id']}/annotations", headers=action_headers).get_json()
    b = client.get(f"/api/watch/videos/{film_b['film_id']}/annotations", headers=action_headers).get_json()
    assert [x["content"] for x in a["annotations"]] == ["only A"]
    assert b["annotations"] == []


def test_user_annotation_full_crud(web_client, csrf, make_film):
    film = make_film()
    item = create_annotation(web_client, csrf, film["film_id"])
    updated = web_client.put(
        f"/api/web/annotations/{item['annotation_id']}",
        json={"content": "edited", "start_seconds": 12.5},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.get_json()["annotation"]["content"] == "edited"
    listed = web_client.get(f"/api/web/films/{film['film_id']}/annotations").get_json()
    assert listed["annotations"][0]["start_seconds"] == 12.5
    deleted = web_client.delete(
        f"/api/web/annotations/{item['annotation_id']}", headers={"X-CSRF-Token": csrf}
    )
    assert deleted.status_code == 200
    assert web_client.get(f"/api/web/films/{film['film_id']}/annotations").get_json()["annotations"] == []


def test_xiaxia_thought_and_reply_have_distinct_models(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film()
    annotation = create_annotation(web_client, csrf, film["film_id"], "user trace", 25)
    thought = client.post(
        f"/api/watch/videos/{film['film_id']}/thoughts",
        json={"start_seconds": 20, "content": "independent thought"},
        headers=action_headers,
    ).get_json()["thought"]
    reply = client.post(
        f"/api/watch/annotations/{annotation['annotation_id']}/reply",
        json={"content": "reply to you"},
        headers=action_headers,
    ).get_json()["reply"]
    assert thought["content_type"] == "xiaxia_thought"
    assert "thought_id" in thought and "reply_id" not in thought
    assert reply["content_type"] == "xiaxia_reply"
    assert reply["annotation_id"] == annotation["annotation_id"]
    assert reply["start_seconds"] == annotation["start_seconds"]


def test_reply_delete_does_not_delete_annotation(client, web_client, csrf, action_headers, make_film):
    film = make_film()
    annotation = create_annotation(web_client, csrf, film["film_id"])
    reply = client.post(
        f"/api/watch/annotations/{annotation['annotation_id']}/reply",
        json={"content": "reply"}, headers=action_headers
    ).get_json()["reply"]
    deleted = web_client.delete(
        f"/api/web/replies/{reply['reply_id']}", headers={"X-CSRF-Token": csrf}
    )
    assert deleted.status_code == 200
    assert len(web_client.get(f"/api/web/films/{film['film_id']}/annotations").get_json()["annotations"]) == 1


def test_user_and_xiaxia_progress_are_independent(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film(duration_seconds=500)
    user = web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 240, "duration_seconds": 500, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    assert user.status_code == 200
    xiaxia = client.post(
        "/api/watch/xiaxia/progress",
        json={"film_id": film["film_id"], "last_timestamp_seconds": 90, "chunk_checkpoint": 2, "completed": False},
        headers=action_headers,
    )
    assert xiaxia.status_code == 200
    detail = client.get(f"/api/watch/videos/{film['film_id']}", headers=action_headers).get_json()["film"]
    assert detail["user_progress"]["current_seconds"] == 240
    assert detail["xiaxia_viewing_state"]["last_timestamp_seconds"] == 90
    assert detail["xiaxia_viewing_state"]["chunk_checkpoint"] == 2


def test_transcript_can_start_from_xiaxia_checkpoint(
    client, action_headers, make_film, upload_srt, sample_srt
):
    film = make_film(duration_seconds=500)
    upload_srt(film["film_id"], sample_srt)
    client.post(
        "/api/watch/xiaxia/progress",
        json={"film_id": film["film_id"], "last_timestamp_seconds": 17},
        headers=action_headers,
    )
    data = client.get(
        f"/api/watch/videos/{film['film_id']}/transcript?from_checkpoint=true",
        headers=action_headers,
    ).get_json()
    assert data["range_start_seconds"] == 17
    assert data["cues"][0]["sequence_number"] == 3


def test_polling_api_returns_new_xiaxia_entries_without_page_reload(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film()
    initial = web_client.get(f"/api/web/films/{film['film_id']}/timeline").get_json()
    assert initial["entries"] == []
    client.post(
        f"/api/watch/videos/{film['film_id']}/thoughts",
        json={"start_seconds": 3, "content": "appears by polling"},
        headers=action_headers,
    )
    polled = web_client.get(f"/api/web/films/{film['film_id']}/timeline?since={initial['cursor']}").get_json()
    assert [x["content"] for x in polled["entries"]] == ["appears by polling"]


def test_timeline_returns_user_annotation_and_its_xiaxia_reply(
    client, web_client, csrf, action_headers, make_film
):
    film = make_film("Reply Timeline")
    annotation = create_annotation(web_client, csrf, film["film_id"], "I noticed this", 14)
    reply_response = client.post(
        f"/api/watch/annotations/{annotation['annotation_id']}/reply",
        json={"content": "I noticed it too"},
        headers=action_headers,
    )
    assert reply_response.status_code == 201
    reply = reply_response.get_json()["reply"]

    entries = web_client.get(f"/api/web/films/{film['film_id']}/timeline").get_json()["entries"]
    assert [entry["content_type"] for entry in entries] == ["user_annotation", "xiaxia_reply"]
    assert entries[0]["annotation_id"] == annotation["annotation_id"]
    assert entries[1]["annotation_id"] == annotation["annotation_id"]
    assert entries[1]["reply_id"] == reply["reply_id"]


def test_film_deletion_cascades_all_owned_rows(
    app, client, web_client, csrf, action_headers, make_film, upload_srt, sample_srt
):
    film = make_film("Delete Me")
    upload_srt(film["film_id"], sample_srt)
    annotation = create_annotation(web_client, csrf, film["film_id"])
    client.post(
        f"/api/watch/videos/{film['film_id']}/thoughts",
        json={"start_seconds": 1, "content": "thought"}, headers=action_headers
    )
    client.post(
        f"/api/watch/annotations/{annotation['annotation_id']}/reply",
        json={"content": "reply"}, headers=action_headers
    )
    web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 5, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    client.post(
        "/api/watch/xiaxia/progress",
        json={"film_id": film["film_id"], "last_timestamp_seconds": 3}, headers=action_headers
    )
    response = web_client.delete(
        f"/api/web/films/{film['film_id']}",
        json={"confirm_title": "Delete Me"}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    db = app.extensions["db_session_factory"]()
    try:
        for model in [Film, SubtitleCue, UserAnnotation, XiaxiaThought, XiaxiaReply, UserProgress, XiaxiaViewingState]:
            assert db.scalar(select(func.count()).select_from(model)) == 0
        state = db.get(WatchState, 1)
        assert state is not None and state.current_film_id is None
    finally:
        db.close()
