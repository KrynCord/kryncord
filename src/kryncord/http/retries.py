"""Política de repetição de requisições.

A regra que este módulo existe para obedecer: **não repetir cegamente
operações que criam estado**. Um ``POST /channels/:id/messages`` que deu
timeout pode ter sido processado — repetir manda a mensagem duas vezes,
e o Discord não tem idempotency key para desfazer.

Para decidir, é preciso saber duas coisas separadas: o que aconteceu
(nossa classificação) e o que a requisição fazia (a do `Request`).

=========================  =============================================
`FailureKind`               Significado
=========================  =============================================
``not_sent``                A conexão nunca se estabeleceu. Nada chegou.
``ambiguous``               Enviado, resposta não veio. Pode ter sido.
``server_error``            5xx. O servidor errou — geralmente não
                            processou, mas não é garantia.
``client_error``            4xx. Erro nosso, repetir só repete o erro.
``rate_limited``            429. Tratado pelo rate limiter, não aqui.
=========================  =============================================

A matriz de decisão:

======================  ==========  ============  ===========
                        ``not_sent`` ``ambiguous`` 5xx
======================  ==========  ============  ===========
GET/PUT/DELETE/PATCH     repete      repete        repete
POST                     repete      **não**       **não**
======================  ==========  ============  ===========

``POST`` é o único que cria entidades novas. `PATCH` entra no grupo
seguro porque o Discord usa PATCH para *definir* estado (nome, tópico,
permissões) — aplicar duas vezes produz o mesmo resultado.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

import httpx

from kryncord.http.request import Request


class FailureKind(StrEnum):
    """O que sabemos sobre uma falha, antes de olhar para a requisição."""

    NOT_SENT = "not_sent"
    AMBIGUOUS = "ambiguous"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    RATE_LIMITED = "rate_limited"


#: Métodos cuja repetição não cria entidade nova.
#: `POST` fica de fora de propósito: é o único que cria.
_REPEATABLE = frozenset({"GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Quando e quanto esperar antes de tentar de novo."""

    max_retries: int = 3
    backoff_base: float = 0.0
    """Segundos de espera na primeira repetição. ``0`` = imediata."""

    backoff_factor: float = 2.0
    backoff_max: float = 30.0
    jitter: float = 0.1
    """Fração de aleatoriedade (0 a 1). Sem jitter, clientes que falharam
    juntos voltam juntos e causam outra onda no mesmo instante."""

    def should_retry(self, request: Request, kind: FailureKind, retries_done: int) -> bool:
        """`retries_done` é quantas repetições já houve (0 na primeira falha)."""
        if retries_done >= self.max_retries:
            return False

        if kind is FailureKind.CLIENT_ERROR:
            return False
        if kind is FailureKind.RATE_LIMITED:
            # Nunca aqui. Repetir cedo demais ignora a espera que o
            # Discord pediu e piora o bloqueio.
            return False

        if kind is FailureKind.NOT_SENT:
            return True

        # ambiguous ou server_error: só se repetir for inofensivo.
        return request.method.value in _REPEATABLE

    def backoff(self, retries_done: int) -> float:
        """Espera em segundos antes da próxima tentativa.

        Exponencial com teto e jitter — o teto evita que um servidor
        caído segure o cliente por minutos, e o jitter espalha clientes
        que falharam no mesmo instante.
        """
        if self.backoff_base <= 0:
            return 0.0
        raw = self.backoff_base * (self.backoff_factor**retries_done)
        capped = min(raw, self.backoff_max)
        if self.jitter <= 0:
            return capped
        spread = capped * self.jitter
        return max(0.0, capped + random.uniform(-spread, spread))

    @classmethod
    def none(cls) -> RetryPolicy:
        """Desliga repetição. Para teste e para quem quer falhar rápido."""
        return cls(max_retries=0)


def classify_transport_error(exc: BaseException) -> FailureKind | None:
    """Classifica uma exceção de transporte, ou devolve ``None`` se irrelevante.

    A pergunta é: **a requisição chegou ao servidor?** Se não chegou,
    repetir é sempre seguro, qualquer que seja o método.

    ``None`` significa "não é falha de transporte" — o chamador deixa a
    exceção propagar, porque tentar de novo não vai ajudar.
    """
    # Ordem importa: `ConnectTimeout` é subclasse de `TimeoutException`,
    # e `ConnectError` é subclasse de `NetworkError`. O teste mais
    # específico tem que vir primeiro, senão a resposta sai errada.
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return FailureKind.NOT_SENT

    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return FailureKind.AMBIGUOUS

    if isinstance(exc, httpx.NetworkError):
        # Read/Write/Close: a conexão existiu, então não sabemos se o
        # servidor processou.
        return FailureKind.AMBIGUOUS

    if isinstance(exc, (httpx.TimeoutException, httpx.ProtocolError)):
        # ProtocolError = o servidor fechou no meio da troca. A requisição
        # já tinha saído, então é ambígua.
        return FailureKind.AMBIGUOUS

    if isinstance(exc, httpx.RequestError):
        # Qualquer outra falha de transporte que não enumeramos. Sabemos
        # que a resposta não chegou; não sabemos se o pedido foi
        # processado — ambíguo é o honesto, e o custo é só uma tentativa
        # extra em operação idempotente.
        return FailureKind.AMBIGUOUS

    return None
