"""Heartbeat — o batimento que prova que a sessão está viva.

Sem heartbeat o Discord considera a sessão morta e derruba a conexão
sem avisar. Com heartbeat errado, pior: se mandamos e o ``ACK`` nunca
chega, do lado de lá a conexão está boa e do nosso lado não — é a
**conexão zumbi**, e ela é perigosa justamente porque parece funcionar:
mandamos mensagem, o ``send`` aceita, e nada chega.

A detecção é a mesma do discord.js: antes de mandar o próximo
``HEARTBEAT``, olha se o anterior foi respondido. Não foi, e o socket
está morto — fecha com ``4200``, o código de "estou retomando", que
`reconnect.classify_close` lê como ``RESUME``. A sessão não se perde,
então o custo de um falso positivo é um round-trip.

Por que ``beat_now()`` pula a checagem: um ``op 1`` vindo do Discord
**é** a prova de que o servidor está recebendo. Se o socket estivesse
morto, o pedido não chegava. Recusar mandar num pedido do servidor,
achando que estamos zumbis, seria fechar uma conexão saudável.

A primeira espera é ``interval * random()`` — de 0 até um intervalo
inteiro. Sem isso, um bot que inicia 100 shards ao mesmo tempo bate o
primeiro heartbeat no mesmo milissegundo e o Discord vê um pico
sincronizado. Com o jitter, os batimentos se espalham pela janela.

Separação de responsabilidades: `HeartbeatState` é **puro** — não cria
task, não dorme, não manda nada; o teste dele é uma pilha de asserts.
`Heartbeat` é quem agenda; o teste dele injeta um sleeper falso e um
``send`` que registra. É isso que permite testar a detecção de zumbi
sem um event loop se enrolando.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from kryncord.errors import LifecycleError
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep

#: Manda um ``HEARTBEAT`` carregando a sequence corrente. `None` é a
#: primeira vez — o Discord exige o campo presente mesmo assim, nulo.
SendBeat = Callable[[int | None], Awaitable[None]]

#: Devolve a última sequence vista. O heartbeat não guarda estado de
#: sessão: quem guarda é o `gateway/client.py`.
SequenceProvider = Callable[[], int | None]


@dataclass(slots=True)
class HeartbeatState:
    """O que já aconteceu no batimento. Sem task, sem espera, sem IO.

    O campo que importa é `pending_since`: o instante em que mandamos um
    heartbeat que ainda não foi respondido. Zumbi é ``pending_since``
    não-nulo na hora de mandar o próximo.

    Ele é um **instante**, não um booleano, por uma razão prática: um
    ``op 1`` do Discord pode chegar entre dois batimentos e mandar outro
    heartbeat. Se cada envio re-armasse uma flag, o segundo envio seria
    tratado como recém-mandado e a detecção de zumbi ficaria cega por
    mais um intervalo inteiro. Mantendo o instante original, o prazo não
    é estendido por envios extras — e o ``ACK`` de qualquer um dos dois
    limpa o estado.
    """

    clock: Clock = field(default=monotonic_clock, repr=False)
    """Relógio monotônico, injetável. É o daqui que mede a latência."""
    pending_since: float | None = field(default=None, init=False)
    last_sent_at: float | None = field(default=None, init=False)
    latency_ms: float | None = field(default=None, init=False)
    beats: int = field(default=0, init=False)
    acks: int = field(default=0, init=False)

    @property
    def awaiting_ack(self) -> bool:
        """`True` enquanto houver um heartbeat por responder."""
        return self.pending_since is not None

    @property
    def is_zombie(self) -> bool:
        """Há batimento sem resposta — a conexão não deveria estar viva."""
        return self.pending_since is not None

    def mark_sent(self) -> float:
        """Registra o envio. Devolve o instante, para log e latência."""
        now = self.clock()
        self.last_sent_at = now
        self.beats += 1
        if self.pending_since is None:
            # Só na primeira — ver docstring. Envio extra não estende o prazo.
            self.pending_since = now
        return now

    def ack(self) -> float | None:
        """Registra o ``ACK``. Devolve a latência em ms, ou `None`.

        `None` significa que não havia nada pendente: um ``ACK``
        duplicado, ou um atrasado que chegou depois de outro já ter
        limpado o estado. Não é erro — é o lado melhor de uma rede.
        """
        self.acks += 1
        since = self.pending_since
        self.pending_since = None
        if since is None:
            return None

        latency = (self.clock() - since) * 1000.0
        self.latency_ms = latency
        return latency

    def reset(self) -> None:
        """Zera o batimento. Chamado ao trocar de conexão.

        Levar o ``pending_since`` de uma sessão morta para a nova
        faria a primeira verificação da conexão nova já nascer achando
        que somos zumbis — e fecharíamos uma sessão recém-aberta.
        """
        self.pending_since = None
        self.last_sent_at = None

    def snapshot(self) -> dict[str, object]:
        """Estado legível, para log de diagnóstico."""
        return {
            "beats": self.beats,
            "acks": self.acks,
            "awaiting_ack": self.awaiting_ack,
            "latency_ms": self.latency_ms,
        }


@dataclass(slots=True)
class Heartbeat:
    """Agenda os batimentos e avisa quando a conexão virou zumbi.

    O ciclo é ``dorme → checa zumbi → manda → dorme``. A checagem vem
    **antes** do envio porque é o único momento em que ela responde à
    pergunta certa: "dá para confiar que o último batimento foi
    ouvido?". Checar depois de mandar diria só que o ``send`` aceitou,
    o que em rede nunca é garantia de nada.

    `state` carrega o relógio. `Heartbeat` não tem `clock` próprio de
    propósito: ter dois relógios num objeto só é como ter dois pesos na
    mesma balança — alguém vai ler o errado.
    """

    state: HeartbeatState = field(default_factory=HeartbeatState)
    sleeper: Sleeper = field(default=real_sleep, repr=False)
    random: Callable[[], float] = field(default=random.random, repr=False)
    """Fonte do jitter do primeiro batimento. Injetável: sem isto, o
    teste depende da sorte para a ordem dos eventos."""

    _send: SendBeat | None = field(default=None, repr=False, init=False)
    _sequence: SequenceProvider = field(default=lambda: None, repr=False, init=False)
    _on_zombie: Callable[[], Awaitable[None]] | None = field(default=None, repr=False, init=False)
    _task: asyncio.Task[None] | None = field(default=None, repr=False, init=False)
    _interval: float = field(default=0.0, init=False, repr=False)

    @property
    def running(self) -> bool:
        """`True` enquanto a task de batimento estiver viva."""
        return self._task is not None and not self._task.done()

    @property
    def interval(self) -> float:
        """Intervalo corrente, em segundos. Zero antes do `start()`."""
        return self._interval

    def start(
        self,
        interval_ms: float,
        *,
        send: SendBeat,
        sequence: SequenceProvider = lambda: None,
        on_zombie: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Começa a bater.

        Síncrono de propósito: só cria a task, não espera nada. Levanta
        `LifecycleError` se já estiver rodando ou se o intervalo for
        inválido — dois batimentos na mesma conexão significam que
        alguém perdeu o `stop()`, e a consequência seria o dobro de
        envio, não um erro legível.
        """
        if interval_ms <= 0:
            raise ValueError(f"intervalo do heartbeat precisa ser positivo, recebido {interval_ms}")
        if self.running:
            raise LifecycleError(
                "Heartbeat já está rodando — chame `stop()` antes de `start()` de novo."
            )

        self._send = send
        self._sequence = sequence
        self._on_zombie = on_zombie
        self._interval = interval_ms / 1000.0
        self.state.reset()
        self._task = asyncio.create_task(self._run(), name="kryncord.heartbeat")

    async def stop(self) -> None:
        """Para o batimento e espera a task morrer. Idempotente."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def beat_now(self) -> None:
        """Manda um heartbeat imediato, a pedido do Discord (``op 1``).

        Pula a checagem de zumbi: o pedido veio pelo mesmo socket que
        estaríamos declarando morto, então ele não está.
        """
        await self._send_beat()

    async def _run(self) -> None:
        # `interval * random()` — de 0 a um intervalo inteiro.
        first_wait = self._interval * self.random()
        if first_wait > 0:
            await self.sleeper(first_wait)

        while True:
            if self.state.is_zombie:
                await self._notify_zombie()
                return

            await self._send_beat()
            await self.sleeper(self._interval)

    async def _send_beat(self) -> None:
        send = self._send
        if send is None:  # pragma: no cover - `start()` já exige
            raise LifecycleError("Heartbeat não iniciado.")
        self.state.mark_sent()
        await send(self._sequence())

    async def _notify_zombie(self) -> None:
        on_zombie = self._on_zombie
        if on_zombie is not None:
            await on_zombie()
