from pathlib import Path
import json
import subprocess

import yaml
from sqlalchemy import inspect


ROOT = Path(__file__).resolve().parents[1]


def test_fresh_schema_metadata_and_postgres_script(app):
    expected = {
        "films", "subtitle_cues", "user_progress", "xiaxia_viewing_state",
        "user_annotations", "xiaxia_thoughts", "xiaxia_replies", "watch_state",
    }
    assert set(inspect(app.extensions["db_engine"]).get_table_names()) == expected
    sql = (ROOT / "schema.sql").read_text(encoding="utf-8").lower()
    for table in expected:
        assert f"create table {table}" in sql
    assert "on delete cascade" in sql
    assert "create or replace function set_updated_at" in sql
    assert sql.index("create table films") < sql.index("create table subtitle_cues")
    assert "storage is intentionally not required" in sql


def _action_routes_from_flask(app):
    result = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/watch"):
            continue
        path = rule.rule.replace("<film_id>", "{film_id}").replace("<annotation_id>", "{annotation_id}")
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            result.add((path, method.lower()))
    return result


def _action_routes_from_openapi(spec):
    verbs = {"get", "post", "put", "patch", "delete"}
    return {(path, method) for path, item in spec["paths"].items() for method in item if method in verbs}


def test_openapi_matches_action_routes(app):
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert _action_routes_from_openapi(spec) == _action_routes_from_flask(app)
    assert spec["servers"] == [{"url": "https://YOUR-RENDER-SERVICE.onrender.com"}]
    assert "/login" not in spec["paths"]
    assert not any("delete" in item for item in spec["paths"].values())


def test_operation_ids_unique_and_descriptions_short():
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    operations = []
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operations.append(operation)
                assert len(operation.get("description", "")) < 300
                for parameter in operation.get("parameters", []):
                    if parameter["in"] == "path":
                        assert "$ref" not in parameter
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids))


def test_every_openapi_object_declares_properties():
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))

    def walk(node, path="root"):
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "object" or (isinstance(node_type, list) and "object" in node_type):
                assert "properties" in node, f"Object without properties at {path}"
            assert "oneOf" not in node and "anyOf" not in node and "discriminator" not in node
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(spec)


def test_frontend_polling_and_progress_throttling_contract():
    js = (ROOT / "xiaxia_watch_house/static/watch.js").read_text(encoding="utf-8")
    assert "setInterval(() => pollTimeline(false), 12000)" in js
    assert "now - lastSavedAt < 12000" in js
    assert "pagehide" in js and "beforeunload" in js and "seeked" in js and "pause" in js
    assert "window.location.reload" not in js
    assert "textarea.value = ''" in js
    assert "rendered.has(id)" in js


def test_reply_and_annotation_have_distinct_frontend_dedupe_keys():
    helper = ROOT / "xiaxia_watch_house/static/timeline_key.js"
    script = f"""
const entryKey = require({json.dumps(str(helper))});
const annotation = entryKey({{content_type:'user_annotation', annotation_id:'parent-1'}});
const reply = entryKey({{content_type:'xiaxia_reply', annotation_id:'parent-1', reply_id:'reply-1'}});
const thought = entryKey({{content_type:'xiaxia_thought', thought_id:'thought-1'}});
process.stdout.write(JSON.stringify({{annotation, reply, thought}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    keys = json.loads(result.stdout)
    assert keys == {
        "annotation": "annotation:parent-1",
        "reply": "reply:reply-1",
        "thought": "thought:thought-1",
    }
    assert len(set(keys.values())) == 3

    watch_js = (ROOT / "xiaxia_watch_house/static/watch.js").read_text(encoding="utf-8")
    assert "window.XiaxiaTimelineEntryKey(entry)" in watch_js
    assert "👤', label: '我的痕迹" in watch_js
    assert "💭', label: 'Xiaxia Thought" in watch_js
    assert "💬', label: 'Xiaxia 回复" in watch_js
    assert "timeline.appendChild(card)" in watch_js


def test_v11_cinema_presentation_is_incremental_and_mobile_first():
    library = (ROOT / "xiaxia_watch_house/templates/watch_library.html").read_text(encoding="utf-8")
    detail = (ROOT / "xiaxia_watch_house/templates/watch_detail.html").read_text(encoding="utf-8")
    css = (ROOT / "xiaxia_watch_house/static/style.css").read_text(encoding="utf-8")
    for heading in ["Xiaxia Cinema", "正在观看", "想看的影片", "已经看完"]:
        assert heading in library
    for label in ["影片信息", "来源", "字幕", "总时长", "我的进度", "Xiaxia 进度"]:
        assert label in detail
    assert "@media (max-width: 560px)" in css
    assert ".information-grid { grid-template-columns: repeat(2" in css


def test_private_library_and_watch_pages_render(web_client, csrf, make_film):
    film = make_film("Want To Watch")
    watching = make_film("Watching Now", duration_seconds=100)
    completed = make_film("Finished Film", duration_seconds=100)
    web_client.put(
        f"/api/web/films/{watching['film_id']}/progress",
        json={"current_seconds": 35, "duration_seconds": 100, "playback_state": "paused"},
        headers={"X-CSRF-Token": csrf},
    )
    web_client.put(
        f"/api/web/films/{completed['film_id']}/progress",
        json={"current_seconds": 100, "duration_seconds": 100, "playback_state": "ended"},
        headers={"X-CSRF-Token": csrf},
    )
    library = web_client.get("/watch")
    detail = web_client.get(f"/watch/{film['film_id']}")
    library_html = library.get_data(as_text=True)
    assert library.status_code == 200 and "Xiaxia Cinema" in library_html
    assert "正在观看" in library_html and "想看的影片" in library_html and "已经看完" in library_html
    html = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "local-video-file" in html and "annotation-form" in html and "subtitle-form" in html


def test_no_server_secrets_are_shipped_to_frontend():
    files = list((ROOT / "xiaxia_watch_house/templates").glob("*.html"))
    files += list((ROOT / "xiaxia_watch_house/static").glob("*.js"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for secret_name in ["ACTION_BEARER_TOKEN", "DATABASE_URL", "WEB_PASSWORD_HASH", "SESSION_SECRET", "test-action-token"]:
        assert secret_name not in combined


def test_render_and_dependency_files_use_required_versions():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "psycopg[binary,pool]==3.2.10" in requirements
    assert "3.2.9" not in requirements
    render = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    assert render["services"][0]["healthCheckPath"] == "/health"
