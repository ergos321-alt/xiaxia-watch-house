from __future__ import annotations

import io

import pytest
from werkzeug.security import generate_password_hash

from xiaxia_watch_house import create_app


@pytest.fixture()
def app(tmp_path):
    database = tmp_path / "watch-house.sqlite3"
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite+pysqlite:///{database}",
            "WEB_PASSWORD_HASH": generate_password_hash("private-password"),
            "ACTION_BEARER_TOKEN": "test-action-token",
            "SESSION_COOKIE_SECURE": False,
        }
    )
    yield application
    application.extensions["db_engine"].dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def web_client(client):
    response = client.post("/login", data={"password": "private-password"})
    assert response.status_code == 302
    return client


@pytest.fixture()
def csrf(web_client):
    with web_client.session_transaction() as sess:
        return sess["csrf_token"]


@pytest.fixture()
def action_headers():
    return {"Authorization": "Bearer test-action-token"}


@pytest.fixture()
def make_film(web_client, csrf):
    def factory(title="Test Film", source_type="local", source_url=None, duration_seconds=600):
        response = web_client.post(
            "/api/web/films",
            json={
                "title": title,
                "source_type": source_type,
                "source_url": source_url,
                "duration_seconds": duration_seconds,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()["film"]

    return factory


@pytest.fixture()
def upload_srt(web_client, csrf):
    def upload(film_id, content, filename="movie.srt", language="zh-CN"):
        return web_client.post(
            f"/api/web/films/{film_id}/subtitles",
            data={
                "subtitle": (io.BytesIO(content.encode("utf-8")), filename),
                "language": language,
            },
            headers={"X-CSRF-Token": csrf},
            content_type="multipart/form-data",
        )

    return upload


@pytest.fixture()
def sample_srt():
    return """1
00:00:00,000 --> 00:00:04,000
Opening line

2
00:00:08,000 --> 00:00:12,000
Second line

3
00:00:18,000 --> 00:00:22,000
At twenty seconds

4
00:00:28,000 --> 00:00:32,000
Future line
"""
