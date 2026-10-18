"""N shards em um processo — o que o `WebSocketManager` faz no discord.js.

Uma shard é um `GatewayClient`; o manager é o que existe quando o bot
passa de uma: decide quantas conectar, quando, e o que fazer quando uma
morre. As decisões de paridade estão todas nos detalhes:

* **Shards em paralelo, sem stagger** — o `SimpleShardingStrategy`
  dispara todas de uma vez (`Promise.all`); o pacing entre identifies é
  só do throttler por bucket. Um sono artificial entre shards só
  atrasaria o boot de quem tem concorrência alta de verdade.
* **`session_start_limit.remaining` conferido antes de começar** — o
  `WebSocketManager.ts` recusa na cara; a mensagem leva o
  `reset_after`, porque "espera X segundos" é o que resolve, e não
  "limite estourado".
* **Um throttler só, compartilhado** — `max_concurrency` vem do
  `/gateway/bot`, e o bucket da shard `i` é `i % max_concurrency`. Cada
  shard ter o seu seria fingir que a janela de identify é por conexão;
  é por conta.

O que **não** vem do discord.js, e por quê:

* **Falha fatal numa shard fecha todas** — o discord.js propaga o erro
  e deixa o resto rodando até o dono perceber. Aqui um bot meio ligado
  (metade dos servidores recebendo eventos, metade não) é pior que um
  desligado: o orquestrador reinicia, e o identify novo resolve. É a
  mesma filosofia do `ReconnectPolicy`, agora no nível de sharding.
* **Supervisão sem TaskGroup aninhado** — o runner do `Client` já é
  supervisionado; aqui é uma espera `FIRST_COMPLETED` + cancel
  explícito, para que o erro que sobe seja o **original**, não um
  embrulho de grupo.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from kryncord.config import GatewayConfig
from kryncord.errors import GatewayError, LifecycleError
from kryncord.gateway.client import DEFAULT_GATEWAY_URL, EventHandler, GatewayClient
from kryncord.gateway.compression import CompressionMode
from kryncord.gateway.connection import GatewayTransport
from kryncord.gateway.identify import IdentifyProperties, IdentifyThrottler
from kryncord.gateway.reconnect import ReconnectPolicy
from kryncord.gateway.session import InMemorySessionStore, SessionStore
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep
from kryncord.logging import get_logger
from kryncord.models.gateway import GatewayBotInfo

log = get_logger("gateway.manager")


@dataclass(frozen=True, slots=True)
class ShardAssignment:
    """O que o manager decidiu sobre a topologia — para log e teste."""

    shard_ids: tuple[int, ...]
    shard_count: int


class GatewayManager:
    """Todas as shards de um processo, com um só coração.

    O objeto não conecta no construtor — `connect()` é o loop que dura
    enquanto o bot viver, exatamente como no `GatewayClient` de uma
    shard. A diferença é que aqui o loop espera **todas** as shards:
    pronto é tudo pronto, não "a maioria".
    """

    def __init__(
        self,
        *,
        token: str,
        intents: int,
        transport_factory: Callable[[], GatewayTransport],
        config: GatewayConfig | None = None,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        version: int = 10,
        session_store: SessionStore | None = None,
        on_event: EventHandler | None = None,
        shard_ids: Sequence[int] | None = None,
        gateway_information: GatewayBotInfo | None = None,
        properties: IdentifyProperties | Mapping[str, str] | None = None,
        large_threshold: int | None = None,
        presence: Mapping[str, Any] | None = None,
        compression: CompressionMode = CompressionMode.NONE,
        policy: ReconnectPolicy | None = None,
        on_ready: Callable[[], None] | None = None,
        clock: Clock = monotonic_clock,
        sleeper: Sleeper = real_sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("GatewayManager precisa de um token não-vazio.")

        total = 1 if gateway_information is None else gateway_information.shards
        if total < 1:
            raise ValueError(f"`/gateway/bot` devolveu shards={total}; o mínimo é 1.")

        ids = self._resolve_shard_ids(shard_ids, total)
        self._assignment = ShardAssignment(shard_ids=ids, shard_count=total)
        self._limiter = (
            None if gateway_information is None else gateway_information.session_start_limit
        )

        # Um throttler só para todas as shards — o teto é da conta, não
        # do socket. `max_concurrency` vem do `/gateway/bot`; sem
        # informação, 1 (comportamento de sempre).
        self._throttler = IdentifyThrottler(
            max_concurrency=1 if self._limiter is None else self._limiter.max_concurrency,
            clock=clock,
            sleeper=sleeper,
            random=random_source,
        )
        # Um store só também: a sessão de cada shard é item do store,
        # e dois stores seriam duas verdades sobre o mesmo bot.
        self._store: SessionStore = (
            session_store if session_store is not None else InMemorySessionStore()
        )

        self._on_ready = on_ready
        self._prontas: set[int] = set()
        self._tarefas: dict[int, asyncio.Task[None]] = {}
        self._running = False

        self._shards: dict[int, GatewayClient] = {}
        for shard_id in ids:
            self._shards[shard_id] = GatewayClient(
                token=token,
                intents=intents,
                transport_factory=transport_factory,
                config=config,
                gateway_url=gateway_url,
                version=version,
                session_store=self._store,
                on_event=on_event,
                shard_id=shard_id,
                shard_count=total,
                properties=properties,
                large_threshold=large_threshold,
                presence=presence,
                throttler=self._throttler,
                on_ready=partial(self._marca_pronta, shard_id),
                compression=compression,
                policy=policy,
                clock=clock,
                sleeper=sleeper,
                random_source=random_source,
            )

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def assignment(self) -> ShardAssignment:
        """Quais shards este manager cuida, e o total da topologia."""
        return self._assignment

    @property
    def shard_count(self) -> int:
        """Total de shards da topologia — o `n` de `[shard_id, n]`."""
        return self._assignment.shard_count

    @property
    def shards(self) -> tuple[GatewayClient, ...]:
        """As shards, na ordem dos ids."""
        return tuple(self._shards[sid] for sid in self._assignment.shard_ids)

    @property
    def ready(self) -> bool:
        """Todas as shards prontas — "meio pronto" não é pronto."""
        return len(self._prontas) == len(self._shards)

    @property
    def latency(self) -> float | None:
        """Média das latências das shards — `None` se nenhuma mediu.

        Média, não soma nem pior caso: o `/ping` do bot mostra "quanto
        custa falar com o Discord", e isso é uma distância, não uma
        fila. Shard que ainda não mediu (`None`) fica de fora em vez
        de virar zero — zero é latência, não ausência de resposta.
        """
        medidas = [
            medida for shard in self._shards.values() if (medida := shard.latency) is not None
        ]
        if not medidas:
            return None
        return sum(medidas) / len(medidas)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Conecta todas as shards em paralelo. Não devolve enquanto viver.

        Paridade com o `SimpleShardingStrategy`: todas as shards
        conectam ao mesmo tempo, e o que separa os identifies é o
        throttler por bucket. Qualquer falha fatal fecha o manager
        inteiro e propaga o erro original — ver o docstring do módulo.
        """
        if self._running:
            raise LifecycleError("Manager já está conectando — `connect()` não chama duas vezes.")

        self._validar_inicio()
        self._running = True
        self._tarefas = {
            shard_id: asyncio.create_task(
                shard.connect(), name=f"kryncord.gateway.shard-{shard_id}"
            )
            for shard_id, shard in self._shards.items()
        }

        try:
            feitas, _ = await asyncio.wait(
                set(self._tarefas.values()), return_when=asyncio.FIRST_COMPLETED
            )
            primeira = next(iter(feitas))
            if primeira.cancelled():
                raise asyncio.CancelledError
            erro = primeira.exception()
            if erro is not None:
                log.error("Shard morreu com falha fatal: %r", erro)
                await self.close()
                raise erro
            # Terminou sem erro: alguém fechou uma shard por fora. Um
            # manager com shard morta é o bot "meio ligado" — fecha tudo.
            await self.close()
        finally:
            await self._limpa_tarefas()

    async def close(self, code: int = 1000, reason: str = "KrynCord closing") -> None:
        """Fecha todas as shards. Idempotente.

        Em paralelo: o shutdown de uma shard não pode segurar o das
        outras — o contrato de shutdown imediato vale por shard e
        vale para o conjunto.
        """
        await asyncio.gather(
            *(shard.close(code, reason) for shard in self._shards.values()),
            return_exceptions=True,  # uma shard que reclama no close não segura as outras
        )
        await self._limpa_tarefas()

    # ------------------------------------------------------------------
    # Operações
    # ------------------------------------------------------------------

    async def update_presence(
        self,
        *,
        since: int | None = None,
        afk: bool = False,
        status: str = "online",
        activities: Sequence[Mapping[str, Any]] = (),
        shard_ids: Sequence[int] | None = None,
    ) -> None:
        """Muda a presença — broadcast para todas as shards, ou subset.

        Presença é propriedade da **sessão**, e cada shard é uma sessão:
        uma shard com status diferente da irmã é bot meio ligado. O teto
        de 5/20s é por conexão (é o Discord que cobra por lá), então
        cada shard cobra o seu na hora do envio.
        """
        alvos = self._shards_selecionadas(shard_ids)
        await asyncio.gather(
            *(
                shard.update_presence(since=since, afk=afk, status=status, activities=activities)
                for shard in alvos
            )
        )

    async def request_guild_members(
        self,
        guild_id: int | str,
        *,
        query: str | None = None,
        limit: int = 0,
        presences: bool = False,
        user_ids: Sequence[int | str] | None = None,
        nonce: str | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Pede os membros pela shard **dona** da guild.

        A conta é a do discord.js: `shard = (guild_id >> 22) %
        shards` — os bits altos do snowflake são a shard de nascimento.
        """
        shard_id = (int(guild_id) >> 22) % self.shard_count
        shard = self._shards.get(shard_id)
        if shard is None:
            raise LifecycleError(
                f"A guild {guild_id} pertence à shard {shard_id}, que não está "
                f"neste manager (conectadas: {sorted(self._shards)})."
            )
        return await shard.request_guild_members(
            guild_id,
            query=query,
            limit=limit,
            presences=presences,
            user_ids=user_ids,
            nonce=nonce,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_shard_ids(shard_ids: Sequence[int] | None, total: int) -> tuple[int, ...]:
        """Quais shards conectar, validando contra o total da topologia."""
        if shard_ids is None:
            return tuple(range(total))

        ids = tuple(shard_ids)
        if not ids:
            raise ValueError("`shard_ids` vazio — conecte ao menos a shard 0.")
        for shard_id in ids:
            if isinstance(shard_id, bool) or not isinstance(shard_id, int):
                raise ValueError(f"`shard_ids` aceita inteiros, veio {shard_id!r}.")
            if not 0 <= shard_id < total:
                raise ValueError(
                    f"shard {shard_id} não existe numa topologia de {total} shard(s) "
                    f"(válidas: 0..{total - 1}). Confira `gateway_information.shards`."
                )
        if len(set(ids)) != len(ids):
            raise ValueError(f"`shard_ids` com repetição: {ids} — cada shard conecta uma vez.")
        return ids

    def _validar_inicio(self) -> None:
        """Confere o teto de identifies antes de gastar um.

        O `WebSocketManager.ts` faz a mesma conta antes do spawn. Contar
        todas as shards, mesmo as com sessão válida no store, é a postura
        conservadora do discord.js — e é a certa: a sessão antiga pode
        ser rejeitada, e descobrir isso com um identify a menos no
        bolso é melhor que descobrir com `4009 Session no longer valid`.
        """
        limite = self._limiter
        if limite is None:
            return
        if limite.remaining < len(self._shards):
            raise GatewayError(
                f"`session_start_limit.remaining` = {limite.remaining}, mas "
                f"{len(self._shards)} shard(s) precisam de identify. O teto "
                f"recarrega em {limite.reset_after:.0f}s — conecte depois "
                f"disso, ou reduza as shards de uma vez."
            )

    def _marca_pronta(self, shard_id: int) -> None:
        """Uma shard estabeleceu sessão. Quando todas, avisa o dono."""
        self._prontas.add(shard_id)
        if len(self._prontas) == len(self._shards) and self._on_ready is not None:
            self._on_ready()

    def _shards_selecionadas(self, shard_ids: Sequence[int] | None) -> list[GatewayClient]:
        """Shards alvo de uma operação — todas, ou o subset pedido."""
        if shard_ids is None:
            return list(self._shards.values())
        faltantes = [sid for sid in shard_ids if sid not in self._shards]
        if faltantes:
            raise LifecycleError(
                f"Shards {faltantes} não estão neste manager (conectadas: {sorted(self._shards)})."
            )
        return [self._shards[sid] for sid in shard_ids]

    async def _limpa_tarefas(self) -> None:
        """Cancela e espera o que sobrou das shards. Idempotente."""
        tarefas, self._tarefas = self._tarefas, {}
        vivas = [tarefa for tarefa in tarefas.values() if not tarefa.done()]
        for tarefa in vivas:
            tarefa.cancel()
        if vivas:
            await asyncio.gather(*vivas, return_exceptions=True)
