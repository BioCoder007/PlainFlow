"""The only place that talks to an LLM provider."""
from __future__ import annotations

import json
from typing import Protocol


class LLMError(Exception):
    """The provider failed or did not return a JSON object."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class NotJSON(LLMError):
    """The model answered, but not with a JSON object. `text` holds what it said."""

    def __init__(self, text: str) -> None:
        super().__init__("The model did not reply in the required format. Small models often "
                         "fail at this. Try again, or choose a larger model.")
        self.text = text


def parse_json_object(text: str) -> dict:
    """Parse a reply that should be one JSON object. Tolerates a code fence, text before or
    after the object, and raw line breaks inside strings."""
    text = (text or "").strip()
    decoder = json.JSONDecoder(strict=False)
    start = text.find("{")
    tries = 0
    while start != -1 and tries < 20:
        try:
            data, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
        start = text.find("{", start + 1)
        tries += 1
    raise NotJSON(text)


_KEY_REJECTED = "The API key was rejected by the provider."
_NOT_FOUND = "The provider did not recognise the model or the endpoint address."
_RATE_LIMITED = (
    "The provider is rate-limiting this key or it is out of credit. Try again later.")


_BAD_REQUEST = ("The provider rejected the request (400). Most often the API key is invalid "
                "(Google Gemini answers 400 for a bad key) or the model name is wrong. "
                "Check both, and that the key has no spaces.")


_TOO_BIG = ("This function is too large for the model's request limit (413). Free tiers, "
            "especially Groq's, allow only a few thousand tokens per request. Open a shorter function, "
            "or switch to a model with a larger limit, such as Gemini Flash.")


def _provider_detail(response, api_key: str = "") -> str:
    """The provider's own error sentence for a 400 or 404, so a wrong model name or address can be
    told apart from a wrong key. Shown only to the person running the app. Short, with the key removed."""
    try:
        body = response.json()
        err = body.get("error", body) if isinstance(body, dict) else {}
        text = err.get("message", "") if isinstance(err, dict) else ""
    except ValueError:
        text = ""
    text = " ".join(str(text).split())
    if api_key:
        text = text.replace(api_key, "***")
    return text[:300]


def _status_message(status: int, detail: str = "") -> str:
    """A short message per failure. Only a 400 or 404 may carry the provider's own sentence."""
    if status in (401, 403):
        return _KEY_REJECTED
    if status == 400:
        return _BAD_REQUEST + (f" Provider said: {detail}" if detail else "")
    if status == 404:
        return _NOT_FOUND + (f" Provider said: {detail}" if detail else "")
    if status == 413:
        return _TOO_BIG + (f" Provider said: {detail}" if detail else "")
    if status == 429:
        return _RATE_LIMITED
    return f"The provider returned an error (status {status})."


_shared_http = None


def _http(transport=None):
    """An HTTP client. Real requests share one client, so connections to a provider stay open
    between requests and each request skips the connection set-up."""
    import httpx

    global _shared_http
    if transport is not None:
        return httpx.Client(transport=transport)
    if _shared_http is None:
        _shared_http = httpx.Client(limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120))
    return _shared_http


class AnthropicClient:
    def __init__(self, model: str, api_key: str, max_tokens: int = 4096) -> None:
        import anthropic  # optional dependency: pip install cve-engine[llm]

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def complete_json(self, system: str, user: str) -> dict:
        try:
            reply = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIStatusError as e:
            raise LLMError(_status_message(e.status_code)) from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError("The provider could not be reached at api.anthropic.com.") from e
        except self._anthropic.AnthropicError as e:
            raise LLMError("The provider returned an error.") from e
        text = "".join(
            block.text for block in reply.content if getattr(block, "type", "") == "text")
        return parse_json_object(text)


