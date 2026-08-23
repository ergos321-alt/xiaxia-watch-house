from xiaxia_watch_house.services import parse_subtitles, stable_cue_id


def test_srt_and_vtt_parsing_use_seconds():
    srt = "1\n00:01:02,500 --> 00:01:04,250\nHello\n"
    vtt = "WEBVTT\n\n00:01:02.500 --> 00:01:04.250\nHello\n"
    assert parse_subtitles(srt, "a.srt") == [(62.5, 64.25, "Hello")]
    assert parse_subtitles(vtt, "a.vtt") == [(62.5, 64.25, "Hello")]


def test_stable_cue_anchor_survives_identical_reupload(web_client, make_film, upload_srt, sample_srt):
    film = make_film()
    assert upload_srt(film["film_id"], sample_srt).status_code == 200
    first = web_client.get(f"/api/web/films/{film['film_id']}/subtitles?around_seconds=9").get_json()["cues"]
    assert upload_srt(film["film_id"], sample_srt).status_code == 200
    second = web_client.get(f"/api/web/films/{film['film_id']}/subtitles?around_seconds=9").get_json()["cues"]
    assert [x["cue_id"] for x in first] == [x["cue_id"] for x in second]
    assert all(isinstance(x["start_seconds"], float) for x in second)


def test_cue_anchor_cannot_cross_films(client, action_headers, make_film, upload_srt, sample_srt):
    film_a = make_film("A")
    film_b = make_film("B")
    upload_srt(film_a["film_id"], sample_srt)
    cue = client.get(
        f"/api/watch/videos/{film_a['film_id']}/transcript?chunk_size_cues=1", headers=action_headers
    ).get_json()["cues"][0]
    response = client.post(
        f"/api/watch/videos/{film_b['film_id']}/thoughts",
        json={"start_seconds": 0, "cue_id": cue["cue_id"], "content": "wrong film"},
        headers=action_headers,
    )
    assert response.status_code == 400


def test_context_clamps_to_user_progress_and_prevents_spoilers(
    client, web_client, csrf, action_headers, make_film, upload_srt, sample_srt
):
    film = make_film(duration_seconds=100)
    upload_srt(film["film_id"], sample_srt)
    saved = web_client.put(
        f"/api/web/films/{film['film_id']}/progress",
        json={"current_seconds": 20, "duration_seconds": 100, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200
    response = client.get(
        f"/api/watch/videos/{film['film_id']}/context?timestamp_seconds=99&before_seconds=60",
        headers=action_headers,
    )
    data = response.get_json()
    assert data["spoiler_boundary_seconds"] == 20
    assert data["evidence_end_seconds"] == 20
    assert all(cue["start_seconds"] <= 20 for cue in data["subtitle_cues"])
    assert "Future line" not in {cue["text"] for cue in data["subtitle_cues"]}


def test_transcript_time_window_is_bounded(client, action_headers, make_film, upload_srt, sample_srt):
    film = make_film()
    upload_srt(film["film_id"], sample_srt)
    response = client.get(
        f"/api/watch/videos/{film['film_id']}/transcript?start_seconds=7&end_seconds=23",
        headers=action_headers,
    )
    data = response.get_json()
    assert [cue["sequence_number"] for cue in data["cues"]] == [2, 3]
    assert data["range_start_seconds"] == 7
    assert data["range_end_seconds"] == 23


def test_long_transcript_requires_chunks_and_continuation(client, action_headers, make_film, upload_srt):
    film = make_film(duration_seconds=4000)
    blocks = []
    for i in range(1, 451):
        minute, sec = divmod(i * 5, 60)
        end_minute, end_sec = divmod(i * 5 + 2, 60)
        blocks.append(
            f"{i}\n00:{minute:02d}:{sec:02d},000 --> 00:{end_minute:02d}:{end_sec:02d},000\nLine {i}\n"
        )
    assert upload_srt(film["film_id"], "\n".join(blocks)).status_code == 200
    first = client.get(
        f"/api/watch/videos/{film['film_id']}/transcript?chunk_size_cues=80", headers=action_headers
    ).get_json()
    assert first["cue_count"] == 80
    assert first["has_next"] is True
    assert first["continuation"]
    assert len(first["cues"]) <= 200
    second = client.get(
        f"/api/watch/videos/{film['film_id']}/transcript?continuation={first['continuation']}",
        headers=action_headers,
    ).get_json()
    assert second["chunk_index"] == 1
    assert second["cues"][0]["sequence_number"] == 81
    assert second["cues"][0]["cue_id"] != first["cues"][0]["cue_id"]
