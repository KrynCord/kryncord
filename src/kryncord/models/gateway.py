"""O que o `GET /gateway/bot` devolve — shards e o teto de identifies.

Payload pequeno, consequência grande: é daqui que sai **quantas shards**
o bot tem e **quanto cabe ainda** de identify (`session_start_limit`).
O limite envelhece a cada identify, então quem usa para decidir o
sharding busca na hora de conectar — não no boot.

`from_payload` segue o contrato de `models/`: devolve `None` quando o
corpo não forma o modelo, e o `expect_model` da rota REST vira isso em
`HTTPError` com a rota na mensagem.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionStartLimit:
    """Quanto cabe de identify hoje, e quando a conta recarrega."""

    total: int
    """Identifies que a conta tem numa janela (1000 para a maioria)."""

    remaining: int
    """Quantos ainda cabem agora. Conectar `n` shards consome `n`."""

    reset_after: float
    """Segundos até a conta recarregar — o número que a mensagem de
    erro precisa mostrar, porque "espera X segundos" é o que resolve."""

    max_concurrency: int
    """Identifies simultâneos por bucket. Alimenta o throttler: o bucket
    da shard `i` é `i % max_concurrency`."""

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> SessionStartLimit | None:
        total = data.get("total")
        remaining = data.get("remaining")
        reset_after = data.get("reset_after")
        max_concurrency = data.get("max_concurrency")
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or isinstance(remaining, bool)
            or not isinstance(remaining, int)
            or isinstance(reset_after, bool)
            or not isinstance(reset_after, (int, float))
            or isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
        ):
            return None
        return cls(
            total=total,
            remaining=remaining,
            reset_after=float(reset_after),
            max_concurrency=max_concurrency,
        )


@dataclass(frozen=True, slots=True)
class GatewayBotInfo:
    """`GET /gateway/bot` — a URL do Gateway e a topologia sugerida."""

    url: str
    shards: int
    """Total de shards que o Discord sugere para este bot."""

    session_start_limit: SessionStartLimit

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> GatewayBotInfo | None:
        url = data.get("url")
        shards = data.get("shards")
        limite = data.get("session_start_limit")
        if (
            not isinstance(url, str)
            or isinstance(shards, bool)
            or not isinstance(shards, int)
            or not isinstance(limite, Mapping)
        ):
            return None
        limit_parsed = SessionStartLimit.from_payload(limite)
        if limit_parsed is None:
            return None
        return cls(url=url, shards=shards, session_start_limit=limit_parsed)
