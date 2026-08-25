from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_schema():
    return yaml.safe_load(
        (PROJECT_ROOT / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )


def walk(value):
    yield value

    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def test_openapi_schema_is_valid_yaml_with_unique_operation_ids():
    schema = load_schema()

    assert schema["openapi"] == "3.1.0"

    operation_ids = []

    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
            }:
                operation_ids.append(operation["operationId"])

    assert len(operation_ids) == len(set(operation_ids))
    assert "createHandCommand" in operation_ids
    assert "getHandCommandStatus" in operation_ids
    assert "createEyeScreenRequest" in operation_ids
    assert "getEyeScreenRequest" in operation_ids
    assert "execute_anything" not in str(schema)
    assert "run_tasker_command" not in str(schema)


def test_tasker_only_claim_and_result_routes_are_not_exposed_to_gpt():
    schema = load_schema()

    assert "/hand/commands/next" not in schema["paths"]
    assert "/hand/commands/{command_id}/result" not in schema["paths"]
    assert "/eye/device/requests/next" not in schema["paths"]
    assert not any(
        path.startswith("/eye/device/")
        for path in schema["paths"]
    )


def test_custom_gpt_schema_uses_conservative_types_and_object_bodies():
    schema = load_schema()

    for item in walk(schema):
        if isinstance(item, dict) and "type" in item:
            # A schema may legitimately define a property literally named
            # "type". The compatibility regression here targets OpenAPI's
            # type keyword being encoded as a JSON/YAML array.
            assert not isinstance(item["type"], list)

        if isinstance(item, dict) and "enum" in item:
            enum = item["enum"]

            if "on" in enum or "off" in enum:
                assert all(isinstance(value, str) for value in enum)

    schemas = schema["components"]["schemas"]

    assert schemas["HandCommandRequest"]["type"] == "object"
    assert schemas["EyeScreenRequest"]["type"] == "object"

    for path, method in (
        ("/hand/commands", "post"),
        ("/eye/requests", "post"),
    ):
        body = schema["paths"][path][method]["requestBody"]
        body_schema = body["content"]["application/json"]["schema"]
        component_name = body_schema["$ref"].rsplit("/", 1)[-1]
        assert schemas[component_name]["type"] == "object"

    assert "oneOf" not in str(schema)
    assert "discriminator" not in str(schema)
    assert "variables" not in schema["servers"][0]


def test_openapi_declares_knock_and_only_gpt_visible_eye_operations():
    schema = load_schema()
    schemas = schema["components"]["schemas"]

    hand_request = schemas["HandCommandRequest"]
    actions = hand_request["properties"]["action"]["enum"]
    patterns = (
        hand_request["properties"]["parameters"]
        ["properties"]["pattern"]["enum"]
    )

    assert "knock" in actions
    assert patterns == ["xiaxia"]
    assert set(path for path in schema["paths"] if path.startswith("/eye")) == {
        "/eye/requests",
        "/eye/requests/{request_id}",
    }


def test_migration_has_required_fields_states_and_indexes():
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "20260824_001_create_hand_commands.sql"
    ).read_text(encoding="utf-8")

    for field in (
        "id UUID PRIMARY KEY",
        "action TEXT",
        "parameters JSONB",
        "status TEXT",
        "created_at TIMESTAMPTZ",
        "delivered_at TIMESTAMPTZ",
        "executed_at TIMESTAMPTZ",
        "result JSONB",
        "error TEXT",
    ):
        assert field in migration

    for status in (
        "pending",
        "delivered",
        "executed",
        "failed",
        "expired",
    ):
        assert f"'{status}'" in migration

    assert "idx_hand_commands_pending" in migration


def test_v11_migration_upgrades_hand_check_and_adds_eye_without_rebuild():
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "20260825_002_add_knock_and_eye.sql"
    ).read_text(encoding="utf-8")

    assert "DROP CONSTRAINT IF EXISTS hand_commands_action_check" in migration
    assert "ADD CONSTRAINT hand_commands_action_check" in migration
    assert "'knock'" in migration
    assert "CREATE TABLE IF NOT EXISTS eye_requests" in migration
    assert "frame_count BETWEEN 1 AND 3" in migration
    assert "visual_facts JSONB" in migration

    for status in (
        "pending",
        "capturing",
        "uploaded",
        "analyzing",
        "completed",
        "failed",
        "expired",
    ):
        assert f"'{status}'" in migration

    for index in (
        "idx_eye_requests_pending",
        "idx_eye_requests_status_updated",
        "idx_eye_requests_result_expiry",
    ):
        assert index in migration

    assert "DROP TABLE" not in migration.upper()
    assert "DELETE FROM hand_commands" not in migration
