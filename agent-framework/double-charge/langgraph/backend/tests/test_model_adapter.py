import pytest
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure import model_client


@pytest.mark.parametrize("temperature", [None, 0.25])
def test_configured_temperature_is_forwarded_only_when_present(monkeypatch, temperature):
    captured = {}

    class Chat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(model_client, "AzureChatOpenAI", Chat)
    monkeypatch.setattr(model_client, "get_bearer_token_provider", lambda *_: object())
    model_client.FoundryComplaintModel(
        Settings(
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_deployment="model",
            model_temperature=temperature,
        ),
        credential=object(),
        http_client=object(),
        http_async_client=object(),
    )
    if temperature is None:
        assert "temperature" not in captured
    else:
        assert captured["temperature"] == temperature
    assert "azure_ad_async_token_provider" in captured
    assert "azure_ad_token_provider" not in captured


@pytest.mark.parametrize(
    "content",
    [
        {"reasoning": "SECRET"},
        [{"type": "reasoning", "text": "SECRET"}],
        [{"type": "text", "text": {"SECRET": "SECRET"}}],
        "   ",
    ],
)
def test_model_boundary_does_not_stringify_private_or_missing_content(content):
    with pytest.raises(ValueError):
        model_client._text(content)
