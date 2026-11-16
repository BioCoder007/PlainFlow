import pytest

from cve_engine.llm import LLMError, parse_json_object


def test_parses_plain_json_object():
    assert parse_json_object('{"steps": {"s1": "A"}}') == {"steps": {"s1": "A"}}


def test_parses_object_inside_code_fence():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"a": '])
def test_non_object_reply_raises(text):
    with pytest.raises(LLMError):
        parse_json_object(text)


# -- provider choice ------------------------------------------------------------
import json

import httpx

from cve_engine.llm import (
    PROVIDERS, AnthropicClient, GeminiClient, OpenAICompatibleClient, make_client,
)


def chat_client(handler, **kwargs):
    kwargs.setdefault("base_url", "https://api.example.com/v1")
    kwargs.setdefault("model", "m-1")
    kwargs.setdefault("api_key", "sk-test")
    return OpenAICompatibleClient(transport=httpx.MockTransport(handler), **kwargs)


def reply(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def test_providers_offered():
    assert list(PROVIDERS) == ["anthropic", "openai", "gemini", "local", "other"]


def test_local_model_needs_an_address_but_no_key():
    local = make_client("local", "llama3", "", base_url="http://localhost:11434/v1")
    assert isinstance(local, OpenAICompatibleClient)
    assert local.base_url == "http://localhost:11434/v1"
    with pytest.raises(LLMError) as exc:
        make_client("local", "llama3", "", None)
    assert str(exc.value) == "Enter the endpoint address."


def test_local_models_get_a_longer_timeout_than_hosted_ones():
    local = make_client("local", "llama3", "", base_url="http://localhost:11434/v1")
    hosted = make_client("openai", "gpt-x", "k")
    assert local.timeout > hosted.timeout


def test_chat_client_sends_model_messages_and_bearer_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return reply('{"steps": {"s1": "A"}}')

    assert chat_client(handler).complete_json("SYS", "USER") == {"steps": {"s1": "A"}}
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "m-1"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


def test_chat_client_tolerates_trailing_slash_and_omits_auth_without_a_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return reply("{}")

    chat_client(handler, base_url="http://localhost:11434/v1/", api_key="").complete_json("s", "u")
    assert seen == {"url": "http://localhost:11434/v1/chat/completions", "auth": None}


@pytest.mark.parametrize("status,message", [
    (401, "The API key was rejected by the provider."),
    (403, "The API key was rejected by the provider."),
    (400, "The provider rejected the request (400). Most often the API key is invalid "
          "(Google Gemini answers 400 for a bad key) or the model name is wrong. "
          "Check both, and that the key has no spaces."),
    (404, "The provider did not recognise the model or the endpoint address."),
    (429, "The provider is rate-limiting this key or it is out of credit. Try again later."),
    (500, "The provider returned an error (status 500)."),
])
def test_chat_client_error_messages(status, message):
    with pytest.raises(LLMError) as exc:
        chat_client(lambda request: httpx.Response(status, text="secret detail")).complete_json("s", "u")
    assert str(exc.value) == message


def test_chat_client_network_failure_message():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError) as exc:
        chat_client(handler, base_url="http://localhost:11434/v1").complete_json("s", "u")
    assert str(exc.value) == "The provider could not be reached at localhost:11434."


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {}}]}, "text"])
def test_chat_client_unexpected_reply_shape(body):
    with pytest.raises(LLMError):
        chat_client(lambda request: httpx.Response(200, json=body)).complete_json("s", "u")


def test_make_client_maps_openai_and_gemini_to_their_endpoints():
    openai = make_client("openai", "gpt-x", "k")
    gemini = make_client("gemini", "gemini-x", "k")
    assert isinstance(openai, OpenAICompatibleClient) and openai.base_url == "https://api.openai.com/v1"
    assert isinstance(gemini, GeminiClient)


def test_make_client_other_uses_the_given_address():
    other = make_client("other", "llama", "", base_url="http://localhost:11434/v1")
    assert other.base_url == "http://localhost:11434/v1"


def test_make_client_anthropic():
    assert isinstance(make_client("anthropic", "claude-x", "k"), AnthropicClient)


@pytest.mark.parametrize("args,message", [
    (("nope", "m", "k", None), "Unknown provider."),
    (("openai", "  ", "k", None), "Enter a model name."),
    (("openai", "m", "", None), "Enter an API key."),
    (("anthropic", "m", " ", None), "Enter an API key."),
    (("other", "m", "", None), "Enter the endpoint address."),
    (("other", "m", "", "ftp://x"), "The endpoint address must start with http:// or https://."),
])
def test_make_client_rejects_incomplete_settings(args, message):
    with pytest.raises(LLMError) as exc:
        make_client(*args)
    assert str(exc.value) == message


def test_list_models_anthropic_and_gemini_and_local():
    from cve_engine.llm import list_models

    def handler(request):
        if "anthropic.com" in str(request.url):
            assert request.headers["x-api-key"] == "k"
            return httpx.Response(200, json={"data": [{"id": "claude-b"}, {"id": "claude-a"}]})
        if "generativelanguage" in str(request.url):
            assert request.headers["x-goog-api-key"] == "AQ.Abc"
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["createInteraction"]},
                {"name": "models/gemini-3.8-flash-tts", "supportedGenerationMethods": ["createInteraction"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
        return httpx.Response(200, json={"data": [{"id": "llama3:8b"}, {"id": "nomic-embed-text"}]})

    t = httpx.MockTransport(handler)
    assert list_models("anthropic", "k", transport=t) == ["claude-a", "claude-b"]
    assert list_models("gemini", "AQ.Abc", transport=t) == ["gemini-2.5-flash", "gemini-3.8-flash"]
    assert list_models("local", "", "http://localhost:11434/v1", transport=t) == ["llama3:8b", "nomic-embed-text"]


def test_list_models_errors():
    from cve_engine.llm import list_models
    t = httpx.MockTransport(lambda r: httpx.Response(401, text="no"))
    with pytest.raises(LLMError, match="rejected"):
        list_models("openai", "sk-x", transport=t)
    with pytest.raises(LLMError, match="API key"):
        list_models("gemini", "")
    with pytest.raises(LLMError, match="endpoint address"):
        list_models("local", "")


def test_gemini_client_uses_native_endpoint_and_header():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})

    client = GeminiClient("models/gemini-2.5-flash", "AQ.Abc", transport=httpx.MockTransport(handler))
    assert client.complete_json("sys", "user") == {"ok": True}
    assert seen == {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "key": "AQ.Abc", "auth": None}


