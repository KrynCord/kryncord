"""Execução de requisições HTTP.

Esta camada faz **uma** tentativa. Não decide nada sobre rate limit nem
sobre repetição — só monta URL e headers, manda, e devolve a resposta
normalizada. Quem decide fila, bucket e retry é `rest.client`.

Isso mantém a testabilidade: dá para trocar o transporte inteiro por um
``httpx.MockTransport`` e exercitar esta classe sem rede alguma.

Duas regras de segurança valem aqui: o token entra no header mas nunca na
mensagem de erro, e exceção de transporte vira `HTTPError` com o
`failure_kind` anexado — sem isso, quem decide repetir não saberia o que
aconteceu.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from kryncord.config import HTTPConfig
from kryncord.errors import HTTPError
from kryncord.http.authentication import Token, build_auth_header
from kryncord.http.request import BODYLESS_METHODS, Request
from kryncord.http.response import Response
from kryncord.http.retries import classify_transport_error
from kryncord.logging import get_logger
from kryncord.version import __version__

log = get_logger("http")

#: Formato do ``User-Agent`` que o Discord exige.
#: ``<biblioteca> (<url>, <versão>) <extra>``.
_USER_AGENT_TEMPLATE = "KrynCord (https://github.com/KrynCord/kryncord, {version})"


class HTTPClient:
    """Transporte HTTP com um `httpx.AsyncClient` por trás."""

    def __init__(
        self,
        config: HTTPConfig,
        *,
        token: Token | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._config = config
        self._token = token
        self._user_agent = user_agent or self._build_user_agent(config)

        limits = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout),
            limits=limits,
            transport=transport,
            follow_redirects=True,
        )
        self._closed = False

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    async def send(self, request: Request) -> Response:
        """Executa uma tentativa. Não repete, não espera rate limit."""
        if self._closed:
            raise HTTPError(
                f"Cliente HTTP já fechado: {request.method} {request.route}. "
                "Chame aclose() só depois de todas as requisições."
            )

        url = self.build_url(request)
        headers = self.build_headers(request)
        content, json_body = _body_of(request)

        log.debug("%s %s", request.method, url)

        try:
            raw = await self._client.request(
                request.method.value,
                url,
                headers=headers,
                content=content,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(request, url, exc) from exc

        return Response.of(
            status=raw.status_code,
            headers=list(raw.headers.items()),
            body=raw.content,
            url=str(raw.url),
        )

    async def aclose(self) -> None:
        """Fecha o pool de conexões. Idempotente."""
        if self._closed:
            return
        self._closed = True
        await self._client.aclose()

    async def __aenter__(self) -> HTTPClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def build_url(self, request: Request) -> str:
        base = self._config.base_url.rstrip("/")
        prefix = f"/v{self._config.version}" if request.versioned else ""
        return f"{base}{prefix}{request.path_with_query}"

    def build_headers(self, request: Request) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        if request.auth:
            if self._token is None:
                # O token não entra na mensagem. Dizer "token ausente"
                # ajuda; dizer o que estava lá não.
                raise HTTPError(
                    f"Requisição autenticada sem token configurado: "
                    f"{request.method} {request.route}. "
                    "Chame set_token() antes de usar endpoints autenticados."
                )
            headers.update(build_auth_header(self._token))

        if request.reason:
            # Audit log aceita URI-encoded; caracteres não-ASCII no motivo
            # dariam 400.
            headers["X-Audit-Log-Reason"] = quote(request.reason, safe="")

        headers.update(request.headers)

        if request.json is not None and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        return headers

    def set_token(self, token: Token | None) -> None:
        """Troca o token. Também é o que o handler de 401 chama."""
        self._token = token

    @property
    def token(self) -> Token | None:
        return self._token

    # ------------------------------------------------------------------
    # Erros
    # ------------------------------------------------------------------

    def _transport_error(self, request: Request, url: str, exc: httpx.HTTPError) -> HTTPError:
        kind = classify_transport_error(exc)
        if kind is None:
            # Não classificável: deixa o chamador ver a exceção original
            # via __cause__. Encaixar numa HTTPError genérica esconderia
            # que não temos diagnóstico.
            return HTTPError(
                f"Falha de transporte em {request.method} {request.route}: {type(exc).__name__}",
                failure_kind=None,
            )
        return HTTPError(
            f"Falha de transporte em {request.method} {request.route} "
            f"({kind.value}): {type(exc).__name__}: {exc}",
            failure_kind=kind.value,
        )

    @staticmethod
    def _build_user_agent(config: HTTPConfig) -> str:
        agent = _USER_AGENT_TEMPLATE.format(version=__version__)
        if config.user_agent_appendix:
            return f"{agent} {config.user_agent_appendix}".rstrip()
        return agent


def _body_of(request: Request) -> tuple[bytes | str | None, Any]:
    """Separa corpo em ``content`` (binário) e ``json`` (serializado).

    `GET` e `DELETE` não levam corpo, mesmo que tenha sido passado — o
    httpx enviaria, o Discord ignoraria, e o teste que deveria falhar não
    falharia.
    """
    if request.method in BODYLESS_METHODS:
        return None, None
    if request.json is not None:
        return None, request.json
    return request.body, None


def merge_headers(*parts: Mapping[str, str]) -> dict[str, str]:
    """Sobrescreve na ordem: o que vem depois ganha.

    Exposto para `rest.client` montar headers de request sem reimplementar
    a regra de precedência.
    """
    merged: dict[str, str] = {}
    for part in parts:
        merged.update(part)
    return merged
