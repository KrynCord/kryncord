"""Identify: o payload que registra o bot, e o teto de sessões.

Dois assuntos que parecem separados e não são — os dois respondem a
"como apresentar este bot ao Discord sem ser derrubado".

**O payload.** Mandado uma vez por conexão, depois do ``HELLO``. Erros
aqui são fatais e não se recuperam reconectando: intents errados dão
``4013``, intent privilegiado sem permissão no portal dá ``4014``, e os
dois encerram a conexão para sempre. Por isso a validação é local e
barulhenta: vale falhar no `build_identify`, com mensagem dizendo o que
corrigir, do que descobrir no close code 4014 depois de ligar.

**O teto.** O Discord aceita **um identify a cada 5 segundos por bucket
de concorrência**, e o bucket é ``shard_id % max_concurrency``. Para um
bot de uma shard isso é quase invisível; para um que reconstroi sessão
em loop (queda de rede, por exemplo) é a diferença entre voltar em 5
segundos e ser bloqueado.

O cálculo do ``wait`` é o do ``SimpleIdentifyThrottler`` do discord.js:
descobre quanto falta para a janela virar, dorme isso **mais um pouco
de sorte**. A folga existe porque o identify leva um tempo atravessando
a rede — se mandarmos exatamente no instante do reset, o Discord já
contou o anterior e conta este como o primeiro da janela seguinte. Errar
para o lado da espera custa 1,5 s; errar para o lado do envio custa um
round-trip que termina em ``4008``.

O ``asyncio.Lock`` por bucket não é burocracia: sem ele, duas shards
que chamam ``wait()`` ao mesmo tempo leem a mesma janela ainda vazia,
nenhuma dorme, e as duas identificam juntas.
"""

from __future__ import annotations

import asyncio
import platform
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from kryncord.enums import GatewayOpcode
from kryncord.gateway.payloads import Payload
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep

#: Intervalo entre dois identifies no mesmo bucket, em segundos.
IDENTIFY_INTERVAL = 5.0
#: Folga sorteada somada à espera, em segundos. Discord.js usa 1500 ms.
IDENTIFY_JITTER = 1.5

#: Faixa que o Discord aceita para `large_threshold`.
MIN_LARGE_THRESHOLD = 50
MAX_LARGE_THRESHOLD = 256


@dataclass(frozen=True, slots=True)
class IdentifyProperties:
    """Os ``properties`` do Identify.

    O Discord usa isto para mostrar "KrynCord em Linux" no painel de
    sessões. Não é decorativo: campos ausentes mudam como o Discord
    trata a sessão. Os três nomes — ``os``, ``browser``, ``device`` —
    são os que a API reconhece; inventar outros é ignorado em silêncio.
    """

    os: str = field(default_factory=lambda: platform.system().lower() or "unknown")
    browser: str = "kryncord"
    device: str = "kryncord"

    def to_dict(self) -> dict[str, str]:
        return {"os": self.os, "browser": self.browser, "device": self.device}


def default_properties() -> IdentifyProperties:
    """Identidades padrão, resolvidas no momento da chamada.

    Função, e não constante, porque o ``os`` só é conhecido em runtime
    e porque um módulo que captura ``platform.system()`` no import fica
    com o valor errado se o processo for migrado.
    """
    return IdentifyProperties()


def build_identify(
    *,
    token: str,
    intents: int,
    properties: IdentifyProperties | Mapping[str, str] | None = None,
    large_threshold: int | None = None,
    shard: tuple[int, int] | None = None,
    presence: Mapping[str, Any] | None = None,
    compress: bool = False,
) -> Payload:
    """Monta o ``IDENTIFY``. Levanta `ValueError` no que é nosso.

    Argumento inválido é `ValueError`, igual a `config.py` — e não
    `DefinitionError`, cujo contrato é "detectado na importação". Aqui
    estamos em `start()`.

    Só erros do **código do usuário** viram exceção aqui — token vazio,
    intent negativo, threshold fora de faixa. O que o Discord pode
    rejeitar (intent privilegiado sem permissão) passa e só aparece no
    close code, porque nós não temos como saber: o portal é dele.
    """
    if not token or not token.strip():
        raise ValueError("Identify com token vazio — o Client precisa de um token de bot válido.")
    if isinstance(intents, bool) or not isinstance(intents, int) or intents < 0:
        raise ValueError(
            f"Identify com intents inválido: {intents!r}. "
            "Esperado inteiro não-negativo, construído com `Intents`."
        )
    if large_threshold is not None and not (
        MIN_LARGE_THRESHOLD <= large_threshold <= MAX_LARGE_THRESHOLD
    ):
        raise ValueError(
            f"large_threshold deve estar entre {MIN_LARGE_THRESHOLD} e "
            f"{MAX_LARGE_THRESHOLD}, recebido {large_threshold}. "
            "O Discord descarta o identify fora dessa faixa."
        )
    if shard is not None:
        shard_id, shard_count = shard
        if shard_count < 1:
            raise ValueError(f"shard_count precisa ser ao menos 1, recebido {shard_count}.")
        if not 0 <= shard_id < shard_count:
            raise ValueError(f"shard_id {shard_id} fora do intervalo [0, {shard_count}).")

    if properties is None:
        resolved = default_properties().to_dict()
    elif isinstance(properties, IdentifyProperties):
        resolved = properties.to_dict()
    else:
        resolved = dict(properties)

    body: dict[str, Any] = {
        "token": token,
        "intents": intents,
        "properties": resolved,
        "compress": compress,
    }
    if large_threshold is not None:
        body["large_threshold"] = large_threshold
    if shard is not None:
        body["shard"] = list(shard)
    if presence is not None:
        body["presence"] = dict(presence)

    return Payload(op=GatewayOpcode.IDENTIFY, data=body)