def test_gemini_client_bad_reply_and_errors():
    bad = GeminiClient("m", "k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})))
    with pytest.raises(LLMError, match="expected format"):
        bad.complete_json("s", "u")
    err = GeminiClient("m", "k", transport=httpx.MockTransport(lambda r: httpx.Response(400, text="secret")))
    with pytest.raises(LLMError, match="400"):
        err.complete_json("s", "u")


def test_400_and_404_show_the_providers_sentence_without_the_key():
    body = {"error": {"message": "models/zzz is not found for API version v1beta. Key AQ.Abc was bad"}}
    client = GeminiClient("zzz", "AQ.Abc", transport=httpx.MockTransport(lambda r: httpx.Response(404, json=body)))
    with pytest.raises(LLMError) as exc:
        client.complete_json("s", "u")
    assert "models/zzz is not found for API version v1beta" in str(exc.value)
    assert "AQ.Abc" not in str(exc.value)
    # a 401 never carries provider text
    client = GeminiClient("zzz", "k", transport=httpx.MockTransport(lambda r: httpx.Response(401, json=body)))
    with pytest.raises(LLMError) as exc:
        client.complete_json("s", "u")
    assert str(exc.value) == "The API key was rejected by the provider."


def test_413_explains_the_request_was_too_large():
    with pytest.raises(LLMError, match="too large for the model"):
        chat_client(lambda r: httpx.Response(413, json={"error": {"message": "Request too large"}})).complete_json("s", "u")


# -- finding the provider from a key -------------------------------------------
from cve_engine.llm import detect_local, detect_provider


def _services(accepting_host, seen):
    def handler(request):
        seen.append(request.url.host)
        if request.url.host == accepting_host:
            return httpx.Response(200, json={"data": [{"id": "m-1"}]})
        return httpx.Response(401, text="no")
    return httpx.MockTransport(handler)


def test_known_prefix_sends_the_key_to_one_service_only():
    seen = []
    found = detect_provider("gsk_abc", transport=_services("api.groq.com", seen))
    assert found == {"name": "Groq", "provider": "other",
                     "base_url": "https://api.groq.com/openai/v1", "models": ["m-1"]}
    assert seen == ["api.groq.com"]


def test_known_prefix_rejected_names_the_service():
    with pytest.raises(LLMError, match="looks like a Groq key"):
        detect_provider("gsk_abc", transport=_services("nowhere", []))


def test_unknown_key_is_tried_against_every_service():
    seen = []
    found = detect_provider("zz-unknown", transport=_services("api.mistral.ai", seen))
    assert found["name"] == "Mistral" and found["base_url"] == "https://api.mistral.ai/v1"
    assert "openrouter.ai" not in seen and len(set(seen)) == 10
    with pytest.raises(LLMError, match="No known provider"):
        detect_provider("zz-unknown", transport=_services("nowhere", []))
    with pytest.raises(LLMError, match="Enter an API key"):
        detect_provider("  ")


def test_detect_local_finds_lm_studio_when_ollama_is_off():
    def handler(request):
        if request.url.port == 1234:
            return httpx.Response(200, json={"data": [{"id": "qwen"}]})
        raise httpx.ConnectError("refused")
    assert detect_local(transport=httpx.MockTransport(handler)) == {
        "name": "LM Studio", "provider": "local", "base_url": "http://localhost:1234/v1", "models": ["qwen"]}

    def dead(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(LLMError, match="No local model server"):
        detect_local(transport=httpx.MockTransport(dead))


def test_bare_list_model_reply_is_accepted():
    from cve_engine.llm import list_models
    t = httpx.MockTransport(lambda r: httpx.Response(200, json=[{"id": "a"}]))
    assert list_models("other", "k", "https://api.together.xyz/v1", transport=t) == ["a"]


def test_gemini_asks_for_little_thinking_and_falls_back_when_refused():
    GeminiClient._no_thinking_option = False
    bodies = []

    def handler(request):
        import json as _json
        body = _json.loads(request.content)
        bodies.append(body["generationConfig"])
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": "Unknown field thinkingConfig"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]})

    client = GeminiClient("gemini-3.8-flash", "k", transport=httpx.MockTransport(handler))
    assert client.complete_json("s", "u") == {"ok": 1}
    assert bodies[0]["thinkingConfig"] == {"thinkingLevel": "low"} and "thinkingConfig" not in bodies[1]
    assert client.complete_json("s", "u") == {"ok": 1}
    assert len(bodies) == 3  # the refused option is not sent again
    GeminiClient._no_thinking_option = False


def test_gemini_25_flash_turns_thinking_off():
    GeminiClient._no_thinking_option = False
    seen = {}

    def handler(request):
        import json as _json
        seen.update(_json.loads(request.content)["generationConfig"])
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]})

    GeminiClient("gemini-2.5-flash", "k", transport=httpx.MockTransport(handler)).complete_json("s", "u")
    assert seen["thinkingConfig"] == {"thinkingBudget": 0}
