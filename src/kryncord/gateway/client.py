"""Coordena o ciclo de vida do Gateway e a entrega de eventos.

Este é o módulo que mantém o bot ligado. Ele repete cinco passos, sempre
nesta ordem:

1. **Abrir** — conectar e esperar o ``HELLO``, que traz o intervalo de
   heartbeat.
2. **Apresentar-se** — ``RESUME`` quando a sessão ainda vale (nenhum
   evento se perde), ``IDENTIFY`` quando não vale (o cache é
   reconstruído do zero).
3. **Bater o coração** — heartbeat em background, com detecção de
   conexão zumbi.
4. **Entregar** — cada ``DISPATCH`` vai para quem pediu. Sem interpretar:
   modelos e sistema de eventos são a Fase 3.
5. **Voltar** — caiu, classifica o motivo e reconecta. Só desiste quando
   a configuração manda ou quando o erro é irrecuperável.

Três decisões de projeto valem a leitura:

**O heartbeat começa depois do Identify, não no `HELLO`.** O discord.js
inicia o timer no `HELLO` e manda o Identify em paralelo — o que deixa
uma janela em que um heartbeat pode sair antes da apresentação, e isso
é ``4003 Not AuthENTICATED``. Adiar o primeiro batimento até depois do
envio não tem custo: o jitter já espera até um intervalo inteiro.

**Sessão sem `session_id` nunca tenta `RESUME`.** Um close code que
classifica como retomável (4002, 4009) não adianta nada se não há sessão
guardada — o `resume` seria rejeitado e pagaríamos um round-trip para
descobrir o que já sabíamos. Aí o `IDENTIFY` entra por conta própria,
antes de qualquer reconexão.

**O shutdown é imediato mesmo em backoff.** Esperar 60 segundos de
reconexão depois de `close()` é o que faz container ser morto com
SIGKILL pelo orquestrador. Por isso toda espera longa deste módulo —
o backoff entre tentativas e a janela do throttler do identify — é
interrompível: `close()` devolve na hora.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final, TypeVar

from kryncord.config import GatewayConfig
from kryncord.enums import CloseCode, GatewayOpcode
from kryncord.errors import (
    ConnectionClosedError,
    FatalGatewayError,
    GatewayError,
    LifecycleError,
)
from kryncord.gateway.compression import CompressionMode, FrameDecoder, build_gateway_url
from kryncord.gateway.connection import (
    GatewaySendRateLimit,
    GatewayTransport,
)
from kryncord.gateway.heartbeat import Heartbeat
from kryncord.gateway.identify import (
    IdentifyProperties,
    IdentifyThrottler,
    build_identify,
    build_resume,
)
from kryncord.gateway.members import MemberChunkTracker
from kryncord.gateway.payloads import Payload, make_heartbeat
from kryncord.gateway.presence import PresenceRateLimit, build_presence_update
from kryncord.gateway.reconnect import (
    RESUMING_CODE,
    ReconnectPolicy,
    Recovery,
    classify_close,
)
from kryncord.gateway.session import InMemorySessionStore, SessionInfo, SessionStore
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep
from kryncord.logging import get_logger

log = get_logger("gateway")

#: Host do Gateway. `GET /gateway/bot` devolve este mesmo valor — fica
#: aqui para o caso de o chamador não ter feito a chamada.
DEFAULT_GATEWAY_URL = "wss://gateway.discord.gg"

#: Marcador devolvido por `_unless_closing` quando `close()` interrompeu
#: a espera. Precisa ser distinto de `None` — `None` pode ser o
#: resultado legítimo do awaitable (todo `-> None` é `None` no sucesso).
INTERRUPIDO: Final = object()

#: Entrega um evento cru. O primeiro argumento é o nome (``READY``,
#: ``MESSAGE_CREATE``), o segundo é o corpo já decodificado.
EventHandler = Callable[[str, Any], Awaitable[None]]

T = TypeVar("T")


class GatewayStatus(StrEnum):
    """Onde a conexão está, em palavras que um log consegue usar."""

    IDLE = "idle"
    """Nunca conectou (ou foi fechado e não tentou de novo)."""

    CONNECTING = "connecting"
    """Socket abrindo, esperando o `HELLO`."""

    IDENTIFYING = "identifying"
    """`IDENTIFY` enviado, esperando o `READY`."""

    RESUMING = "resuming"
    """`RESUME` enviado, esperando o `RESUMED`."""

    READY = "ready"
    """Sessão viva, eventos fluindo."""

    CLOSED = "closed"
    """Fechado por decisão nossa — `connect()` não está rodando."""

    @property
    def is_established(self) -> bool:
        """`True` quando já temos sessão ativa."""
        return self is GatewayStatus.READY


@dataclass(frozen=True, slots=True)
class _RunOutcome:
    """O que uma tentativa de conexão produziu, para o loop decidir."""

    reached_ready: bool = False
    detail: str = ""
    error: BaseException | None = None
    """Exceção original, quando houve. Guardada para `raise ... from`
    no fim das tentativas — sem ela, um `ValueError` de argumento seria
    embrulhado num `GatewayError` e o tipo real se perderia."""


class GatewayClient:
    """Uma conexão Gateway. Uma shard = uma instância.

    O objeto não conecta sozinho no construtor — quem chama `connect()`
    decide quando o bot liga, e a própria `connect()` é o loop que dura
    enquanto o bot viver. Não há task escondida: o ciclo de vida fica
    todo visível em quem chamou.
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
        shard_id: int = 0,
        shard_count: int = 1,
        properties: IdentifyProperties | Mapping[str, str] | None = None,
        large_threshold: int | None = None,
        presence: Mapping[str, Any] | None = None,
        max_concurrency: int = 1,
        throttler: IdentifyThrottler | None = None,
        on_ready: Callable[[], None] | None = None,
        compression: CompressionMode = CompressionMode.NONE,
        policy: ReconnectPolicy | None = None,
        clock: Clock = monotonic_clock,
        sleeper: Sleeper = real_sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("GatewayClient precisa de um token não-vazio.")
        if shard_count < 1:
            raise ValueError(f"shard_count precisa ser ao menos 1, recebido {shard_count}.")
        if not 0 <= shard_id < shard_count:
            raise ValueError(f"shard_id {shard_id} fora do intervalo [0, {shard_count}).")

        cfg = config or GatewayConfig()
        self._token = token
        self._intents = intents
        self._transport_factory = transport_factory
        self._config = cfg
        self._gateway_url = gateway_url
        self._version = version
        # `is not None`, e não `or`: `InMemorySessionStore` define
        # `__len__`, então uma loja vazia é falsy. Com `or`, um store
        # customizado recém-criado seria trocado em silêncio — e o bot
        # passaria a persistir a sessão em memória enquanto o usuário
        # jura que está usando Redis.
        self._store: SessionStore = (
            session_store if session_store is not None else InMemorySessionStore()
        )
        self._on_event = on_event
        self._shard_id = shard_id
        self._shard_count = shard_count
        self._properties = properties
        self._large_threshold = large_threshold
        self._presence = presence
        self._compression = compression
        self._clock = clock
        self._sleeper = sleeper
        self._random = random_source

        self._policy = policy or ReconnectPolicy(
            max_attempts=cfg.max_reconnect_attempts,
            random=random_source,
        )
        # Throttler injetável: o manager de shards compartilha **um**
        # entre todas — o teto de identify é por conta do aplicativo,
        # não por conexão, e cada shard ter o seu seria fingir o
        # contrário. Quem usa o `GatewayClient` direto (uma shard)
        # continua recebendo o seu, como sempre.
        self._throttler = (
            throttler
            if throttler is not None
            else IdentifyThrottler(
                max_concurrency=max_concurrency,
                clock=clock,
                sleeper=sleeper,
                random=random_source,
            )
        )
        self._on_ready_hook = on_ready
        self._decoder = FrameDecoder(compression)
        self._send_limit = GatewaySendRateLimit(clock=clock, sleeper=sleeper, random=random_source)
        self._heartbeat = Heartbeat(sleeper=sleeper, random=random_source)
        self._members = MemberChunkTracker()
        self._presence_limit = PresenceRateLimit(clock=clock, sleeper=sleeper, random=random_source)

        self._status = GatewayStatus.IDLE
        self._running = False
        self._closing = asyncio.Event()
        self._transport: GatewayTransport | None = None
        self._session: SessionInfo | None = None
        self._sequence: int | None = None
        self._reached_ready = False
        self._network_error = False

    # ------------------------------------------------------------------
    # AAPI pública
    # ------------------------------------------------------------------

    @property
    def status(self) -> GatewayStatus:
        return self._status

    @property
    def latency(self) -> float | None:
        """Round-trip do heartbeat (``op 1`` → ``ACK``) em ms.

        `None` antes do primeiro ACK. É o relógio monotônico da
        `HeartbeatState` que mede — o mesmo que vira log de diagnóstico
        e o ``ping`` que o `Client.latency` expõe. Numa reconexão, o
        último valor fica legível até o primeiro ACK da nova conexão
        chegar (o `reset()` limpa a janela pendente, não a medição).
        """
        return self._heartbeat.state.latency_ms

    @property
    def ready(self) -> bool:
        """`True` quando a sessão está estabelecida e eventos fluem."""
        return self._status.is_established

    @property
    def sequence(self) -> int | None:
        """Última sequence vista — o "continuar daqui" do `RESUME`."""
        return self._sequence

    @property
    def session_id(self) -> str | None:
        """`session_id` corrente, ou `None` se ainda não há sessão."""
        return None if self._session is None else self._session.session_id

    @property
    def shard_id(self) -> int:
        return self._shard_id

    async def connect(self) -> None:
        """Conecta e entrega eventos até `close()` ou uma falha fatal.

        Este é o loop de vida. Ele retorna em três casos: quem chamou
        pediu `close()`, o Discord rejeitou algo irrecuperável (token,
        intents, shard), ou esgotaram-se as tentativas de reconexão.
        Qualquer um deles levanta exceção ou retorna — nunca fica preso
        silenciosamente.
        """
        if self._running:
            raise LifecycleError("Gateway já está conectando — `connect()` não chama duas vezes.")
        if self._status is GatewayStatus.READY:
            raise LifecycleError("Gateway já está `READY` — chame `close()` antes de reconectar.")

        self._running = True
        self._closing = asyncio.Event()
        attempt = 0

        try:
            while not self._closing.is_set():
                try:
                    outcome = await self._run_once()
                except asyncio.CancelledError:
                    raise
                except FatalGatewayError:
                    raise
                except Exception as exc:
                    # `_run_once` já converte o esperado em `recovery`.
                    # Sobrou algo fora da lista — ainda assim vale tentar
                    # de novo, mas com um teto: `max_attempts` limita, e o
                    # `from` lá embaixo preserva o tipo original.
                    outcome = _RunOutcome(
                        reached_ready=False,
                        detail=f"{type(exc).__name__}: {exc}",
                        error=exc,
                    )
                    log.warning("Falha inesperada no Gateway: %s", exc)

                if self._closing.is_set():
                    break

                if outcome.reached_ready:
                    # Tentativas são consecutivas, não totais: um bot que
                    # viveu seis horas tem o orçamento inteiro de volta.
                    attempt = 0

                if not self._policy.should_retry(attempt + 1):
                    message = (
                        "O Gateway desistiu de reconectar — tentativas de "
                        f"reconexão feitas: {attempt}. "
                        f"Motivo da última queda: {outcome.detail}. "
                        "Aumente `gateway.max_reconnect_attempts` ou use `None` "
                        "para tentar indefinidamente."
                    )
                    if outcome.error is not None:
                        raise GatewayError(message) from outcome.error
                    raise GatewayError(message)

                attempt += 1
                delay = self._policy.delay(attempt)
                log.warning(
                    "Gateway caiu (tentativa %d%s) — reconectando em %.2fs. Motivo: %s",
                    attempt,
                    "" if self._policy.max_attempts is None else f"/{self._policy.max_attempts}",
                    delay,
                    outcome.detail,
                )
                await self._unless_closing(self._sleeper(delay))
        finally:
            self._running = False
            await self._shutdown()

    async def close(self, code: int = 1000, reason: str = "KrynCord closing") -> None:
        """Fecha a conexão e encerra `connect()`. Idempotente.

        Interrompe também as esperas longas — backoff entre tentativas e
        janela do throttler do identify; ver `_unless_closing` sobre por
        que isso importa.
        """
        self._closing.set()
        await self._heartbeat.stop()
        transport = self._transport
        if transport is not None:
            try:
                await transport.close(code, reason)
            except Exception:
                log.debug("Erro ao fechar a conexão do Gateway", exc_info=True)
        if not self._running:
            # `connect()` cuida do estado quando ele está rodando. Aqui
            # fora, ninguém vai fazer — e um `close()` que não muda o
            # `status` deixa o objeto mentindo sobre si mesmo.
            self._status = GatewayStatus.CLOSED

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
        """Puxa os membros de uma guild pela conexão (op 8).

        O `guild.members.fetch()` do discord.js, em payload cru: devolve
        a soma dos `members` de todos os `GUILD_MEMBERS_CHUNK` do pedido,
        sem modelo por cima. Os chunks continuam chegando como evento em
        `on_event` como sempre chegaram — este método só soma o que já é
        público e espera o fim.

        `limit=0` pede a guild inteira; `query` filtra por nome; com
        `user_ids`, um `query` vazio casa com qualquer nome. `nonce`
        ausente vira uuid de 32 chars (teto do Discord); `timeout`
        sobrepõe os 120s do módulo, renovados a cada chunk.

        Exige sessão estabelecida (READY/RESUMED): op 8 fora de sessão é
        frame que o Discord descarta sem avisar ninguém.
        """
        if not self._reached_ready or self._session is None:
            raise LifecycleError(
                "`request_guild_members` exige sessão estabelecida — "
                "espere o READY (ou RESUMED) antes de pedir membros."
            )

        pedido = self._members.abrir(guild_id, limit=limit, nonce=nonce, timeout=timeout)

        body: dict[str, Any] = {
            "guild_id": str(guild_id),
            "presences": presences,
            "nonce": pedido.nonce,
            "limit": limit,
        }
        if query is not None:
            body["query"] = query
        if user_ids is not None:
            body["user_ids"] = [str(uid) for uid in user_ids]

        try:
            # Não é op importante: o pedido de membros é evento como
            # qualquer outro e conta no budget de 115 frames.
            await self._send(Payload(op=GatewayOpcode.REQUEST_GUILD_MEMBERS, data=body))
        except BaseException:
            # Envio falhou no meio (sem transporte, cancelamento): sem
            # descartar o pedido, o futuro esperaria chunk que nunca
            # vem e o asyncio reclamaria no GC.
            self._members.abortar(pedido.nonce)
            raise

        return await pedido.futuro

    async def update_presence(
        self,
        *,
        since: int | None = None,
        afk: bool = False,
        status: str = "online",
        activities: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        """Muda a presença em runtime (op 3).

        O `client.presence.set()` do discord.js, com as duas diferenças
        do doc 05: o teto de 5/20s é **cobrado na frente** (quem manda
        mais paga a espera, em vez de ter o update sumido sem aviso), e
        a mudança fora de sessão é recusada na cara (`LifecycleError`),
        não enfileirada em silêncio até o `RESUMED`.

        `since` é há quanto tempo (ms) o "jogo" começou, ou `None`;
        `activities` é lista de dicts crus, os mesmos que o Discord
        devolve nos eventos. A presença inicial, antes do READY, vai no
        IDENTIFY — `identify.py` — e não aqui.
        """
        if not self._reached_ready or self._session is None:
            raise LifecycleError(
                "`update_presence` exige sessão estabelecida — "
                "espere o READY (ou RESUMED), ou ponha a presença inicial no identify."
            )

        await self._presence_limit.acquire()
        await self._send(
            build_presence_update(since=since, afk=afk, status=status, activities=activities)
        )

    # ------------------------------------------------------------------
    # Uma tentativa de conexão
    # ------------------------------------------------------------------

    async def _run_once(self) -> _RunOutcome:
        """Abre, apresenta, bombeia eventos, e devolve o que sobrou.

        Falhas de rede/protocolo **não** estouram daqui: viram um
        `Recovery` que o loop de `connect()` sabe usar. Só `FatalGatewayError`
        (4004, 4010–4014) e `CancelledError` sobem.
        """
        self._sequence = None
        self._session = None
        self._reached_ready = False
        self._network_error = False
        self._decoder.reset()
        self._heartbeat.state.reset()

        # A sessão é lida **antes** de abrir o socket: ela decide a URL
        # (a `resume_gateway_url` é específica) e o payload.
        session = await self._store.retrieve(self._shard_id)
        if session is not None and not session.can_resume_with(self._shard_count):
            log.info(
                "Shard %d/%d mudou de topologia (tinha %d) — descartando sessão.",
                self._shard_id,
                self._shard_count,
                session.shard_count,
            )
            await self._store.update(self._shard_id, None)
            session = None
        self._session = session

        transport = self._transport_factory()
        self._transport = transport
        self._status = GatewayStatus.CONNECTING

        recovery = Recovery.IDENTIFY
        detail = "conexão encerrada sem motivo declarado"

        try:
            await transport.connect(self._url_for(session))
            # A janela de envio é por conexão: o socket novo tem budget
            # novo do Discord. É o `onopen` do discord.js, que zera o
            # contador em todo (re)connect.
            self._send_limit.reset()
            hello = await self._wait_hello()

            if session is None:
                self._status = GatewayStatus.IDENTIFYING
                apresentou = await self._unless_closing(
                    self._apresenta(
                        build_identify(
                            token=self._token,
                            intents=self._intents,
                            properties=self._properties,
                            large_threshold=self._large_threshold,
                            shard=(
                                (self._shard_id, self._shard_count)
                                if self._shard_count > 1
                                else None
                            ),
                            presence=self._presence,
                        )
                    )
                )
            else:
                self._status = GatewayStatus.RESUMING
                apresentou = await self._unless_closing(
                    self._send(
                        build_resume(
                            token=self._token,
                            session_id=session.session_id,
                            sequence=session.sequence,
                        ),
                        important=True,
                    )
                )

            if apresentou is INTERRUPIDO:
                # `close()` chegou no meio da apresentação. Devolve sem
                # levantar: o loop de `connect()` vê o closing e encerra.
                return _RunOutcome(
                    reached_ready=False, detail="close() durante a apresentação da sessão"
                )

            # Depois do Identify, nunca antes: ver docstring do módulo.
            self._start_heartbeat(hello)

            # O prazo do `READY` começa a correr quando o Discord
            # recebe a apresentação — é o `readyTimeout` de 15s do
            # discord.js, que já estava no config e faltava aplicar.
            ready_deadline = self._clock() + self._config.ready_timeout
            recovery = await self._pump(ready_deadline)
            detail = f"o Discord pediu {recovery.value}"

        except asyncio.CancelledError:
            raise
        except FatalGatewayError:
            raise
        except (ConnectionClosedError, GatewayError, OSError, TimeoutError) as exc:
            self._network_error = isinstance(exc, OSError)
            # `self._session`, e não o `session` local: este é o que veio
            # do store **antes** de conectar, e por isso é `None` em toda
            # primeira conexão. Quem decide retomar é a sessão viva — a
            # que o `READY` acabou de criar.
            recovery = self._recovery_for(exc, self._session)
            detail = f"{type(exc).__name__}: {exc}"
        finally:
            await self._heartbeat.stop()
            await self._close_transport(transport)
            self._transport = None

        if recovery is Recovery.RESUME and self._session is None:
            # Close code retomável, mas não há sessão para retomar.
            recovery = Recovery.IDENTIFY
            detail += " (sem sessão guardada — identify novo)"

        if recovery is Recovery.IDENTIFY:
            # A sessão morreu — e ela morre **do store também**. Sem
            # isto, a próxima tentativa leria a `session_id` antiga e
            # mandaria `RESUME` para um close code que acabou de dizer
            # "identify", pagando um round-trip até o `invalid_session`
            # confirmar o que a tabela já sabia.
            await self._store.update(self._shard_id, None)
            self._session = None
            self._sequence = None

        return _RunOutcome(reached_ready=self._reached_ready, detail=detail)

    async def _wait_hello(self) -> Payload:
        """Espera o `HELLO`, que traz o intervalo de heartbeat.

        Um timeout aqui existe porque sem ele um Discord que aceita o
        socket e fica calado deixaria o bot "ligado" para sempre sem
        batimento nenhum — e nada nesse estado parece errado num log.
        """
        try:
            payload = await asyncio.wait_for(
                self._recv_payload(), timeout=self._config.hello_timeout
            )
        except TimeoutError as exc:
            raise GatewayError(
                f"Gateway não mandou `HELLO` em {self._config.hello_timeout}s."
            ) from exc

        if not payload.is_hello:
            raise GatewayError(
                f"Primeiro frame do Gateway deveria ser `HELLO` (op 10), veio op {payload.op}."
            )
        return payload

    def _start_heartbeat(self, hello: Payload) -> None:
        interval_ms = self._config.heartbeat_interval
        if interval_ms is None:
            interval_ms = hello.heartbeat_interval_ms
        if interval_ms is None:
            raise GatewayError("`HELLO` sem `heartbeat_interval` válido — frame malformado.")

        self._heartbeat.start(
            interval_ms,
            send=self._send_beat,
            sequence=lambda: self._sequence,
            on_zombie=self._on_zombie,
        )

    async def _pump(self, ready_deadline: float | None) -> Recovery:
        """Lê frames até a conexão acabar. Devolve o `Recovery` pedido.

        `ready_deadline` é o prazo para `READY`/`RESUMED` chegar — só
        vale enquanto a sessão não está estabelecida. Depois disso é
        operação normal e o prazo some.
        """
        while True:
            payload = await self._recv_frame(ready_deadline)

            if payload.sequence is not None:
                await self._track_sequence(payload.sequence)

            if payload.is_heartbeat:
                # O Discord pediu um agora. Conta como heartbeat, não
                # como evento: op 1 é dos `ImportantGatewayOpcodes` que
                # o discord.js não deduz do budget de envio.
                await self._send(make_heartbeat(self._sequence), important=True)
                continue

            if payload.is_heartbeat_ack:
                latency = self._heartbeat.state.ack()
                if latency is not None:
                    log.debug("Heartbeat ACK em %.1fms", latency)
                continue

            if payload.is_reconnect:
                log.info("Gateway pediu reconexão (op 7).")
                return Recovery.RESUME

            if payload.is_invalid_session:
                return await self._handle_invalid_session(payload)

            if payload.is_dispatch:
                await self._handle_dispatch(payload)
                continue

            log.debug("Opcode não tratado ignorado: op=%d", payload.op)

    async def _recv_frame(self, ready_deadline: float | None) -> Payload:
        """Recebe o próximo frame, com o prazo do `READY` ainda correndo.

        Sem este prazo, um Discord que aceita o socket e fica calado
        deixaria o bot "ligado" para sempre: o heartbeat bate, o ACK
        chega, nada é zumbi — e a sessão nunca existe. Com ele, o
        silêncio vira `GatewayError` e o ciclo de recuperação tenta de
        novo, que é o `readyTimeout` de 15s do discord.js.

        O prazo é medido pelo relógio injetado (testes controlam o
        tempo); a espera em si é a do event loop, que é quem conta
        segundos de verdade. Depois do `READY`, sem prazo nenhum — a
        partir daqui o silêncio é problema do heartbeat, não deste
        frame.
        """
        if self._reached_ready or ready_deadline is None:
            return await self._recv_payload_checked()

        restante = ready_deadline - self._clock()
        if restante <= 0:
            raise GatewayError(
                f"Gateway não mandou `READY`/`RESUMED` em {self._config.ready_timeout}s."
            )
        try:
            return await asyncio.wait_for(self._recv_payload_checked(), timeout=restante)
        except TimeoutError as exc:
            raise GatewayError(
                f"Gateway não mandou `READY`/`RESUMED` em {self._config.ready_timeout}s."
            ) from exc

    async def _recv_payload_checked(self) -> Payload:
        """Recebe um frame, fechando com 4002 se ele for ilegível.

        Um frame malformado é `DECODE_ERROR`: o Discord espera que a
        conexão seja fechada com esse código para saber que o problema é
        de decodificação, e não de rede. Fechar sem aviso faria ele
        classificar como queda genérica.
        """
        try:
            return await self._recv_payload()
        except ConnectionClosedError:
            raise
        except GatewayError as exc:
            log.warning("Frame ilegível do Gateway, fechando com 4002: %s", exc)
            await self._close_transport_code(CloseCode.DECODE_ERROR, "Decode error")
            raise ConnectionClosedError(
                f"Frame ilegível do Gateway: {exc}",
                code=int(CloseCode.DECODE_ERROR),
                reason="Decode error",
            ) from exc

    async def _recv_payload(self) -> Payload:
        """Recebe até ter um frame completo. `ConnectionClosedError` se cair."""
        transport = self._require_transport()
        while True:
            raw = await transport.recv()
            text = self._decoder.decode(raw)
            if text is not None:
                return Payload.decode(text)
            # `None` = pedaço de meio frame no `zlib-stream`. Continua.

    async def _handle_dispatch(self, payload: Payload) -> None:
        name = payload.event_name or ""

        if name == "READY":
            await self._on_ready(payload)
        elif name == "RESUMED":
            self._reached_ready = True
            self._status = GatewayStatus.READY
            log.info(
                "Sessão retomada — %d eventos recuperados de volta.",
                self._sequence if self._sequence is not None else 0,
            )
            self._avisa_pronto()
        elif name == "GUILD_MEMBERS_CHUNK":
            # Correlaciona com um pedido op 8 aberto, se houver. O
            # evento segue para `on_event` mesmo assim — passthrough
            # cru: quem não usa a API de chunks continua vendo tudo.
            self._members.on_chunk(payload.data)
        elif name == "RATE_LIMITED":
            # Mesma lógica: rejeita o pedido correspondente (nonce em
            # `d.meta.nonce`) e deixa o evento passar adiante.
            self._members.on_rate_limited(payload.data)

        if self._on_event is None:
            return
        try:
            await self._on_event(name, payload.data)
        except Exception:
            log.exception("Erro no handler do evento %s", name)

    async def _on_ready(self, payload: Payload) -> None:
        data = payload.data
        if not isinstance(data, Mapping):
            raise GatewayError(f"`READY` com corpo inesperado: {type(data).__name__}")

        sequence = payload.sequence if payload.sequence is not None else self._sequence
        if sequence is None:
            raise GatewayError("`READY` sem sequence — não dá para retomar depois.")

        session = SessionInfo.from_dispatch(
            data,
            sequence=sequence,
            shard_id=self._shard_id,
            shard_count=self._shard_count,
        )
        if session is None:
            raise GatewayError(
                "`READY` sem `session_id` ou `resume_gateway_url` — "
                "o Discord não mandou o que é preciso para retomar."
            )

        await self._store.update(self._shard_id, session)
        self._session = session
        self._sequence = session.sequence
        self._reached_ready = True
        self._status = GatewayStatus.READY
        log.info(
            "Sessão pronta (shard %d, sessão %s) em %s.",
            self._shard_id,
            session.session_id[:8],
            session.resume_url,
        )
        self._avisa_pronto()

    def _avisa_pronto(self) -> None:
        """Avisa quem cuida das shards que **esta** sessão está pronta.

        O hook existe para o manager: uma shard só não é bot pronto, e
        o `start()` só pode devolver quando todas estiverem. Idempotente
        por natureza — reconexão reavisa, e quem ouve já trata o
        segundo aviso como o primeiro.
        """
        if self._on_ready_hook is not None:
            self._on_ready_hook()

    async def _handle_invalid_session(self, payload: Payload) -> Recovery:
        """`op 9` — a sessão foi rejeitada. Decide entre retomar e recomeçar.

        ``d: true`` com sessão guardada → retoma; ``d: false`` (ou sem
        sessão) → identify novo. A espera entre a rejeição e a nova
        tentativa é o backoff da política de reconexão — o mesmo
        anti-thrash de 500ms do discord.js, que no `@discordjs/ws`
        substituiu a espera aleatória de 1–5s que este módulo fazia.
        Pagar as duas era dobrar a conta da recuperação: o throttler de
        identify já garante os 5s do identify seguinte.
        """
        resumable = bool(payload.is_resumable)
        session = self._session

        if resumable and session is not None:
            log.info("`invalid_session` retomável (d=%s) — retomando sessão.", payload.data)
            return Recovery.RESUME

        log.info(
            "`invalid_session` sem retomada possível (d=%s, sessão=%s) — identify novo.",
            payload.data,
            "sim" if session is not None else "não",
        )
        await self._store.update(self._shard_id, None)
        self._session = None
        self._sequence = None
        return Recovery.IDENTIFY

    # ------------------------------------------------------------------
    # Decisão de reconexão
    # ------------------------------------------------------------------

    def _recovery_for(self, exc: BaseException, session: SessionInfo | None) -> Recovery:
        """Traduz uma exceção de conexão na próxima ação.

        Um código retomável só vale alguma coisa se **há sessão**.
        Sem `session_id`, `RESUME` não é uma opção — é um round-trip que
        termina em `invalid_session`. Aí o `IDENTIFY` entra sozinho.
        """
        if isinstance(exc, ConnectionClosedError):
            decision = classify_close(exc.code, network_error=self._network_error)
            if decision.recovery is Recovery.FATAL:
                raise FatalGatewayError(
                    f"Gateway recusou a conexão (código {exc.code}): {decision.reason}. "
                    "Esta falha não se recupera reconectando.",
                    code=exc.code,
                ) from exc
            log.info("Conexão fechada (código %s): %s", exc.code, decision.reason)
            recovery = decision.recovery
        else:
            recovery = Recovery.RESUME if session is not None else Recovery.IDENTIFY
            log.warning("Conexão falhou sem código de fechamento: %s", exc)

        if recovery is Recovery.RESUME and session is None:
            return Recovery.IDENTIFY
        return recovery

    async def _on_zombie(self) -> None:
        """Fechar por conexão zumbi: heartbeat mandado, `ACK` nunca veio.

        O código é `4200` — o mesmo que o discord.js usa — e
        `classify_close` o lê como `RESUME`. A sessão não se perde,
        então o custo de um falso positivo é um round-trip.
        """
        log.warning("Conexão zumbi: heartbeat sem ACK. Fechando com 4200 para retomar sessão.")
        await self._close_transport_code(RESUMING_CODE, "Zombie connection")

    # ------------------------------------------------------------------
    # Envio e utilidades
    # ------------------------------------------------------------------

    async def _send(self, payload: Payload, *, important: bool = False) -> None:
        """Manda um frame, respeitando o teto de 115/60s do Gateway.

        `important=True` para os ops que o Discord não deduz do teto —
        heartbeat (1), identify (2) e resume (6), os
        `ImportantGatewayOpcodes` do discord.js. Só eventos de verdade
        gastam budget.
        """
        await self._send_limit.acquire(important=important)
        await self._require_transport().send(payload.encode())

    async def _apresenta(self, payload: Payload) -> None:
        """Espera o teto de identify e manda o `IDENTIFY`.

        A espera vem ANTES do envio, não depois: o teto é por janela, e
        proteger depois é chegar ao 429. A janela do throttler pode
        chegar a ~6,5s — por isso esta espera roda sob `_unless_closing`,
        e um `close()` no meio dela devolve na hora.
        """
        await self._throttler.wait(self._shard_id)
        await self._send(payload, important=True)

    async def _send_beat(self, sequence: int | None) -> None:
        """Callback do `Heartbeat`. Conta como heartbeat, não como
        evento: o batimento é op importante, como no discord.js."""
        await self._send(make_heartbeat(sequence), important=True)

    async def _track_sequence(self, sequence: int) -> None:
        """Guarda a sequence corrente, mantendo a sessão sempre atual.

        Atualizar a cada `DISPATCH` (e não só no `READY`) é o que faz o
        `RESUME` continuar do ponto exato em vez de reenviar tudo desde o
        início — o `discord.js` faz o mesmo. O custo é um dicionário
        por evento no store em memória, que é irrelevante.
        """
        self._sequence = sequence
        session = self._session
        if session is None:
            return
        self._session = replace(session, sequence=sequence)
        await self._store.update(self._shard_id, self._session)

    def _url_for(self, session: SessionInfo | None) -> str:
        """URL da conexão: a `resume_gateway_url` quando há sessão.

        Usar a base `/gateway/bot` para retomar daria `4009 Session no
        longer valid`, que parece bug do biblioteca.
        """
        base = self._gateway_url if session is None else session.resume_url
        return build_gateway_url(base, version=self._version, compression=self._compression)

    def _require_transport(self) -> GatewayTransport:
        transport = self._transport
        if transport is None:
            raise ConnectionClosedError("Sem conexão ativa com o Gateway.")
        return transport

    async def _close_transport(self, transport: GatewayTransport) -> None:
        try:
            await transport.close(1000, "Connection cycle ended")
        except Exception:
            log.debug("Erro ao encerrar a conexão", exc_info=True)

    async def _close_transport_code(self, code: int, reason: str) -> None:
        transport = self._transport
        if transport is None:
            return
        try:
            await transport.close(code, reason)
        except Exception:
            log.debug("Erro ao fechar a conexão (código %d)", code, exc_info=True)

    async def _unless_closing(self, awaitable: Awaitable[T]) -> T | object:
        """Corre `awaitable`, mas sai na hora se `close()` chegar.

        Devolve o resultado de `awaitable`, ou `INTERRUPIDO` se o
        `close()` interrompeu — nunca `None` como marcador, porque
        `None` é o resultado legítimo de um monte de awaitable. Sem
        isso, um bot em backoff de 60s — ou esperando a janela do
        throttler do identify virar — levaria até 60s para desligar
        depois de `close()`; e tempo de desligamento é exatamente o que
        um orquestrador de container mede antes de mandar `SIGKILL`.
        """
        if self._closing.is_set():
            return INTERRUPIDO

        operacao = asyncio.ensure_future(awaitable)
        closing = asyncio.ensure_future(self._closing.wait())
        try:
            done, _ = await asyncio.wait({operacao, closing}, return_when=asyncio.FIRST_COMPLETED)
            if operacao in done:
                return operacao.result()
            return INTERRUPIDO
        finally:
            closing.cancel()
            if not operacao.done():
                operacao.cancel()

    async def _shutdown(self) -> None:
        """Fecha o que sobrou e marca o estado final. Sempre roda."""
        await self._heartbeat.stop()
        # Pedidos op 8 abertos não sobrevivem ao socket: cancelar os
        # futuros é o que evita "task was destroyed but it is pending"
        # em quem estava esperando membros.
        self._members.close()
        transport = self._transport
        self._transport = None
        if transport is not None:
            await self._close_transport(transport)
        self._status = GatewayStatus.CLOSED