class OpenAICompatibleClient:
    """Any endpoint that speaks the OpenAI chat-completions format:
    OpenAI, Google Gemini, OpenRouter, Ollama and others."""

    def __init__(self, base_url: str, model: str, api_key: str = "",
                 transport=None, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._transport = transport
        self.timeout = timeout

    def complete_json(self, system: str, user: str) -> dict:
        import httpx  # optional dependency: pip install cve-engine[llm]

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = _http(self._transport).post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as e:
            host = httpx.URL(self.base_url).netloc.decode()
            raise LLMError(f"The provider could not be reached at {host}.") from e
        if response.status_code != 200:
            raise LLMError(_status_message(
                response.status_code, _provider_detail(response, self._api_key)))
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError("The provider's reply was not in the expected format.") from e
        if not isinstance(content, str):
            raise LLMError("The provider's reply was not in the expected format.")
        return parse_json_object(content)


class GeminiClient:
    """Google's own Gemini endpoint. New "AQ." keys work here but are refused by the
    OpenAI-compatible endpoint, so Gemini does not go through that one."""

    BASE = "https://generativelanguage.googleapis.com/v1beta"
    _no_thinking_option = False  # set once a model refuses the thinking option

    def __init__(self, model: str, api_key: str, transport=None, timeout: float = 120.0) -> None:
        self._model = model.removeprefix("models/")
        self._api_key = api_key
        self._transport = transport
        self.timeout = timeout

    def complete_json(self, system: str, user: str) -> dict:
        import httpx

        config: dict = {"responseMimeType": "application/json"}
        # Explanations need no long reasoning: ask for the least thinking, which is much faster.
        if GeminiClient._no_thinking_option:
            pass
        elif self._model.startswith("gemini-2.5-flash"):
            config["thinkingConfig"] = {"thinkingBudget": 0}
        elif self._model.startswith("gemini-3"):
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        url = f"{self.BASE}/models/{self._model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        try:
            http = _http(self._transport)
            response = http.post(url, json=payload, headers=headers, timeout=self.timeout)
            if response.status_code == 400 and "thinkingConfig" in config and not GeminiClient._no_thinking_option:
                # This model does not take the thinking option: send the request without it, and remember.
                del config["thinkingConfig"]
                retry = http.post(url, json=payload, headers=headers, timeout=self.timeout)
                if retry.status_code == 200:
                    GeminiClient._no_thinking_option = True
                response = retry
        except httpx.HTTPError as e:
            raise LLMError("The provider could not be reached at generativelanguage.googleapis.com.") from e
        if response.status_code != 200:
            raise LLMError(_status_message(
                response.status_code, _provider_detail(response, self._api_key)))
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError("The provider's reply was not in the expected format.") from e
        return parse_json_object(text)


# provider id -> fixed endpoint (None: Anthropic uses its SDK; Local and Other take an address)
PROVIDERS: dict[str, str | None] = {
    "anthropic": None,
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "local": None,   # a model on the developer's own machine: Ollama, LM Studio, llama.cpp
    "other": None,   # any other OpenAI-compatible service
}
LOCAL_TIMEOUT_SECONDS = 600.0  # local models can be slow on a first, cold request


def make_client(provider: str, model: str, api_key: str = "",
                base_url: str | None = None) -> LLMClient:
    """Build the client for a developer's chosen provider and model.
    Raises LLMError with a message that can be shown to them."""
    model = (model or "").strip()
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip()
    if provider not in PROVIDERS:
        raise LLMError("Unknown provider.")
    if not model:
        raise LLMError("Enter a model name.")
    if provider in ("local", "other"):
        if not base_url:
            raise LLMError("Enter the endpoint address.")
        if not base_url.startswith(("http://", "https://")):
            raise LLMError("The endpoint address must start with http:// or https://.")
        if provider == "local":  # no key needed
            return OpenAICompatibleClient(base_url, model, api_key, timeout=LOCAL_TIMEOUT_SECONDS)
        return OpenAICompatibleClient(base_url, model, api_key)
    if not api_key:
        raise LLMError("Enter an API key.")
    if provider == "anthropic":
        return AnthropicClient(model=model, api_key=api_key)
    if provider == "gemini":
        return GeminiClient(model, api_key)
    return OpenAICompatibleClient(PROVIDERS[provider], model, api_key)


_NOT_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "imagen", "veo", "aqa",
             "image", "audio", "realtime", "transcribe", "babbage", "davinci")


