"""Normalização de resposta HTTP.

O `httpx` devolve `httpx.Response`, mas a camada de rate limit e a de
interpretação de erro não devem depender de uma biblioteca específica —
nem em teste. Este módulo dá uma forma própria e estável.

Os headers são guardados em minúsculas porque é assim que o RFC 9110
define comparação de campo, e porque o `httpx` às vezes preserva o caso
original. `X-RateLimit-Bucket` e `x-ratelimit-bucket` são o mesmo campo.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from kryncord.errors import HTTPError


@dataclass(frozen=True, slots=True)
class Response:
    """Resposta HTTP em forma normalizada."""

    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    """Chaves em minúsculas, já normalizadas."""

    url: str = ""
    """URL final, útil para a mensagem de erro (o Discord redireciona)."""

    @property
    def ok(self) -> bool:
        """2xx. O Discord usa 200, 201, 204 e 202 (ack assíncrono)."""
        return 200 <= self.status < 300

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def is_json(self) -> bool:
        """O Discord manda ``application/json``; alguns 204 vêm vazios."""
        return self.content_type.split(";")[0].strip().lower() == "application/json"

    @property
    def text(self) -> str:
        """Corpo decodificado, com fallback para substituição.

        Discord devolve UTF-8, mas um proxy de erro pode devolver
        iso-8859-1 — não estourar com UnicodeDecodeError num erro de 502
        vale mais que a pureza.
        """
        return self.body.decode("utf-8", errors="replace")

    def header(self, name: str) -> str | None:
        """Lê um header sem se preocupar com o caso."""
        return self.headers.get(name.lower())

    def has_header(self, name: str) -> bool:
        return name.lower() in self.headers

    def json(self) -> Any:
        """Decodifica o corpo como JSON.

        Levanta `HTTPError` em vez de `json.JSONDecodeError` — o chamador
        trata falha HTTP, não falha de parser, e o `JSONDecodeError` seria
        uma exceção que ninguém captura.
        """
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPError(
                f"Corpo da resposta não é JSON válido (status {self.status}): {exc}. "
                f"Início do corpo: {self.text[:200]!r}",
                status=self.status,
            ) from exc

    @classmethod
    def of(
        cls,
        status: int,
        headers: Mapping[str, str] | list[tuple[str, str]],
        body: bytes,
        url: str = "",
    ) -> Response:
        """Constrói normalizando as chaves de header para minúsculas.

        Aceita lista de pares (formato do `httpx`) ou dict — assim os
        testes podem montar uma resposta literal sem depender do transporte.
        """
        items: Iterable[tuple[str, str]] = (
            headers.items() if isinstance(headers, Mapping) else headers
        )
        return cls(
            status=status,
            body=body,
            headers={key.lower(): value for key, value in items},
            url=url,
        )
