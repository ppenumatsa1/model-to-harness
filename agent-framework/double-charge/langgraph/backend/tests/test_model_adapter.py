from model_to_harness_langgraph import model_adapter
from model_to_harness_langgraph.config import Settings


def test_default_model_configuration_omits_temperature(monkeypatch):
    captured: dict[str, object] = {}

    class FakeAzureChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(model_adapter, "AzureChatOpenAI", FakeAzureChatOpenAI)
    monkeypatch.setattr(model_adapter, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(model_adapter, "get_bearer_token_provider", lambda *_: object())

    model_adapter.FoundryComplaintModel(
        Settings(
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_deployment="model",
        )
    )

    assert "temperature" not in captured


def test_explicit_model_temperature_is_forwarded(monkeypatch):
    captured: dict[str, object] = {}

    class FakeAzureChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(model_adapter, "AzureChatOpenAI", FakeAzureChatOpenAI)
    monkeypatch.setattr(model_adapter, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(model_adapter, "get_bearer_token_provider", lambda *_: object())

    model_adapter.FoundryComplaintModel(
        Settings(
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_deployment="model",
            model_temperature=0.25,
        )
    )

    assert captured["temperature"] == 0.25
