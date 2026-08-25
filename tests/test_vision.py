import json

import pytest

import vision
from vision import (
    OpenAIResponsesVisionProvider,
    UnconfiguredVisionProvider,
    VisionProviderError,
    build_vision_provider,
    normalize_visual_facts,
)


FACTS = {
    "scene": "A game screen.",
    "visible_people": [],
    "actions": ["A character is running."],
    "objects": ["health bar"],
    "screen_text": ["PAUSE"],
    "uncertainties": ["The level number is too small to read."],
}


def test_normalize_visual_facts_preserves_observed_and_uncertain_fields():
    assert normalize_visual_facts(FACTS) == FACTS


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {**FACTS, "scene": ""},
        {**FACTS, "objects": "health bar"},
        {**FACTS, "screen_text": [42]},
    ],
)
def test_normalize_visual_facts_rejects_unstructured_provider_output(value):
    with pytest.raises(VisionProviderError) as error:
        normalize_visual_facts(value)

    assert error.value.code == "invalid_vision_response"


def test_build_provider_requires_explicit_provider_key_and_model():
    assert isinstance(build_vision_provider({}), UnconfiguredVisionProvider)
    assert isinstance(
        build_vision_provider({
            "VISION_PROVIDER": "openai",
            "OPENAI_API_KEY": "",
            "VISION_MODEL": "",
        }),
        UnconfiguredVisionProvider,
    )

    provider = build_vision_provider({
        "VISION_PROVIDER": "openai",
        "OPENAI_API_KEY": "test-key",
        "VISION_MODEL": "configured-vision-model",
    })

    assert isinstance(provider, OpenAIResponsesVisionProvider)
    assert provider.model == "configured-vision-model"


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps({
            "output_text": json.dumps(FACTS),
        }).encode("utf-8")


def test_openai_adapter_sends_image_and_strict_structured_schema(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(vision, "urlopen", fake_urlopen)

    provider = OpenAIResponsesVisionProvider(
        api_key="test-secret",
        model="configured-vision-model",
        timeout_seconds=37,
        image_detail="low",
    )
    facts = provider.analyze(
        b"\x89PNG\r\n\x1a\nimage",
        "image/png",
        focus="read the error",
    )

    assert facts == FACTS
    assert captured["timeout"] == 37
    assert captured["request"].full_url.endswith("/responses")

    payload = json.loads(captured["request"].data.decode("utf-8"))
    content = payload["input"][0]["content"]
    image = next(item for item in content if item["type"] == "input_image")

    assert payload["model"] == "configured-vision-model"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert image["detail"] == "low"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False


def test_unconfigured_provider_never_mocks_a_successful_analysis():
    provider = UnconfiguredVisionProvider()

    with pytest.raises(VisionProviderError) as error:
        provider.analyze(b"image", "image/png")

    assert error.value.code == "vision_provider_not_configured"

