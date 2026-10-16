"""Modelo interno de requisição HTTP.

O `Request` é um **valor**, não um builder com estado. Constrói-se um
completo e entrega ao `http.client`. Isso mantém a fila de rate limit
simples: o que está aguardando numa bucket é um objeto imutável, então
retries podem reusá-lo sem cópia defensiva.

`json` e `body` são mutuamente exclusivos — `json` vira `Content-Type:
application/json`, `body` (bytes) já vem com o content-type de quem
construiu, que é o caso dos uploads multipart.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode


class HTTPMethod(StrEnum):
    """Métodos HTTP que a API do Discord aceita.

    `StrEnum` de propósito: o valor já é a string enviada, então
    `str(HTTPMethod.POST) == "POST"` sem conversão.
    """

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


#: Métodos que não levam corpo. O Discord ignora, mas enviar é desperdício
#: e mascara bugs.
BODYLESS_METHODS = frozenset({HTTPMethod.GET, HTTPMethod.DELETE})


@dataclass(frozen=True, slots=True)
class Request:
    """Uma requisição pronta para entrar na fila de um bucket."""

    method: HTTPMethod
    route: str
    """Caminho começando com ``/``. Ex.: ``/channels/123/messages``."""

    query: Mapping[str, Any] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    json: Any = None
    """Corpo JSON. Se definido, `body` deve ser `None`."""

    body: bytes | None = None
    """Corpo binário já serializado (multipart ou stream)."""

    auth: bool = True
    """``False`` envia sem o header ``Authorization``."""

    reason: str | None = None
    """Vira ``X-Audit-Log-Reason``, para o audit log do servidor."""

    versioned: bool = True
    """``False`` omite o ``/v10`` da URL — usado só em endpoints de OAuth."""

    def __post_init__(self) -> None:
        if self.json is not None and self.body is not None:
            raise ValueError(
                f"{self.method} {self.route}: `json` e `body` são mutuamente exclusivos — "
                "defina um ou outro, nunca os dois"
            )
        if not self.route.startswith("/"):
            raise ValueError(
                f"route precisa começar com '/': {self.route!r}. "
                "Um route sem barra produziria uma URL como https://discord.com/api/v10canais..."
            )

    @property
    def has_body(self) -> bool:
        return self.json is not None or self.body is not None

    @property
    def is_idempotent(self) -> bool:
        """GET e DELETE são idempotentes: repetir não cria efeito novo.

        Os demais **criam estado**. Repetir um POST de mensagem enviaria
        duas vezes — é por isso que `retries.py` pergunta isto antes de
        tentar de novo.
        """
        return self.method in {HTTPMethod.GET, HTTPMethod.DELETE}

    @property
    def path_with_query(self) -> str:
        """Rota + query, formatada. ``?`` só se houver parâmetro."""
        if not self.query:
            return self.route
        return f"{self.route}?{urlencode(self.query)}"
