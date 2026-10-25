"""Who a provider is, in words: a leaf module with no SDK or Keychain imports, so the day file (and with
it `process`) can name a provider without loading either."""

from urllib.parse import urlsplit

DISPLAY = {"ollama": "Ollama on this Mac", "anthropic": "Anthropic", "openai": "OpenAI", "google": "Google"}
ENDPOINT = "openai@"  # the provider string of an OpenAI-compatible endpoint: openai@<host>


def endpoint_host(base_url: str) -> str:
    """The host (and port, when given) of a base URL, without any user or password in it; the URL itself
    when it has no scheme to parse."""
    url = (base_url or "").strip()
    parts = urlsplit(url)
    if not parts.hostname:
        return url
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{parts.hostname}:{port}" if port else parts.hostname


def provider_id(provider: str, base_url: str = "") -> str:
    """The provider string stored with an insight and used as the Keychain account: the provider's name,
    or `openai@<host>` when OpenAI is used through a base URL."""
    if provider == "openai" and (base_url or "").strip():
        return ENDPOINT + endpoint_host(base_url)
    return provider


def display(provider_id_: str) -> str:
    """The words for a provider string: "OpenAI", or "the endpoint at <host>" for an endpoint."""
    if provider_id_.startswith(ENDPOINT):
        return f"the endpoint at {provider_id_[len(ENDPOINT):]}"
    return DISPLAY.get(provider_id_, provider_id_)


def display_name(cfg) -> str:
    """Who the configured provider sends to, in words."""
    return display(provider_id(cfg.insights_provider, cfg.insights_base_url))
