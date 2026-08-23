def test_web_and_action_auth_are_separate(client, action_headers):
    assert client.get("/watch").status_code == 302
    assert client.get("/api/watch/videos").status_code == 401
    assert client.get("/api/watch/videos", headers=action_headers).status_code == 200
    assert client.post("/login", data={"password": "wrong"}).status_code == 401
    assert client.post("/login", data={"password": "private-password"}).status_code == 302
    assert client.get("/api/watch/videos").status_code == 401


def test_web_mutations_require_csrf(web_client):
    response = web_client.post("/api/web/films", json={"title": "No", "source_type": "local"})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_web_annotation_actor_is_server_controlled(web_client, csrf, make_film):
    film = make_film()
    rejected = web_client.post(
        f"/api/web/films/{film['film_id']}/annotations",
        json={"actor": "xiaxia", "start_seconds": 1, "content": "attempt"},
        headers={"X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 400
    created = web_client.post(
        f"/api/web/films/{film['film_id']}/annotations",
        json={"start_seconds": 1, "content": "mine"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    body = created.get_json()["annotation"]
    assert body["actor"] == "user"
    assert body["content_type"] == "user_annotation"


def test_action_actor_is_server_controlled(client, action_headers, make_film):
    film = make_film()
    endpoint = f"/api/watch/videos/{film['film_id']}/thoughts"
    rejected = client.post(
        endpoint,
        json={"actor": "user", "start_seconds": 2, "content": "attempt"},
        headers=action_headers,
    )
    assert rejected.status_code == 400
    created = client.post(
        endpoint,
        json={"start_seconds": 2, "content": "Xiaxia thought"},
        headers=action_headers,
    )
    assert created.status_code == 201
    assert created.get_json()["thought"]["actor"] == "xiaxia"


def test_action_request_bodies_do_not_define_actor():
    import yaml

    spec = yaml.safe_load(open("openapi.yaml", encoding="utf-8"))
    for path, item in spec["paths"].items():
        for operation in item.values():
            if not isinstance(operation, dict) or "requestBody" not in operation:
                continue
            ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            schema = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
            assert "actor" not in schema["properties"]
            assert "author" not in schema["properties"]
