"""Fachada REST: fila, rate limit, repetição e leitura de resposta.

`http.client` faz uma tentativa e devolve. Esta classe é quem decide
**quando** aquela tentativa pode acontecer:

1. espera a fila do bucket (uma requisição em voo por ``hash:major``);
2. espera a cota local e a global;
3. manda, lê os headers, alimenta o bucket;
4. em 429, espera o tempo que o Discord pediu e tenta de novo;
5. em 5xx, aplica a política de repetição — que recusa `POST`;
6. em 4xx, levanta `DiscordAPIError` já com código e mensagem.

A fila fica travada durante todo o ciclo. É proposital: se soltasse no
meio de um retry, outra requisição do mesmo bucket entraria na frente e
o Discord responderia 429 de novo.

O `sleeper` é injetável. Sem isso, todo teste de rate limit dormiria de
verdade — e um teste que espera 30 segundos não é teste, é build.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from kryncord.config import HTTPConfig
from kryncord.errors import DiscordAPIError, HTTPError, RateLimitError
from kryncord.http.authentication import Token
from kryncord.http.buckets import Bucket, BucketManager
from kryncord.http.client import HTTPClient
from kryncord.http.rate_limits import (
    Clock,
    RateLimitHeaders,
    monotonic_clock,
    normalize_offset,
    parse_429,
)
from kryncord.http.request import HTTPMethod, Request
from kryncord.http.response import Response
from kryncord.http.retries import FailureKind, RetryPolicy
from kryncord.http.routes import RouteData, generate_route_data
from kryncord.logging import get_logger

log = get_logger("rest")

Sleeper = Callable[[float], Awaitable[None]]

#: Trava de segurança contra 429 em loop. Rate limit esperado não é
#: falha, mas um loop infinito é — se o Discord responder 429 dez vezes
#: seguidas, algo está errado com o nosso cálculo, e insistir só piora.
MAX_RATE_LIMIT_WAITS = 10


async def _real_sleep(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


class RESTClient:
    """Fachada que une transporte, buckets e política de erro."""

    def __init__(
        self,
        config: HTTPConfig,
        *,
        token: Token | None = None,
        transport: Any = None,
        policy: RetryPolicy | None = None,
        clock: Clock = monotonic_clock,
        sleeper: Sleeper = _real_sleep,
    ) -> None:
        self._config = config
        self._clock = clock
        self._sleep = sleeper
        self._policy = policy or RetryPolicy(max_retries=config.max_retries)
        self._buckets = BucketManager(
            requests_per_second=config.global_requests_per_second,
            clock=clock,
        )
        self._http = HTTPClient(config, token=token, transport=transport)
        self._offset = normalize_offset(config.offset_ms)

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        route: str,
        *,
        query: dict[str, Any] | None = None,
        json: Any = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
        reason: str | None = None,
        versioned: bool = True,
    ) -> Response:
        """Envia uma requisição, respeitando rate limit e política de retry.

        Erros de 4xx/5xx já vêm convertidos em `DiscordAPIError` ou
        `HTTPError`. O que volta é a `Response` em si — quem precisa de
        JSON chama `.json()` ou `request_json`.
        """
        request = Request(
            method=HTTPMethod(method.upper()),
            route=route,
            query=query or {},
            headers=headers or {},
            json=json,
            body=body,
            auth=auth,
            reason=reason,
            versioned=versioned,
        )
        return await self.send(request)

    async def request_json(self, method: str, route: str, **kwargs: Any) -> Any:
        """`request()` já decodificado. O caso comum dos endpoints."""
        response = await self.request(method, route, **kwargs)
        return response.json()

    async def send(self, request: Request) -> Response:
        """Núcleo: fila → cota → tentativas. Aceita um `Request` pronto."""
        route = generate_route_data(request.method.value, request.route)
        bucket = self._buckets.resolve(request.method.value, route)

        bucket.pending += 1
        try:
            async with bucket.lock:
                await self._wait_for_capacity(bucket)
                return await self._attempt(request, route, bucket)
        finally:
            bucket.pending -= 1

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RESTClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    @property
    def buckets(self) -> BucketManager:
        """Exposto para teste e para o sweeper do `Client`."""
        return self._buckets

    def set_token(self, token: Token | None) -> None:
        self._http.set_token(token)

    # ------------------------------------------------------------------
    # Espera de cota
    # ------------------------------------------------------------------

    async def _wait_for_capacity(self, bucket: Bucket) -> None:
        """Dorme até que global e local permitam disparar.

        Ordem: global primeiro. Se o global está travado, adianta nada
        olhar o bucket — e esperar o bucket primeiro atrasaria a fila
        inteira atrás de uma janela que já vai zerar.
        """
        global_limit = self._buckets.global_limit
        while global_limit.exhausted:
            wait = global_limit.seconds_until_reset + self._offset
            log.debug("rate limit global: esperando %.3fs", wait)
            await self._sleep(wait)

        while bucket.state.exhausted:
            wait = bucket.state.seconds_until_reset + self._offset
            log.debug("bucket %s: esperando %.3fs", bucket.key, wait)
            await self._sleep(wait)

    # ------------------------------------------------------------------
    # Ciclo de tentativas
    # ------------------------------------------------------------------

    async def _attempt(self, request: Request, route: RouteData, bucket: Bucket) -> Response:
        """Loop único de tentativas.

        Falha de transporte e 5xx competem pelo **mesmo** orçamento de
        `max_retries`. Tinham contadores separados, e aí um timeout seguido
        de um 500 consumia duas "vidas" por falha — no pior caso
        `(max_retries + 1)²` requisições, quando a config promete
        `max_retries + 1`. Um contador só torna o teto verdadeiro.

        429 fica fora do orçamento: não é falha, é o Discord pedindo
        espera. Ele tem trav própria (`MAX_RATE_LIMIT_WAITS`).
        """
        retries_done = 0
        rate_limit_waits = 0

        while True:
            self._buckets.global_limit.consume()

            try:
                response = await self._http.send(request)
            except HTTPError as exc:
                if not self._should_retry_transport(request, exc, retries_done):
                    raise
                kind = FailureKind(exc.failure_kind or FailureKind.AMBIGUOUS.value)
                delay = self._policy.backoff(retries_done)
                log.debug(
                    "%s %s: transporte falhou (%s), repetindo em %.3fs (%d/%d)",
                    request.method,
                    request.route,
                    kind.value,
                    delay,
                    retries_done + 1,
                    self._policy.max_retries,
                )
                await self._sleep(delay)
                retries_done += 1
                continue

            headers = RateLimitHeaders.from_response(response)
            bucket.state.update(headers)
            self._buckets.learn(request.method.value, route, headers)

            if response.status == 429:
                rate_limit_waits += 1
                if rate_limit_waits > MAX_RATE_LIMIT_WAITS:
                    raise self._rate_limit_error(response, bucket, gave_up=True)
                await self._handle_429(response, bucket)
                continue

            if response.status >= 500:
                if self._policy.should_retry(request, FailureKind.SERVER_ERROR, retries_done):
                    delay = self._policy.backoff(retries_done)
                    log.debug(
                        "%s %s → %d, repetindo em %.3fs (%d/%d)",
                        request.method,
                        request.route,
                        response.status,
                        delay,
                        retries_done + 1,
                        self._policy.max_retries,
                    )
                    await self._sleep(delay)
                    retries_done += 1
                    continue
                raise HTTPError(
                    f"{request.method} {request.route} falhou com {response.status} "
                    f"após {retries_done} repetição(ões): {response.text[:200]}",
                    status=response.status,
                    failure_kind=FailureKind.SERVER_ERROR.value,
                )

            if 400 <= response.status < 500:
                raise self._api_error(response, request)

            if not response.ok:
                # 3xx já tratado pelo transporte (follow_redirects), mas
                # um status fora de 2xx/4xx/5xx não é erro de API — volta
                # cru para o chamador decidir.
                log.debug("status inesperado %d em %s", response.status, request.route)

            return response

    def _should_retry_transport(self, request: Request, exc: HTTPError, retries_done: int) -> bool:
        """`failure_kind=None` significa que não temos diagnóstico.

        Sem diagnóstico, repetir é palpite — e palpite num `POST` cria
        mensagem duplicada. Deixa a exceção subir.
        """
        if exc.failure_kind is None:
            return False
        kind = FailureKind(exc.failure_kind)
        return self._policy.should_retry(request, kind, retries_done)

    # ------------------------------------------------------------------
    # 429
    # ------------------------------------------------------------------

    async def _handle_429(self, response: Response, bucket: Bucket) -> None:
        retry_after, is_global = parse_429(response)

        if is_global:
            log.debug("429 global: travando tudo por %.3fs", retry_after)
            self._buckets.global_limit.force_limit(retry_after)
        elif not bucket.state.exhausted:
            # Não temos cota local esgotada nos headers, mas o Discord
            # bloqueou. É o caso de *sublimit* — uma ação específica
            # (mudar `name`/`topic` de canal) com cota própria dentro do
            # bucket. Tratar como cota do bucket é conservador: segura
            # mais gente do que o necessário, mas nunca deixa passar na
            # frente de quem foi bloqueado.
            log.debug("429 em %s sem cota local: tratando como sublimit", bucket.key)
            bucket.state.force_limit(retry_after)

        await self._sleep(retry_after)

    def _rate_limit_error(self, response: Response, bucket: Bucket, *, gave_up: bool) -> HTTPError:
        retry_after, is_global = parse_429(response)
        message = (
            f"Rate limit persistiu após {MAX_RATE_LIMIT_WAITS} esperas em "
            f"{bucket.key}; última espera seria {retry_after:.3f}s"
            if gave_up
            else f"Rate limit em {bucket.key}"
        )
        return RateLimitError(
            message,
            retry_after=retry_after,
            global_limit=is_global,
            bucket=bucket.state.bucket_hash,
        )

    # ------------------------------------------------------------------
    # 4xx
    # ------------------------------------------------------------------

    def _api_error(self, response: Response, request: Request) -> HTTPError:
        data: Any
        try:
            data = response.json()
        except HTTPError:
            # Corpo não-JSON num 4xx. Não é o caso comum, mas um proxy de
            # erro devolve HTML — e a mensagem abaixo ainda ajuda.
            data = None

        if isinstance(data, dict) and "error" in data and "code" not in data:
            # Erro OAuth: `error` + `error_description`, não `code`.
            message = str(data.get("error_description") or data.get("error"))
            return DiscordAPIError(
                f"{request.method} {request.route} → {response.status}: {message}",
                status=response.status,
            )

        if isinstance(data, dict) and "message" in data:
            message = str(data["message"])
            code = data.get("code")
            errors = data.get("errors")
            return DiscordAPIError(
                f"{request.method} {request.route} → {response.status}: {message}",
                status=response.status,
                code=int(code) if isinstance(code, int) else None,
                errors=errors if isinstance(errors, dict) else None,
            )

        # Resposta 4xx sem corpo reconhecível — não inventa mensagem.
        return DiscordAPIError(
            f"{request.method} {request.route} → {response.status} "
            f"sem corpo de erro: {response.text[:200]!r}",
            status=response.status,
        )

    # ------------------------------------------------------------------
    # Endpoints essenciais (Fase 1)
    # ------------------------------------------------------------------

    async def get_gateway_bot(self) -> Any:
        """``GET /gateway/bot`` — URL do WebSocket e contagem de shards."""
        return await self.request_json("GET", "/gateway/bot")

    async def get_current_user(self) -> Any:
        """``GET /users/@me`` — quem somos. Bom teste de token."""
        return await self.request_json("GET", "/users/@me")

    async def get_channel(self, channel_id: str | int) -> Any:
        return await self.request_json("GET", f"/channels/{channel_id}")

    async def get_guild(self, guild_id: str | int) -> Any:
        return await self.request_json("GET", f"/guilds/{guild_id}")

    async def send_message(self, channel_id: str | int, content: str, **kwargs: Any) -> Any:
        """``POST /channels/:id/messages`` — o endpoint mais usado de todos."""
        return await self.request_json(
            "POST",
            f"/channels/{channel_id}/messages",
            json={"content": content, **kwargs},
        )
