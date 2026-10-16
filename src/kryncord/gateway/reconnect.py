"""Classificação de fechamentos e política de reconexão.

A pergunta que este módulo responde é a única que decide se um bot que
caiu volta **igual** ou volta **de novo do zero**:

* **RESUME** — a sessão ainda vale. Reabre, manda ``session_id`` +
  ``sequence`` e o Discord reenvia o que perdemos. Nenhum evento cai.
* **IDENTIFY** — a sessão morreu. Reabre e faz ``identify`` novo.
  Tudo que aconteceu durante a queda é perdido, e o ``READY`` chega de
  novo com o cache inteiro.
* **FATAL** — nem adianta tentar: token inválido, intents errados,
  shard inválida. Tentar de novo é só queimar rate limit do Gateway.

A tabela abaixo foi extraída do ``WebSocketShard.onClose`` do
discord.js. Não é chute: cada linha corresponde a um ``case`` de lá.

+------+--------------------------+-----------------------------+
| 4000 | erro desconhecido        | RESUME                      |
| 4001 | opcode desconhecido      | RESUME                      |
| 4002 | decode error             | RESUME                      |
| 4003 | não autenticado          | IDENTIFY                    |
| 4004 | autenticação falhou      | **FATAL**                   |
| 4005 | já autenticado           | IDENTIFY                    |
| 4007 | sequence inválida        | IDENTIFY                    |
| 4008 | rate limited             | IDENTIFY                    |
| 4009 | sessão expirou           | RESUME                      |
| 4010 | shard inválida           | **FATAL**                   |
| 4011 | sharding obrigatório     | **FATAL**                   |
| 4012 | API version inválida     | **FATAL**                   |
| 4013 | intents inválidos        | **FATAL**                   |
| 4014 | intents não permitidos   | **FATAL**                   |
| 1000 | fechamento normal        | IDENTIFY                    |
| 4200 | "estou retomando"        | RESUME                      |
|  inx. | inesperado               | RESUME, salvo erro de rede |
+------+--------------------------+-----------------------------+

Dois casos merecem explicação porque parecem errados:

**1000 vira IDENTIFY.** Fechamento normal significa que o Discord
encerrou a sessão de propósito. A sessão acabou — tentar ``RESUME`` com
ela devolve ``invalid_session`` e a gente paga um round-trip para
descobrir o que já sabia.

**4008 (rate limited) vira IDENTIFY.** Parece que deveria ser RESUME
(houve rate limit, não erro de sessão), mas é o discord.js que decide
IDENTIFY aqui, e ele está em produção há anos. O custo de errar é
perder eventos; o custo de acertar de mais é um ``READY`` extra.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from kryncord.enums import CloseCode

# Códigos 4xxx que encerram a conexão para sempre. Não existe "tentar de
# novo" — o próximo identify falha igual.
_FATAL_CODES = frozenset(
    {
        CloseCode.AUTHENTICATION_FAILED,  # 4004 token errado
        CloseCode.INVALID_SHARD,  # 4010
        CloseCode.SHARDING_REQUIRED,  # 4011
        CloseCode.INVALID_API_VERSION,  # 4012
        CloseCode.INVALID_INTENTS,  # 4013
        CloseCode.DISALLOWED_INTENTS,  # 4014
    }
)

# A sessão morreu; precisa de identify novo.
_IDENTIFY_CODES = frozenset(
    {
        1000,  # fechamento normal — sessão encerrada de propósito
        CloseCode.NOT_AUTHENTICATED,  # 4003
        CloseCode.ALREADY_AUTHENTICATED,  # 4005
        CloseCode.INVALID_SEQ,  # 4007 — sequence que nós mandamos era velha
        CloseCode.RATE_LIMITED,  # 4008
    }
)

# A sessão ainda vale; retomar evita perder eventos.
_RESUME_CODES = frozenset(
    {
        4200,  # "resuming" — código que o próprio discord.js emite
        CloseCode.UNKNOWN_ERROR,  # 4000
        CloseCode.UNKNOWN_OPCODE,  # 4001
        CloseCode.DECODE_ERROR,  # 4002
        CloseCode.SESSION_TIMEOUT,  # 4009
    }
)

#: Código que o discord.js envia ao fechar de propósito para retomar.
RESUMING_CODE = 4200


class Recovery(StrEnum):
    """O que fazer depois que a conexão caiu."""

    RESUME = "resume"
    """Reabrir e retomar a sessão — nenhum evento é perdido."""

    IDENTIFY = "identify"
    """Reabrir com ``identify`` novo — o cache é reconstruído."""

    FATAL = "fatal"
    """Não reconectar. Levantar `FatalGatewayError`."""

    @property
    def will_resume(self) -> bool:
        return self is Recovery.RESUME


@dataclass(frozen=True, slots=True)
class CloseDecision:
    """O resultado de `classify_close`, com o motivo para log."""

    recovery: Recovery
    code: int | None
    reason: str


def classify_close(
    code: int | None,
    *,
    network_error: bool = False,
) -> CloseDecision:
    """Decide se um fechamento pede resume, identify ou desistência.

    `code` é o código WebSocket de fechamento. `None` (ou 1000) é o
    fechamento normal — sessão encerrada, portanto ``identify``.

    `network_error` só importa para códigos **inesperados**: um close
    code que não está em nenhuma das tabelas. Sem erro de rede, um
    fechamento estranho mantém a sessão (``resume``); com erro de rede,
    a sessão provavelmente estourou no caminho, e um ``identify`` novo é
    mais barato do que um ``resume`` que vai ser rejeitado.

    Nenhum código é FATAL por engano: FATAL é sempre explícito, porque
    o custo de uma falsa positiva é um bot que desiste de viver.
    """
    if code is None or code == 1000:
        return CloseDecision(
            recovery=Recovery.IDENTIFY,
            code=code,
            reason="fechamento normal — a sessão foi encerrada pelo Discord",
        )

    if code in _FATAL_CODES:
        return CloseDecision(
            recovery=Recovery.FATAL,
            code=code,
            reason=f"{code} não é recuperável: corriga a configuração e reinicie",
        )

    if code in _IDENTIFY_CODES:
        return CloseDecision(
            recovery=Recovery.IDENTIFY,
            code=code,
            reason=f"{code} invalidou a sessão — identify novo",
        )

    if code in _RESUME_CODES:
        return CloseDecision(
            recovery=Recovery.RESUME,
            code=code,
            reason=f"{code} é transitório — retomar sessão",
        )

    # Fora de tabela. É aqui que `network_error` decide.
    recovery = Recovery.IDENTIFY if network_error else Recovery.RESUME
    detail = (
        "houve erro de rede antes do fechamento, a sessão não é confiável"
        if network_error
        else "código fora de tabela, tentando retomar a sessão"
    )
    return CloseDecision(recovery=recovery, code=code, reason=f"{code} inesperado: {detail}")


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Backoff exponencial com jitter, e o limite de tentativas.

    ``max_attempts`` conta falhas **consecutivas**: chegar ao ``READY``
    zera o contador. Um bot que vive seis horas e cai tem todas as
    tentativas de volta — o limite existe para não girar sozinho
    indefinidamente quando o token está errado, não para punir um bot
    que já funcionou.

    * ``None`` — tenta para sempre. É o que se quer quando o objetivo é
      "manter o bot ligado": uma manutenção do Discord não pode matar o
      processo.
    * ``0`` — nunca reconecta (a feature está desligada).
    * ``n > 0`` — no máximo ``n`` tentativas seguidas.

    O backoff é ``equal jitter``: metade do delay é fixa e metade é
    aleatória. Delay totalmente fixo faz N shards caídos ao mesmo tempo
    baterem no Gateway no mesmo milissegundo; delay totalmente aleatório
    pode devolver 0 e não protege nada.
    """

    max_attempts: int | None = 5
    base_delay: float = 0.5
    max_delay: float = 60.0
    jitter: float = 0.5
    """Fração do delay que é sorteada. ``0`` desliga o jitter (útil em
    teste); ``0.5`` é o default."""
    random: Callable[[], float] = random.random
    """Fonte de aleatoriedade, injetável para o teste sair determinístico."""

    def __post_init__(self) -> None:
        if self.base_delay <= 0:
            raise ValueError(f"base_delay precisa ser positivo, recebido {self.base_delay}")
        if self.max_delay < self.base_delay:
            raise ValueError(
                f"max_delay ({self.max_delay}) não pode ser menor que "
                f"base_delay ({self.base_delay})"
            )
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError(f"jitter deve estar entre 0 e 1, recebido {self.jitter}")
        if self.max_attempts is not None and self.max_attempts < 0:
            raise ValueError(f"max_attempts não pode ser negativo, recebido {self.max_attempts}")

    def should_retry(self, attempt: int) -> bool:
        """`attempt` é a tentativa que **está** para ser feita (1-indexed)."""
        if self.max_attempts is None:
            return True
        return attempt <= self.max_attempts

    def delay(self, attempt: int) -> float:
        """Espera antes da tentativa `attempt` (1-indexed).

        ``attempt=1`` devolve a menor espera. O exponencial dobra a cada
        falha, cortado em ``max_delay`` — depois disso o jitter ainda
        mexe, mas dentro do teto.
        """
        if attempt < 1:
            raise ValueError(f"attempt é 1-indexed, recebido {attempt}")

        exponential = self.base_delay * (2.0 ** (attempt - 1))
        capped = min(exponential, self.max_delay)

        if self.jitter <= 0.0:
            return capped

        # equal jitter: garante metade da espera, sorteia a outra metade
        half = capped * (1.0 - self.jitter)
        span = capped - half
        return half + self.random() * span