def list_models(provider: str, api_key: str = "", base_url: str = "",
                transport=None, timeout: float = 20.0) -> list[str]:
    """The model ids this key or server offers, so a developer can pick one instead of typing it.
    Raises LLMError with a message that can be shown to them."""
    import httpx

    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip()
    if provider not in PROVIDERS:
        raise LLMError("Unknown provider.")
    if provider == "anthropic":
        if not api_key:
            raise LLMError("Enter an API key.")
        url = "https://api.anthropic.com/v1/models?limit=100"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    elif provider == "gemini":
        if not api_key:
            raise LLMError("Enter an API key.")
        url = GeminiClient.BASE + "/models?pageSize=1000"
        headers = {"x-goog-api-key": api_key}
    else:
        endpoint = PROVIDERS[provider] or base_url
        if not endpoint:
            raise LLMError("Enter the endpoint address.")
        if not endpoint.startswith(("http://", "https://")):
            raise LLMError("The endpoint address must start with http:// or https://.")
        if provider not in ("local", "other") and not api_key:
            raise LLMError("Enter an API key.")
        url = endpoint.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = _http(transport).get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        host = httpx.URL(url).netloc.decode()
        raise LLMError(f"The provider could not be reached at {host}.") from e
    if response.status_code != 200:
        raise LLMError(_status_message(response.status_code, _provider_detail(response, api_key)))
    try:
        body = response.json()
        if provider == "gemini":
            # Newer Gemini models may list only the Interactions API as a method, but they
            # still accept generateContent, so keep every gemini model that is not a
            # special-purpose one (speech, embeddings, images).
            ids = [str(m["name"]) for m in body["models"]
                   if "generateContent" in m.get("supportedGenerationMethods", [])
                   or str(m["name"]).removeprefix("models/").startswith("gemini-")]
        else:
            items = body if isinstance(body, list) else body["data"]  # some services return a bare list
            ids = [str(item["id"]) for item in items]
    except (ValueError, KeyError, TypeError) as e:
        raise LLMError("The provider's reply was not in the expected format.") from e
    ids = [i.removeprefix("models/") for i in ids]
    if provider != "anthropic" and provider != "local":
        ids = [i for i in ids if not any(w in i.lower() for w in _NOT_CHAT)]
    if provider == "gemini":
        ids = [i for i in ids if not any(w in i.lower() for w in ("live", "robotics", "computer-use"))]
    return sorted(set(ids))


# Services an API key can be tried against: (name, provider id, endpoint address).
# OpenRouter is not here: its model list is public, so it cannot confirm a key; its keys
# are recognised by their "sk-or-" prefix instead.
KEY_SERVICES = [
    ("OpenAI", "openai", ""),
    ("Anthropic", "anthropic", ""),
    ("Google Gemini", "gemini", ""),
    ("Groq", "other", "https://api.groq.com/openai/v1"),
    ("Mistral", "other", "https://api.mistral.ai/v1"),
    ("DeepSeek", "other", "https://api.deepseek.com/v1"),
    ("Together", "other", "https://api.together.xyz/v1"),
    ("xAI", "other", "https://api.x.ai/v1"),
    ("Cerebras", "other", "https://api.cerebras.ai/v1"),
    ("Fireworks", "other", "https://api.fireworks.ai/inference/v1"),
]
# Key prefixes that identify one service, so the key is sent nowhere else.
KEY_PREFIXES = [
    ("sk-ant-", "Anthropic"), ("AIza", "Google Gemini"), ("AQ.", "Google Gemini"),
    ("sk-or-", "OpenRouter"), ("gsk_", "Groq"), ("xai-", "xAI"), ("csk-", "Cerebras"),
    ("fw_", "Fireworks"), ("sk-proj-", "OpenAI"),
]
_OPENROUTER = ("OpenRouter", "other", "https://openrouter.ai/api/v1")


def detect_provider(api_key: str, transport=None, timeout: float = 10.0) -> dict:
    """Find which service an API key belongs to, and the models it can use.
    A key with a known prefix is sent only to its own service. Any other key is tried
    against every service in KEY_SERVICES, and the first that accepts it wins."""
    from concurrent.futures import ThreadPoolExecutor

    api_key = (api_key or "").strip()
    if not api_key:
        raise LLMError("Enter an API key.")
    by_name = {name: (name, provider, url) for name, provider, url in [*KEY_SERVICES, _OPENROUTER]}
    known = next((by_name[name] for prefix, name in KEY_PREFIXES if api_key.startswith(prefix)), None)
    candidates = [known] if known else KEY_SERVICES

    def attempt(service):
        name, provider, url = service
        try:
            models = list_models(provider, api_key, url, transport=transport, timeout=timeout)
        except LLMError as e:
            return None, str(e)
        return ({"name": name, "provider": provider, "base_url": url, "models": models}
                if models else None), "It listed no models."

    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        results = list(pool.map(attempt, candidates))
    for found, _ in results:
        if found:
            return found
    if known:
        raise LLMError(f"This looks like a {known[0]} key, but {known[0]} did not accept it. {results[0][1]}")
    raise LLMError("No known provider accepted this key. Check the key, or set the provider up manually.")


LOCAL_SERVERS = [("Ollama", "http://localhost:11434/v1"), ("LM Studio", "http://localhost:1234/v1")]


def detect_local(transport=None, timeout: float = 3.0) -> dict:
    """Find a model server running on this computer, and the models it has."""
    for name, url in LOCAL_SERVERS:
        try:
            models = list_models("local", "", url, transport=transport, timeout=timeout)
        except LLMError:
            continue
        return {"name": name, "provider": "local", "base_url": url, "models": models}
    raise LLMError("No local model server was found. Start Ollama or LM Studio, then try again.")
