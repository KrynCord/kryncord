"""Testes de `kryncord.rest.client` — ponta a ponta, transporte simulado.

Cobrem o que a Fase 1 pede: rate limits, 429, 5xx, 4xx, e a política que
recusa repetir `POST`. Nenhum teste dorme nem toca a rede — o relógio é
falso e o `sleeper` registra o que teria esperado.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from kryncord.config import HTTPConfig
from kryncord.errors import DiscordAPIError, HTTPError, RateLimitError
from kryncord.http.authentication import Token
from kryncord.http.routes import generate_route_data
from kryncord.rest.client import MAX_RATE_LIMIT_WAITS, RESTClient
from tests.conftest import FakeClock, FakeSleeper

TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.AbCdEfGhIjKlMnOpQrStUvWxYz"
CHANNEL_A = "123456789012345678"
CHANNEL_B = "987654321098765432"

Factory = Callable[[], httpx.Response | BaseException]

#: Singleton para o default de `make_client` (ver B008).
DEFAULT_TOKEN = Token(value=TOKEN)


def ok(**json_body: Any) -> Factory:
    return lambda: httpx.Response(200, json=json_body or {"ok": True})


def rl(
    *,
    status: int = 200,
    remaining: int = 5,
    reset_after: float = 10.0,
    bucket: str | None = "abc",
    limit: int = 5,
) -> Factory:
    """Resposta com headers de rate limit, o mais comum de todos."""
    headers: list[tuple[str, str]] = [("X-RateLimit-Limit", str(limit))]
    if remaining is not None:
        headers.append(("X-RateLimit-Remaining", str(remaining)))
    if reset_after is not None:
        headers.append(("X-RateLimit-Reset-After", str(reset_after)))
    if bucket is not None:
        headers.append(("X-RateLimit-Bucket", bucket))

    def make() -> httpx.Response:
        return httpx.Response(status, headers=headers, json={"ok": True})

    return make


def rate_limited(
    retry_after: float = 2.0, *, global_limit: bool = False, headers: bool = True
) -> Factory:
    response_headers = [("Retry-After", str(retry_after))]
    if global_limit:
        response_headers.append(("X-RateLimit-Global", "true"))
    if headers:
        response_headers.append(("X-RateLimit-Remaining", "0"))
        response_headers.append(("X-RateLimit-Reset-After", str(retry_after)))

    body = {
        "message": "You are being rate limited.",
        "retry_after": retry_after,
        "global": global_limit,
    }
    return lambda: httpx.Response(429, headers=response_headers, json=body)


def error(status: int, code: int = 0, message: str = "boom") -> Factory:
    return lambda: httpx.Response(status, json={"code": code, "message": message})


def failing(exc: BaseException) -> Factory:
    def make() -> httpx.Response | BaseException:
        return exc

    return make


def make_rest(
    *factories: Factory,
    clock: FakeClock,
    sleeper: FakeSleeper,
    config: HTTPConfig | None = None,
    token: Token | None = DEFAULT_TOKEN,
) -> tuple[RESTClient, list[httpx.Request]]:
    """RESTClient com transportes falsos.

    `factories` é a sequência de respostas; a última se repete. Cada
    resposta é construída na hora — reusar objeto `httpx.Response` daria
    "content already read".
    """
    captured: list[httpx.Request] = []
    seq = list(factories) or [ok()]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = min(len(captured) - 1, len(seq) - 1)
        result = seq[index]()
        if isinstance(result, BaseException):
            raise result
        return result

    client = RESTClient(
        config or HTTPConfig(),
        token=token,
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleeper=sleeper,
    )
    return client, captured


# --------------------------------------------------------------------------
# Sucesso
# --------------------------------------------------------------------------


async def test_successful_request_returns_response(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(url="wss://gateway"), clock=clock, sleeper=sleeper)
    response = await rest.request("GET", "/gateway/bot")
    assert response.json()["url"] == "wss://gateway"
    assert len(captured) == 1


async def test_request_json_decodes(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(ok(id=CHANNEL_A), clock=clock, sleeper=sleeper)
    data = await rest.request_json("GET", f"/channels/{CHANNEL_A}")
    assert data["id"] == CHANNEL_A


async def test_no_wait_when_quota_is_available(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Cota sobrando não pode gerar espera nenhuma."""
    rest, _ = make_rest(rl(remaining=5), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert sleeper.calls == []


async def test_bucket_hash_is_learned(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(rl(bucket="realhash"), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    route = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    assert rest.buckets.hashes[rest.buckets.hash_key("GET", route)].value == "realhash"


async def test_second_bucket_is_seeded_from_first_response(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Sem seeding, a 2ª requisição ignoraria a cota descoberta na 1ª."""
    rest, _ = make_rest(rl(remaining=1, reset_after=5.0), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    await rest.request("GET", f"/channels/{CHANNEL_A}")

    route = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    bucket = rest.buckets.resolve("GET", route)
    assert bucket.state.remaining == 1


async def test_pending_is_released_after_request(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    route = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    bucket = rest.buckets.resolve("GET", route)
    assert bucket.pending == 0


# --------------------------------------------------------------------------
# Rate limit proativo
# --------------------------------------------------------------------------


async def test_waits_when_bucket_is_exhausted(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """A 1ª resposta esgota a cota; a 2ª tem que esperar o reset."""
    rest, captured = make_rest(rl(remaining=0, reset_after=5.0), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    await rest.request("GET", f"/channels/{CHANNEL_A}")

    assert len(captured) == 2
    assert len(sleeper.calls) == 1
    # reset_after (5.0) + offset de segurança (0.05)
    assert sleeper.calls[0] == pytest.approx(5.05)


async def test_wait_advances_clock_so_next_request_passes(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """O sleeper falso anda o relógio — senão o teste travaria em loop."""
    rest, _ = make_rest(rl(remaining=0, reset_after=5.0), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    before = clock()
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert clock() > before


async def test_wait_adds_safety_offset(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Chegar exatamente no instante do reset é apertado demais."""
    rest, _ = make_rest(rl(remaining=0, reset_after=1.0), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert sleeper.calls[0] == pytest.approx(1.05)


async def test_global_429_blocks_before_the_retry(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """A espera global acontece *antes* da tentativa seguinte.

    Note que a espera já consumiu o relógio antes de `request()` retornar —
    por isso o assert é sobre o que o sleeper registrou, não sobre
    `global_limit.exhausted` (que já teria expirado).
    """
    rest, captured = make_rest(
        rate_limited(3.0, global_limit=True), ok(), clock=clock, sleeper=sleeper
    )
    await rest.request("GET", f"/channels/{CHANNEL_A}")

    assert sleeper.calls[0] == pytest.approx(3.0)
    assert len(captured) == 2, "depois da espera, tenta de novo"


async def test_global_limit_blocks_other_buckets(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Travou global, travou tudo — inclusive outro channel."""
    rest, _ = make_rest(
        rate_limited(3.0, global_limit=True), ok(), ok(), clock=clock, sleeper=sleeper
    )
    await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "a"})
    await rest.request("GET", f"/channels/{CHANNEL_B}")
    await rest.request("GET", f"/channels/{CHANNEL_A}")

    # espera global + espera (eventual) de bucket, nessa ordem
    assert sleeper.calls[0] == pytest.approx(3.0)


async def test_global_window_allows_many_requests(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(rl(remaining=999, reset_after=60), clock=clock, sleeper=sleeper)
    for _ in range(20):
        await rest.request("GET", "/gateway/bot")
    assert len(captured) == 20
    assert sleeper.calls == []


# --------------------------------------------------------------------------
# 429
# --------------------------------------------------------------------------


async def test_429_waits_then_retries(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(rate_limited(2.0), ok(), clock=clock, sleeper=sleeper)
    response = await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "oi"})

    assert response.ok
    assert len(captured) == 2
    assert 2.0 in sleeper.calls


async def test_429_does_not_count_as_retry(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """429 não é falha — é o Discord pedindo espera. Não consome retries."""
    rest, captured = make_rest(
        *[rate_limited(1.0)] * 5,
        ok(),
        clock=clock,
        sleeper=sleeper,
        config=HTTPConfig(max_retries=1),
    )
    response = await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert response.ok
    assert len(captured) == 6


async def test_429_without_headers_still_blocks_bucket(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Sublimit: Discord bloqueou mas os headers dizem ter cota."""
    rest, _ = make_rest(rate_limited(4.0, headers=False), ok(), clock=clock, sleeper=sleeper)
    await rest.request("PATCH", f"/channels/{CHANNEL_A}", json={"name": "novo"})
    assert 4.0 in sleeper.calls

    route = generate_route_data("PATCH", f"/channels/{CHANNEL_A}")
    bucket = rest.buckets.resolve("PATCH", route)
    assert bucket.state.exhausted is False, "já deve ter expirado após a espera"


async def test_429_loop_is_capped(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Dez 429 seguidos significam cálculo errado. Insistir piora."""
    rest, captured = make_rest(rate_limited(1.0), clock=clock, sleeper=sleeper)
    with pytest.raises(RateLimitError, match="persistiu"):
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert len(captured) == MAX_RATE_LIMIT_WAITS + 1


async def test_rate_limit_error_carries_context(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(rate_limited(7.5), clock=clock, sleeper=sleeper)
    with pytest.raises(RateLimitError) as info:
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert info.value.retry_after == pytest.approx(7.5)
    assert info.value.status == 429


# --------------------------------------------------------------------------
# 5xx
# --------------------------------------------------------------------------


async def test_5xx_is_retried_for_get(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(error(500), ok(), clock=clock, sleeper=sleeper)
    response = await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert response.ok
    assert len(captured) == 2


async def test_5xx_exhausted_raises_http_error(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(error(503), clock=clock, sleeper=sleeper)
    with pytest.raises(HTTPError) as info:
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert info.value.status == 503
    assert len(captured) == HTTPConfig().max_retries + 1


async def test_5xx_is_never_retried_for_post(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """POST que deu 500 pode ter criado a mensagem. Repetir duplica."""
    rest, captured = make_rest(error(500), ok(), clock=clock, sleeper=sleeper)
    with pytest.raises(HTTPError):
        await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "oi"})
    assert len(captured) == 1, "POST não pode ter sido repetido"


async def test_5xx_is_retried_for_patch(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """PATCH define estado — aplicar duas vezes dá o mesmo resultado."""
    rest, captured = make_rest(error(500), ok(), clock=clock, sleeper=sleeper)
    response = await rest.request("PATCH", f"/channels/{CHANNEL_A}", json={"name": "x"})
    assert response.ok
    assert len(captured) == 2


async def test_retries_can_be_disabled(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(
        error(500), ok(), clock=clock, sleeper=sleeper, config=HTTPConfig(max_retries=0)
    )
    with pytest.raises(HTTPError):
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert len(captured) == 1


async def test_transport_and_5xx_share_one_retry_budget(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Regressão: falha de transporte e 5xx competem pelo mesmo orçamento.

    Com contadores separados, um 500 e um ConnectError consumiriam duas
    "vidas" por falha e chegariam ao `200` final — 3 requisições com
    `max_retries=1`, quando a config promete 2.
    """
    rest, captured = make_rest(
        error(500),
        failing(httpx.ConnectError("refused", request=httpx.Request("GET", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
        config=HTTPConfig(max_retries=1),
    )

    with pytest.raises(HTTPError):
        await rest.request("GET", f"/channels/{CHANNEL_A}")

    assert len(captured) == 2, "max_retries=1 significa 2 requisições no total"


async def test_budget_is_not_shared_with_rate_limits(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """429 é espera, não falha — não pode consumir o orçamento de retries."""
    rest, captured = make_rest(
        rate_limited(1.0),
        error(500),
        error(500),
        error(500),
        clock=clock,
        sleeper=sleeper,
        config=HTTPConfig(max_retries=2),
    )

    with pytest.raises(HTTPError):
        await rest.request("GET", f"/channels/{CHANNEL_A}")

    # 1 de rate limit + (max_retries + 1) de 5xx
    assert len(captured) == 1 + 3


# --------------------------------------------------------------------------
# 4xx
# --------------------------------------------------------------------------


async def test_4xx_raises_discord_api_error(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(
        error(404, code=10003, message="Unknown Channel"), clock=clock, sleeper=sleeper
    )
    with pytest.raises(DiscordAPIError) as info:
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert info.value.status == 404
    assert info.value.code == 10003
    assert "Unknown Channel" in str(info.value)
    assert len(captured) == 1, "4xx não se repete"


async def test_4xx_is_never_retried(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(error(403, message="Missing Access"), clock=clock, sleeper=sleeper)
    with pytest.raises(DiscordAPIError):
        await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert len(captured) == 1


async def test_oauth_error_shape_is_understood(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """OAuth manda `error` + `error_description`, não `code` + `message`."""

    def oauth() -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Code expired"}
        )

    rest, _ = make_rest(oauth, clock=clock, sleeper=sleeper)
    with pytest.raises(DiscordAPIError, match="Code expired"):
        await rest.request("POST", "/oauth2/token", json={}, versioned=False)


async def test_4xx_without_json_body_still_raises(clock: FakeClock, sleeper: FakeSleeper) -> None:
    def html() -> httpx.Response:
        return httpx.Response(404, text="<html>not found</html>")

    rest, _ = make_rest(html, clock=clock, sleeper=sleeper)
    with pytest.raises(DiscordAPIError, match="sem corpo de erro"):
        await rest.request("GET", f"/channels/{CHANNEL_A}")


async def test_401_does_not_leak_token(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(error(401, message="401: Unauthorized"), clock=clock, sleeper=sleeper)
    with pytest.raises(DiscordAPIError) as info:
        await rest.request("GET", "/users/@me")
    assert TOKEN not in str(info.value)


# --------------------------------------------------------------------------
# Falha de transporte
# --------------------------------------------------------------------------


async def test_connect_error_is_retried_for_post(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """ConnectError = conexão nunca estabelecida = nada chegou.

    Diferente de timeout (ambíguo), aqui sabemos que o POST não foi
    processado — repetir é seguro.
    """
    rest, captured = make_rest(
        failing(httpx.ConnectError("refused", request=httpx.Request("POST", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
    )
    response = await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "oi"})
    assert response.ok
    assert len(captured) == 2


async def test_read_timeout_is_never_retried_for_post(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Timeout = ambíguo. O POST pode ter sido processado já."""
    rest, captured = make_rest(
        failing(httpx.ReadTimeout("t", request=httpx.Request("POST", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
    )
    with pytest.raises(HTTPError) as info:
        await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "oi"})
    assert info.value.failure_kind == "ambiguous"
    assert len(captured) == 1


async def test_connect_error_is_retried_for_get(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(
        failing(httpx.ConnectError("refused", request=httpx.Request("GET", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
    )
    response = await rest.request("GET", f"/channels/{CHANNEL_A}")
    assert response.ok
    assert len(captured) == 2


async def test_read_timeout_is_not_retried_for_post(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Timeout = ambíguo. O POST pode ter sido processado."""
    rest, captured = make_rest(
        failing(httpx.ReadTimeout("t", request=httpx.Request("POST", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
    )
    with pytest.raises(HTTPError) as info:
        await rest.request("POST", f"/channels/{CHANNEL_A}/messages", json={"content": "oi"})
    assert info.value.failure_kind == "ambiguous"
    assert len(captured) == 1


async def test_read_timeout_is_retried_for_get(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(
        failing(httpx.ReadTimeout("t", request=httpx.Request("GET", "https://x"))),
        ok(),
        clock=clock,
        sleeper=sleeper,
    )
    assert (await rest.request("GET", f"/channels/{CHANNEL_A}")).ok
    assert len(captured) == 2


# --------------------------------------------------------------------------
# Serialização por bucket
# --------------------------------------------------------------------------


async def test_second_request_waits_for_first(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Uma requisição em voo por `hash:major`. É o que evita 429 por fila."""
    rest, _ = make_rest(rl(remaining=5), clock=clock, sleeper=sleeper)
    route = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    bucket = rest.buckets.resolve("GET", route)

    await bucket.lock.acquire()
    try:
        task = asyncio.create_task(rest.request("GET", f"/channels/{CHANNEL_A}"))
        await asyncio.sleep(0)
        assert task.done() is False, "deveria estar esperando o lock"
    finally:
        bucket.lock.release()

    await asyncio.wait_for(task, timeout=1)


async def test_different_majors_use_different_locks(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Channel A travado não pode segurar o channel B."""
    rest, _ = make_rest(rl(remaining=5), clock=clock, sleeper=sleeper)
    route_a = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    bucket_a = rest.buckets.resolve("GET", route_a)

    await bucket_a.lock.acquire()
    try:
        response = await asyncio.wait_for(rest.request("GET", f"/channels/{CHANNEL_B}"), timeout=1)
        assert response.ok
    finally:
        bucket_a.lock.release()


async def test_same_route_same_channel_reuses_one_bucket(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Mesmo método, mesma rota, mesmo channel → mesma instância de `Bucket`.

    A serialização depende disto: se cada requisição criasse um `Bucket`
    novo, o `asyncio.Lock` seria novo também, e nada seria serializado.
    """
    rest, _ = make_rest(rl(remaining=5), clock=clock, sleeper=sleeper)
    route = generate_route_data("GET", f"/channels/{CHANNEL_A}")
    first = rest.buckets.resolve("GET", route)
    second = rest.buckets.resolve("GET", route)
    assert first is second


async def test_different_majors_get_separate_buckets_after_learning(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Mesmo hash do Discord, majors diferentes → contadores separados.

    `/channels/A` e `/channels/B` caem no mesmo hash, mas o Discord conta
    por servidor. Compartilhar a instância faria A bloquear B à toa.
    """
    rest, _ = make_rest(rl(bucket="mesmohash"), clock=clock, sleeper=sleeper)
    await rest.request("GET", f"/channels/{CHANNEL_A}")
    await rest.request("GET", f"/channels/{CHANNEL_B}")

    first = rest.buckets.resolve("GET", generate_route_data("GET", f"/channels/{CHANNEL_A}"))
    second = rest.buckets.resolve("GET", generate_route_data("GET", f"/channels/{CHANNEL_B}"))

    assert first is not second
    assert first.key != second.key
    assert first.key.startswith("mesmohash:")
    assert second.key.startswith("mesmohash:")


async def test_different_endpoints_use_different_buckets(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """`/channels/:id` e `/channels/:id/messages` são buckets distintos."""
    rest, _ = make_rest(rl(remaining=5), clock=clock, sleeper=sleeper)
    channel = rest.buckets.resolve("GET", generate_route_data("GET", f"/channels/{CHANNEL_A}"))
    messages = rest.buckets.resolve(
        "POST", generate_route_data("POST", f"/channels/{CHANNEL_A}/messages")
    )
    assert channel is not messages


# --------------------------------------------------------------------------
# Endpoints essenciais
# --------------------------------------------------------------------------


async def test_get_gateway_bot(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(url="wss://gateway.discord.gg"), clock=clock, sleeper=sleeper)
    data = await rest.get_gateway_bot()
    assert data["url"].startswith("wss://")
    assert captured[0].url.path == "/api/v10/gateway/bot"


async def test_get_current_user(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(id="1", username="kryncord"), clock=clock, sleeper=sleeper)
    data = await rest.get_current_user()
    assert data["username"] == "kryncord"
    assert captured[0].headers["Authorization"] == f"Bot {TOKEN}"


async def test_send_message(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(id="9"), clock=clock, sleeper=sleeper)
    await rest.send_message(CHANNEL_A, "olá")
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == f"/api/v10/channels/{CHANNEL_A}/messages"
    assert b'"content"' in request.content


async def test_get_channel(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(id=CHANNEL_A), clock=clock, sleeper=sleeper)
    data = await rest.get_channel(CHANNEL_A)
    assert data["id"] == CHANNEL_A
    assert captured[0].url.path == f"/api/v10/channels/{CHANNEL_A}"


async def test_get_guild(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(ok(id="7"), clock=clock, sleeper=sleeper)
    data = await rest.get_guild("7")
    assert data["id"] == "7"
    assert captured[0].url.path == "/api/v10/guilds/7"


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


async def test_context_manager_closes_transport(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, _ = make_rest(clock=clock, sleeper=sleeper)
    async with rest:
        await rest.request("GET", "/gateway/bot")
    with pytest.raises(HTTPError, match="já fechado"):
        await rest.request("GET", "/gateway/bot")


async def test_set_token_after_construction(clock: FakeClock, sleeper: FakeSleeper) -> None:
    rest, captured = make_rest(clock=clock, sleeper=sleeper, token=None)
    rest.set_token(Token(value=TOKEN))
    await rest.request("GET", "/users/@me")
    assert captured[0].headers["Authorization"] == f"Bot {TOKEN}"


async def test_case_insensitive_method(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Quem escreve 'get' minúsculo não merece ValueError obscura."""
    rest, captured = make_rest(clock=clock, sleeper=sleeper)
    await rest.request("get", "/gateway/bot")
    assert captured[0].method == "GET"
