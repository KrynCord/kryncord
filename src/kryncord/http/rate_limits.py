"""Interpretação dos headers de rate limit, e da resposta 429.

Contrato oficial (Discord API v10), lido de **toda** resposta — não só
do 429. É assim que a biblioteca descobre a cota de um bucket sem ter
que ser bloqueada primeiro:

===========================  ========  ===================================
Header                       Unidade   Significado
===========================  ========  ===================================
``X-RateLimit-Limit``        —         total de requisições na janela
``X-RateLimit-Remaining``    —         as que restam agora
``X-RateLimit-Reset-After``  segundos  quanto até a janela zerar
``X-RateLimit-Bucket``       —         identificador do bucket
``X-RateLimit-Scope``        —         ``user`` | ``shared`` | ``global``
``X-RateLimit-Global``       —         presente num 429 = limite global
``Retry-After``              segundos  quanto esperar (429)
===========================  ========  ===================================

Duas decisões aqui valem nota:

**Relógio monotônico.** Reset é comparado com ``time.monotonic()``, não
``time.time()``. Ajuste de relógio do sistema (NTP, mudança de fuso,
`date` na mão) não pode fazer o cliente disparar requisições cedo ou
esperar horas sem motivo.

**Corpo do 429 como fallback.** O discord.js lê só o header. Nós
preferimos o header mas caímos no campo ``retry_after`` do corpo — o
contrato oficial documenta os dois, e um proxy no meio do caminho pode
reescrever headers sem tocar no corpo.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kryncord.http.response import Response

#: Folga em milissegundos somada a todo reset. O Discord zera a janela em
#: um instante, e chegar exatamente nele é apertado demais.
DEFAULT_OFFSET_MS = 50

#: Janela do rate limit global client-side, em segundos. Espelha o
#: ``globalRequestsPerSecond``: uma janela de 1s com N requisições.
GLOBAL_WINDOW_SECONDS = 1.0

Clock = Callable[[], float]


def monotonic_clock() -> float:
    """Relógio padrão. Imune a ajuste de relógio do sistema."""
    return time.monotonic()


@dataclass(frozen=True, slots=True)
class RateLimitHeaders:
    """Instantâneo do rate limit lido de uma resposta.

    Pode vir quase todo vazio: endpoints de OAuth e alguns erros do proxy
    não mandam nada. `from_response` trata ausência como "sem informação"
    em vez de inventar zero — zero significaria "cota esgotada".
    """

    limit: int | None = None
    remaining: int | None = None
    reset_after: float | None = None
    bucket: str | None = None
    scope: str = "user"
    retry_after: float | None = None
    is_global: bool = False

    @classmethod
    def from_response(cls, response: Response) -> RateLimitHeaders:
        def number(name: str) -> float | None:
            raw = response.header(name)
            if raw is None:
                return None
            try:
                return float(raw)
            except ValueError:
                # Header malformado não pode derrubar a requisição. A cota
                # continua válida pelo resto da resposta.
                return None

        reset_after = number("x-ratelimit-reset-after")
        limit = number("x-ratelimit-limit")
        remaining = number("x-ratelimit-remaining")
        retry_after = number("retry-after")

        return cls(
            limit=int(limit) if limit is not None else None,
            remaining=int(remaining) if remaining is not None else None,
            reset_after=reset_after,
            bucket=response.header("x-ratelimit-bucket"),
            scope=response.header("x-ratelimit-scope") or "user",
            retry_after=retry_after,
            is_global=response.has_header("x-ratelimit-global"),
        )


@dataclass(slots=True)
class BucketState:
    """Estado corrente de um bucket, atualizado por cada resposta.

    Uma instância por ``bucket hash + major parameter`` — que é
    exatamente a granularidade que o Discord usa para contar.
    """

    limit: int = 0
    remaining: int = 1
    reset_at: float = 0.0
    """``reset_after`` aplicado ao relógio, em unidades de `clock`."""

    bucket_hash: str | None = None
    scope: str = "user"
    clock: Clock = field(default=monotonic_clock, repr=False)
    """Relógio monotônico. Injetável — sem isto, todo teste de rate limit
    dormiria de verdade ou dependeria do relógio da máquina."""

    @property
    def exhausted(self) -> bool:
        """Sem cota e ainda dentro da janela."""
        return self.remaining <= 0 and self.clock() < self.reset_at

    @property
    def seconds_until_reset(self) -> float:
        """Quanto falta para a janela zerar. Zero se já zerou."""
        return max(0.0, self.reset_at - self.clock())

    def update(self, headers: RateLimitHeaders) -> None:
        """Aplica o que uma resposta disse sobre este bucket.

        Só campos presentes são aplicados. Uma resposta sem headers não
        zera a cota — apagaria o estado de um bucket que estava bom.
        """
        if headers.limit is not None:
            self.limit = headers.limit
        if headers.remaining is not None:
            self.remaining = headers.remaining
        if headers.reset_after is not None:
            self.reset_at = self.clock() + headers.reset_after
        if headers.bucket is not None:
            self.bucket_hash = headers.bucket
        if headers.scope:
            self.scope = headers.scope

    def force_limit(self, seconds: float) -> None:
        """Trava o bucket por `seconds`, sem ter recebido header nenhum.

        É o caminho de um 429: o Discord diz "espera" e a biblioteca
        obedece mesmo sem os headers de cota virem junto.
        """
        self.remaining = 0
        self.reset_at = self.clock() + max(0.0, seconds)

    def snapshot(self) -> dict[str, Any]:
        """Estado legível, para log e para `RateLimitError`."""
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "seconds_until_reset": round(self.seconds_until_reset, 3),
            "bucket": self.bucket_hash,
            "scope": self.scope,
        }


@dataclass(slots=True)
class GlobalRateLimit:
    """Rate limit global: uma janela de 1s, compartilhada por todos os buckets.

    O discord.js mantém a contagem no objeto REST. Aqui é uma classe
    própria porque ela é o estado que **todos** os handlers consultam —
    juntá-la a qualquer um deles seria mentir sobre quem é dono.
    """

    requests_per_second: int = 50
    _remaining: int = 50
    reset_at: float = 0.0
    clock: Clock = field(default=monotonic_clock, repr=False)

    @property
    def remaining(self) -> int:
        """Cota disponível agora.

        Não é simplesmente o contador guardado: depois que a janela
        expira, a cota **voltou a existir**, mesmo que ninguém tenha
        chamado `consume()` ainda. Expor o contador cru mostraria ``0``
        enquanto há cota de sobra — log enganoso e condição de corrida
        para quem lê o valor.
        """
        if self.clock() >= self.reset_at:
            return self.requests_per_second
        return self._remaining

    @property
    def exhausted(self) -> bool:
        if self.clock() >= self.reset_at:
            return False
        return self._remaining <= 0

    @property
    def seconds_until_reset(self) -> float:
        return max(0.0, self.reset_at - self.clock())

    def consume(self) -> None:
        """Reserva uma vaga. Chamar **antes** de disparar a requisição."""
        now = self.clock()
        if now >= self.reset_at:
            self.reset_at = now + GLOBAL_WINDOW_SECONDS
            self._remaining = self.requests_per_second
        self._remaining -= 1

    def force_limit(self, seconds: float) -> None:
        """O Discord mandou ``X-RateLimit-Global`` num 429."""
        self._remaining = 0
        self.reset_at = self.clock() + max(0.0, seconds)


def normalize_offset(offset_ms: float) -> float:
    """Offset nunca pode ser negativo — um offset negativo adiantaria o reset."""
    return max(0.0, offset_ms) / 1000


def parse_429(response: Response) -> tuple[float, bool]:
    """Extrai ``(retry_after, is_global)`` de uma resposta 429.

    Ordem de preferência: header ``Retry-After``, depois o ``retry_after``
    do corpo. Ambos em segundos — a v6 do Discord mandava milissegundos no
    corpo, e interpretar segundos como ms faria o cliente dormir 1000x mais.
    """
    headers = RateLimitHeaders.from_response(response)
    retry_after = headers.retry_after
    is_global = headers.is_global

    if retry_after is None:
        body_retry, body_global = _retry_after_from_body(response)
        retry_after = body_retry
        is_global = is_global or body_global

    # Sem sinal algum: espera curta em vez de disparar em loop. Um 429 sem
    # tempo é anomalia — reaproveitar a janela do bucket é a saída menos pior.
    if retry_after is None:
        retry_after = 1.0

    return retry_after, is_global


def _retry_after_from_body(response: Response) -> tuple[float | None, bool]:
    """Tenta ler o corpo, com ou sem ``Content-Type``.

    Não checamos `is_json`: um proxy pode entregar JSON válido com
    content-type errado (ou nenhum), e o corpo é o contrato documentado
    da API. Se não for JSON, `response.json()` levanta e caímos fora —
    o chamador usa o default.
    """
    if not response.body:
        return None, False
    try:
        data = response.json()
    except Exception:  # corpo de 429 malformado não pode mascarar o 429
        return None, False
    if not isinstance(data, dict):
        return None, False

    raw = data.get("retry_after")
    if isinstance(raw, bool):  # bool é subclasse de int em Python
        return None, bool(data.get("global", False))
    if isinstance(raw, (int, float)):
        return float(raw), bool(data.get("global", False))
    return None, bool(data.get("global", False))