def build_resume(*, token: str, session_id: str, sequence: int) -> Payload:
    """Monta o ``RESUME`` — o que faz a queda sair de graça.

    Diferença prática em relação ao ``IDENTIFY``: quem manda isto **não**
    recebe ``READY`` de novo, recebe ``RESUMED``, e o Discord reenvia os
    eventos que perdemos a partir de ``sequence``. Nenhum evento cai.
    """
    if not session_id:
        raise ValueError("Resume com session_id vazio — sem sessão guardada, use identify.")
    if sequence < 0:
        raise ValueError(f"Resume com sequence negativa: {sequence}.")

    return Payload(
        op=GatewayOpcode.RESUME,
        data={"token": token, "session_id": session_id, "seq": sequence},
    )


@dataclass(slots=True)
class IdentifyThrottler:
    """Garante um ``IDENTIFY`` a cada `interval` por bucket de sessão.

    O bucket é ``shard_id % max_concurrency`` — a mesma divisão que o
    Discord usa. `max_concurrency` vem de ``/gateway/bot``
    (``session_start_limit.max_concurrency``); para a quase totalidade
    dos bots é ``1``, e aí todo identify da aplicação divide o mesmo
    teto.

    `None` em `max_concurrency` significa "ainda não sabemos", e é
    tratado como ``1``: errar para o lado da espera atrasa o boot em 5
    segundos, errar para o lado do envio derruba a conexão.
    """

    max_concurrency: int = 1
    interval: float = IDENTIFY_INTERVAL
    jitter: float = IDENTIFY_JITTER
    clock: Clock = field(default=monotonic_clock, repr=False)
    sleeper: Sleeper = field(default=real_sleep, repr=False)
    random: Callable[[], float] = field(default=random.random, repr=False)

    _resets_at: dict[int, float] = field(default_factory=dict, init=False, repr=False)
    _locks: dict[int, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError(
                f"max_concurrency precisa ser ao menos 1, recebido {self.max_concurrency}"
            )
        if self.interval <= 0:
            raise ValueError(f"interval precisa ser positivo, recebido {self.interval}")
        if self.jitter < 0:
            raise ValueError(f"jitter não pode ser negativo, recebido {self.jitter}")

    def bucket_for(self, shard_id: int) -> int:
        """O bucket desta shard — a mesma fórmula do Discord."""
        return shard_id % self.max_concurrency

    def seconds_until_next(self, shard_id: int) -> float:
        """Quanto falta para poder mandar identify. Zero se já pode."""
        resets_at = self._resets_at.get(self.bucket_for(shard_id))
        if resets_at is None:
            return 0.0
        return max(0.0, resets_at - self.clock())

    async def wait(self, shard_id: int) -> None:
        """Bloqueia até o identify desta shard ser permitido.

        O ``asyncio.Lock`` serializa as chamadas do mesmo bucket. Sem
        ele, duas shards lendo a janela vazia ao mesmo tempo não dormem
        nenhuma — e as duas identificam juntas, que é exatamente o que
        a janela existe para impedir.
        """
        bucket = self.bucket_for(shard_id)
        lock = self._locks.setdefault(bucket, asyncio.Lock())

        async with lock:
            now = self.clock()
            resets_at = self._resets_at.get(bucket, float("inf"))
            remaining = resets_at - now

            # `0 < remaining` descarta a primeira chamada (inf) e janelas
            # já vencidas; `remaining <= interval` é a checagem do
            # discord.js, que descarta um relógio andado demais.
            if 0 < remaining <= self.interval:
                await self.sleeper(remaining + self.random() * self.jitter)
                now = self.clock()

            self._resets_at[bucket] = now + self.interval
