import pytest
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure import model_client


async def test_production_model_constructs_without_api_key_or_network(monkeypatch):
    import socket

    for name in ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_AD_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def deny_network(*args, **kwargs):
        pytest.fail("Model construction must not request credentials or invoke the model")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    async with model_client.open_model(
        Settings(
            _env_file=None,
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_deployment="model",
        )
    ) as model:
        assert isinstance(model, model_client.FoundryComplaintModel)


async def test_real_model_inference_uses_async_credentials():
    import httpx
    from azure.core.credentials import AccessToken

    calls = []

    class AsyncCredential:
        async def get_token(self, *scopes, **kwargs):
            calls.append("async-token")
            assert scopes == ("https://cognitiveservices.azure.com/.default",)
            return AccessToken("offline-token", 2**31)

    class SyncCredential:
        def get_token(self, *scopes, **kwargs):
            pytest.fail("Async inference must not acquire tokens synchronously")

    async def respond(request):
        calls.append("async-inference")
        assert request.headers["authorization"] == "Bearer offline-token"
        return httpx.Response(
            200,
            json={
                "id": "offline-response",
                "model": "model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "safe summary"},
                    }
                ],
            },
        )

    with httpx.Client() as sync_client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            model = model_client.FoundryComplaintModel(
                Settings(
                    _env_file=None,
                    azure_openai_endpoint="https://example.openai.azure.com/",
                    azure_openai_deployment="model",
                ),
                credential=AsyncCredential(),
                sync_credential=SyncCredential(),
                http_client=sync_client,
                http_async_client=async_client,
            )
            assert await model.normalize("offline complaint") == "safe summary"
    assert calls == ["async-token", "async-inference"]


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
        sync_credential=object(),
        http_client=object(),
        http_async_client=object(),
    )
    if temperature is None:
        assert "temperature" not in captured
    else:
        assert captured["temperature"] == temperature
    assert "azure_ad_async_token_provider" in captured
    assert callable(captured["azure_ad_token_provider"])


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
