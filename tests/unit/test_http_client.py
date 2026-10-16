"""Testes de `kryncord.http.client` — transporte simulado, sem rede."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from kryncord.config import HTTPConfig
from kryncord.errors import HTTPError
from kryncord.http.authentication import Token
from kryncord.http.client import HTTPClient
from kryncord.http.request import HTTPMethod, Request
from kryncord.version import __version__

TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.AbCdEfGhIjKlMnOpQrStUvWxYz"

#: Singleton para o default de `make_client`. Um `Token(...)` inline no
#: signature seria recriado a cada chamada e B008 acusaria.
DEFAULT_TOKEN = Token(value=TOKEN)


def make_client(
    handler: Any = None,
    *,
    config: HTTPConfig | None = None,
    token: Token | None = DEFAULT_TOKEN,
) -> tuple[HTTPClient, list[httpx.Request]]:
    """Cliente com transporte falso, e a lista de requisições capturadas."""
    captured: list[httpx.Request] = []

    def default_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    def real_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    transport = httpx.MockTransport(real_handler if handler else default_handler)
    client = HTTPClient(config or HTTPConfig(), token=token, transport=transport)
    return client, captured


# --------------------------------------------------------------------------
# URL
# --------------------------------------------------------------------------


async def test_url_includes_api_version() -> None:
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert str(captured[0].url) == "https://discord.com/api/v10/gateway/bot"


async def test_url_appends_query() -> None:
    client, captured = make_client()
    await client.send(
        Request(method=HTTPMethod.GET, route="/guilds/1/channels", query={"limit": 5})
    )
    assert str(captured[0].url) == "https://discord.com/api/v10/guilds/1/channels?limit=5"


async def test_versioned_false_omits_version_prefix() -> None:
    """Endpoints de OAuth não levam /v10."""
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/oauth2/@me", versioned=False))
    assert str(captured[0].url) == "https://discord.com/api/oauth2/@me"


async def test_custom_base_url_is_respected() -> None:
    client, captured = make_client(config=HTTPConfig(base_url="https://ptb.discord.com/api"))
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert str(captured[0].url) == "https://ptb.discord.com/api/v10/gateway/bot"


async def test_trailing_slash_on_base_is_normalized() -> None:
    client, captured = make_client(config=HTTPConfig(base_url="https://discord.com/api/"))
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert str(captured[0].url) == "https://discord.com/api/v10/gateway/bot"


async def test_query_without_params_adds_no_question_mark() -> None:
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert "?" not in str(captured[0].url)


# --------------------------------------------------------------------------
# Headers
# --------------------------------------------------------------------------


async def test_user_agent_follows_discord_format() -> None:
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    agent = captured[0].headers["User-Agent"]
    assert agent.startswith("KrynCord (https://")
    # a versão vem de `version.py` — não se repete o literal aqui, senão
    # cada bump de versão quebraria um teste que não tem nada a ver.
    assert __version__ in agent


async def test_user_agent_appendix_is_appended() -> None:
    client, captured = make_client(config=HTTPConfig(user_agent_appendix="mybot/2.0"))
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert captured[0].headers["User-Agent"].endswith("mybot/2.0")


async def test_authorization_header_is_sent() -> None:
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/users/@me"))
    assert captured[0].headers["Authorization"] == f"Bot {TOKEN}"


async def test_auth_false_omits_authorization() -> None:
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot", auth=False))
    assert "Authorization" not in captured[0].headers


async def test_auth_true_without_token_raises() -> None:
    """Erro claro em vez de mandar `Authorization:` vazio e receber 401."""
    client, _ = make_client(token=None)
    with pytest.raises(HTTPError, match="sem token configurado"):
        await client.send(Request(method=HTTPMethod.GET, route="/users/@me"))


async def test_error_message_does_not_contain_token() -> None:
    """O erro de 'token ausente' não pode revelar o que estava configurado."""
    client, _ = make_client(token=None)
    with pytest.raises(HTTPError) as info:
        await client.send(Request(method=HTTPMethod.GET, route="/users/@me"))
    assert TOKEN not in str(info.value)


async def test_custom_prefix_is_used() -> None:
    client, captured = make_client(token=Token(value=TOKEN, prefix="Bearer"))
    await client.send(Request(method=HTTPMethod.GET, route="/users/@me"))
    assert captured[0].headers["Authorization"] == f"Bearer {TOKEN}"


async def test_audit_reason_is_uri_encoded() -> None:
    """Motivo com acento daria 400 se mandado cru."""
    client, captured = make_client()
    await client.send(Request(method=HTTPMethod.DELETE, route="/channels/1", reason="limpeza çãé"))
    reason = captured[0].headers["X-Audit-Log-Reason"]
    assert "%" in reason
    assert "ç" not in reason


async def test_json_body_sets_content_type() -> None:
    client, captured = make_client()
    await client.send(
        Request(method=HTTPMethod.POST, route="/channels/1/messages", json={"content": "oi"})
    )
    request = captured[0]
    assert request.headers["Content-Type"].startswith("application/json")
    assert b'"content"' in (request.content or b"")


async def test_get_never_sends_a_body() -> None:
    """Um GET com corpo não falharia — o Discord ignoraria, e o teste que
    deveria acusar não acusaria."""
    client, captured = make_client()

    await client.send(
        Request(method=HTTPMethod.GET, route="/gateway/bot", json={"nao": "deveria ir"})
    )
    assert not captured[0].content


async def test_headers_from_request_merge_over_defaults() -> None:
    client, captured = make_client()
    await client.send(
        Request(
            method=HTTPMethod.GET,
            route="/gateway/bot",
            headers={"Accept": "text/plain", "X-Custom": "1"},
        )
    )
    assert captured[0].headers["Accept"] == "text/plain"
    assert captured[0].headers["X-Custom"] == "1"


# --------------------------------------------------------------------------
# Resposta
# --------------------------------------------------------------------------


async def test_response_headers_are_lowercased() -> None:
    client, _ = make_client(
        lambda _: httpx.Response(
            200,
            headers={"X-RateLimit-Bucket": "abc"},
            json={"ok": True},
        )
    )
    response = await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert response.header("x-ratelimit-bucket") == "abc"
    assert response.header("X-RATELIMIT-BUCKET") == "abc"


async def test_response_json_is_decoded() -> None:
    client, _ = make_client(lambda _: httpx.Response(200, json={"url": "wss://x"}))
    response = await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert response.json() == {"url": "wss://x"}
    assert response.ok is True


async def test_response_ok_is_false_for_4xx() -> None:
    client, _ = make_client(lambda _: httpx.Response(404, json={"message": "nope"}))
    response = await client.send(Request(method=HTTPMethod.GET, route="/channels/1"))
    assert response.ok is False
    assert response.status == 404


async def test_empty_204_body_is_not_json_error() -> None:
    """DELETE devolve 204 sem corpo. `json()` não pode estourar."""
    client, _ = make_client(lambda _: httpx.Response(204))
    response = await client.send(Request(method=HTTPMethod.DELETE, route="/channels/1"))
    assert response.status == 204
    assert response.json() is None


async def test_malformed_json_raises_http_error_not_json_error() -> None:
    """Quem trata falha HTTP não deve precisar capturar JSONDecodeError."""
    client, _ = make_client(lambda _: httpx.Response(200, text="<html>não é json</html>"))
    response = await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    with pytest.raises(HTTPError, match="não é JSON"):
        response.json()


# --------------------------------------------------------------------------
# Falhas de transporte
# --------------------------------------------------------------------------


async def test_connect_error_becomes_http_error_with_kind() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = make_client(handler)
    with pytest.raises(HTTPError) as info:
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert info.value.failure_kind == "not_sent"


async def test_read_timeout_becomes_http_error_with_kind() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client, _ = make_client(handler)
    with pytest.raises(HTTPError) as info:
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert info.value.failure_kind == "ambiguous"


async def test_transport_error_keeps_original_as_cause() -> None:
    """Debugging sem o `__cause__` exigiria reproduzir a falha."""

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = make_client(handler)
    with pytest.raises(HTTPError) as info:
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    assert isinstance(info.value.__cause__, httpx.ConnectError)


async def test_transport_error_message_names_the_route() -> None:
    """'Falha em GET /gateway/bot' é acionável; 'error' não é."""

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = make_client(handler)
    with pytest.raises(HTTPError, match="/gateway/bot"):
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


async def test_send_after_close_raises() -> None:
    client, _ = make_client()
    await client.aclose()
    with pytest.raises(HTTPError, match="já fechado"):
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))


async def test_close_is_idempotent() -> None:
    client, _ = make_client()
    await client.aclose()
    await client.aclose()


async def test_context_manager_closes() -> None:
    client = HTTPClient(
        HTTPConfig(),
        token=Token(value=TOKEN),
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    async with client:
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))
    with pytest.raises(HTTPError, match="já fechado"):
        await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot"))


async def test_set_token_after_construction() -> None:
    client, captured = make_client(token=None)
    client.set_token(Token(value=TOKEN))
    await client.send(Request(method=HTTPMethod.GET, route="/users/@me"))
    assert captured[0].headers["Authorization"] == f"Bot {TOKEN}"


async def test_set_token_none_clears() -> None:
    client, _captured = make_client()
    client.set_token(None)
    await client.send(Request(method=HTTPMethod.GET, route="/gateway/bot", auth=False))
    assert client.token is None
