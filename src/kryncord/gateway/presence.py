"""Presence em runtime (op 3) — o `client.presence.set()` do discord.js.

O op 3 muda status, atividades e flag `afk` da sessão inteira, sem
reconectar. A presença **inicial** vai no `IDENTIFY` (`initialPresence`,
já coberto por `gateway/identify.py`); isto aqui é o que muda depois
que o bot já está pronto — `client.update_presence()`.

Duas diferenças deliberadas do discord.js, ambas justificadas no doc
05 das divergências:

* **Teto client-side de 5 updates por 20 segundos** — o discord.js não
  tem nenhum (`ClientPresence.js` manda direto). O teto é do Discord,
  e o sintoma de ignorá-lo é o update sumindo sem aviso; regra §13
  proíbe drop silencioso, então quem manda demais **paga a espera**, na
  cara, com um número no log em vez de um bot que jura que mandou.
* **Recusa fora de sessão** (`LifecycleError`) — o discord.js enfileira
  mudanças pré-READY e manda no `RESUMED`. Aqui a recusa é na cara:
  enfileiro oculto é estado que mente sobre o que já foi entregue, e
  presença é o campo menos urgente de um bot — quem precisa dela antes
  do READY pode pôr no `identify` e evitar a surpresa.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from kryncord.enums import GatewayOpcode
from kryncord.gateway.payloads import Payload
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep

#: Updates de presença por janela — o teto documentado do Discord.
PRESENCE_LIMIT = 5

#: Janela do teto, em segundos.
PRESENCE_WINDOW = 20.0

#: Folga sorteada quando a janela estoura. Menor que a do envio de
#: frames (1.5s) porque a janela também é menor: espera pequena, folga
#: pequena.
PRESENCE_JITTER = 0.5

#: Status que o Discord aceita no op 3, na ordem dos docs.
VALID_STATUSES: tuple[str, ...] = ("online", "dnd", "idle", "invisible", "offline")


@dataclass(slots=True)
class PresenceRateLimit:
    """Teto de 5 updates por 20 segundos — o teto documentado do op 3.

    Mesmo desenho do `GatewaySendRateLimit`: janela rolante, espera com
    jitter, `clock`/`sleeper` injetáveis para o teste não dormir. Diferente
    dele, não existe `important`: todo update de presença conta, o
    primeiro inclusive.

    Por que existe, se o discord.js não tem um: ver o docstring do
    módulo. Resumindo, é a regra §13 — o teto é do Discord, e a única
    alternativa ao wait honesto é o drop silencioso.
    """

    limit: int = PRESENCE_LIMIT
    window: float = PRESENCE_WINDOW
    jitter: float = PRESENCE_JITTER
    clock: Clock = field(default=monotonic_clock, repr=False)
    sleeper: Sleeper = field(default=real_sleep, repr=False)
    random: Callable[[], float] = field(default=random.random, repr=False)

    _reset_at: float = field(default=0.0, init=False, repr=False)
    _sent: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError(f"limit precisa ser ao menos 1, recebido {self.limit}")
        if self.window <= 0:
            raise ValueError(f"window precisa ser positiva, recebido {self.window}")
        if self.jitter < 0:
            raise ValueError(f"jitter não pode ser negativo, recebido {self.jitter}")
        self._reset_at = self.clock() + self.window

    async def acquire(self) -> None:
        """Bloqueia até caber mais um update na janela.

        Ao contrário do teto de frames, a quinta chamada **passa** — o
        Discord documenta "5 updates per 20 seconds", então cinco são
        livres e a sexta é que espera.
        """
        while True:
            now = self.clock()
            if now >= self._reset_at:
                self._reset_at = now + self.window
                self._sent = 0

            if self._sent + 1 <= self.limit:
                break

            wait = self._reset_at - now + self.random() * self.jitter
            await self.sleeper(wait)

        self._sent += 1


def build_presence_update(
    *,
    since: int | None = None,
    afk: bool = False,
    status: str = "online",
    activities: Sequence[Mapping[str, Any]] = (),
) -> Payload:
    """Monta o op 3 pronto para o socket, validando na cara.

    `status` fora da lista do Discord é `ValueError` **listando as
    opções**: o frame errado ali não vira evento errado, vira close
    code — e recusar aqui custa uma exceção, não uma reconexão.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"status {status!r} não existe; opções do Discord: {', '.join(VALID_STATUSES)}."
        )
    if since is not None and (isinstance(since, bool) or not isinstance(since, int)):
        raise ValueError(f"since precisa ser inteiro de milissegundos ou None, veio {since!r}.")
    if not isinstance(afk, bool):
        raise ValueError(f"afk precisa ser bool, veio {afk!r}.")

    body: dict[str, Any] = {
        "since": since,
        "activities": [dict(atividade) for atividade in activities],
        "status": status,
        "afk": afk,
    }
    return Payload(op=GatewayOpcode.PRESENCE_UPDATE, data=body)
