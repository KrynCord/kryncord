"""Fachada principal da KrynCord.

`Client` orquestra: guarda a configuração, mantém o ciclo de vida, e
expõe as camadas REST e Gateway. Ele **não** implementa nada — coerente
com a arquitetura do discord.js v2 (`core/src/Client.ts`), onde o
`Client` só conecta `gateway.on(Dispatch) → emit(t, data)` e injeta a
API nos handlers.

O que existe aqui hoje é a ligação mínima para manter um bot no ar:
`start()` abre o Gateway e **só devolve quando o `READY` chega**;
`close()` fecha a conexão e o que ficou pendurado. Os payloads passam
por `events/dispatcher.py`, que os converte em modelos antes de entregar
ao handler — `message.content`, não `data["content"]`.

Uso::

    from kryncord import Client, Config, Intents

    config = Config(token=os.environ["DISCORD_TOKEN"], intents=Intents.default())

    async with Client(config) as client:
        @client.on("message_create")
        async def mensagem(message):
            print(message.author_name, message.content)

        await client.start()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self

from kryncord.api import DiscordAPI
from kryncord.config import Config
from kryncord.errors import GatewayError, LifecycleError
from kryncord.events.dispatcher import EventHandler
from kryncord.events.snapshot import instantanea
from kryncord.gateway.client import GatewayClient
from kryncord.gateway.compression import CompressionMode
from kryncord.gateway.connection import GatewayTransport, WebSocketConnection
from kryncord.gateway.session import SessionStore
from kryncord.http.authentication import Token
from kryncord.intents import Intents
from kryncord.internal.tasks import TaskRegistry
from kryncord.lifecycle import Lifecycle
from kryncord.logging import get_logger
from kryncord.registry import Registry
from kryncord.registry import registry as _registry_global
from kryncord.responders.dispatch import Esperas
from kryncord.rest.client import RESTClient
from kryncord.state import ConnectionState, EventUpdater

if TYPE_CHECKING:
    from types import TracebackType

    import httpx

log = get_logger("client")


def _token_of(config: Config) -> Token | None:
    """Token para o REST, ou `None` quando ainda não há um.

    `None` (e não `Token("")`) importa por causa da mensagem de erro.
    Com `Token("")`, o header sairia ``Authorization: Bot `` — malformado
    —, o Discord responderia 401 apontando para o token, e quem lê o
    erro correria para rotacionar um token que nunca esteve errado.

    Com `None`, `HTTPClient.build_headers` recusa a requisição antes de
    mandar, com `HTTPError("Requisição autenticada sem token
    configurado")`. Diz o que falta, sem apontar para o lugar errado.
    """
    return Token(value=config.token) if config.token else None


class Client:
    """Ponto de entrada da aplicação.

    Uso recomendado — `async with`, para garantir encerramento::

        from kryncord import Client, Config, Intents

        config = Config(token=..., intents=Intents.default())

        async with Client(config) as client:
            await client.start()

    Sem o contexto, `start()` ainda funciona, mas `close()` precisa ser
    chamado explicitamente — senão as tasks ficam penduradas no shutdown.
    """

    __slots__ = (
        "_api",
        "_closed",
        "_compression",
        "_config",
        "_dispatcher",
        "_esperas",
        "_gateway",
        "_gateway_failure",
        "_lifecycle",
        "_loop",
        "_parar",
        "_ready",
        "_registry",
        "_rest",
        "_session_store",
        "_started",
        "_state",
        "_tasks",
        "_transport_factory",
        "_updater",
    )

    def __init__(
        self,
        config: Config,
        *,
        registry: Registry | None = None,
        transport_factory: Callable[[], GatewayTransport] | None = None,
        session_store: SessionStore | None = None,
        compression: CompressionMode = CompressionMode.NONE,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._lifecycle = Lifecycle("client")
        #: O registry é o que os `@command`, `@responder` e `@event`
        #: do módulo de usuário encontram sem apontar um client (`K12`).
        #: O default é o global do processo; em teste, `Registry()` novo
        #: — e o `0009` listou a contaminação entre testes como o motivo.
        self._registry = registry if registry is not None else _registry_global
        self._dispatcher = self._registry.events
        #: Tasks disparadas por `ctx.spawn` — com dono, canceladas no
        #: shutdown (`0012`). Não é o `_lifecycle`: o `TaskGroup` dele
        #: cancela a task pai quando uma filha falha, que é o oposto do
        #: que um log de handler deve provocar.
        self._tasks = TaskRegistry()
        #: As esperas de `await_responder` — single-shot, por
        #: `custom_id`. O client é o dono porque a espera atravessa o
        #: despacho: quem espera fica no handler, e quem resolve fica no
        #: próximo clique (`0023`, R3).
        self._esperas = Esperas()
        self._gateway: GatewayClient | None = None
        #: Sinal de "alguém chamou `close()`" — é o que o `run()` (que
        #: bloqueia o thread) espera. O `_ready` não serve: ele é
        #: apagado no fechamento, e uma espera que nunca termina num
        #: shutdown seria o pior lugar para descobrir.
        self._parar = asyncio.Event()
        #: O loop onde este client está rodando, quando instalou o
        #: handler de exceção dele (`0026` §10). `None` fora do `start()`.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Injetável para teste: o default abre um socket de verdade, e
        # nenhum teste deste projeto abre um.
        self._transport_factory = transport_factory or WebSocketConnection
        self._session_store = session_store
        self._compression = compression
        # O REST é construído aqui, e não no `start()`, porque `api` tem
        # que existir antes — um handler registrado fora do `async with`
        # ainda captura `client.api` no closure.
        self._rest = RESTClient(config.http, token=_token_of(config), transport=http_transport)
        self._api = DiscordAPI(self._rest)
        # O cache é construído aqui, junto com o REST, pelo mesmo motivo:
        # existe desde a construção, para que um handler registrado fora
        # do `async with` já capture `client.cache` no closure.
        self._state = ConnectionState(policy=config.cache)
        self._updater = EventUpdater(self._state)
        self._ready = asyncio.Event()
        self._gateway_failure: BaseException | None = None
        self._started = False
        self._closed = False

    @property
    def config(self) -> Config:
        return self._config

    @property
    def intents(self) -> Intents:
        return self._config.intents

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_ready(self) -> bool:
        """`True` quando o Gateway chegou ao `READY` (ou `RESUMED`).

        Não é o mesmo que `is_started`: entre os dois existe o Identify,
        que o Discord pode recusar.
        """
        return self._ready.is_set()

    @property
    def gateway(self) -> GatewayClient | None:
        """A conexão Gateway, ou `None` antes do `start()`."""
        return self._gateway

    @property
    def latency(self) -> float | None:
        """Latência do Gateway em ms — o round-trip do heartbeat.

        `None` antes do `start()`, e antes do primeiro ``ACK``. É o
        mesmo número que o ``client.latency`` do discord.py (que
        devolve **segundos**) e o ``client.ws.ping`` do discord.js
        (ms) mostram no ``/ping``; aqui em ms, que é a unidade do
        resto da casa.

        Isto **não** é a latência REST — a do `client.api` é medida
        cronometrando uma chamada, como o `/ping` do bot faz, e vem
        em outro campo.
        """
        gateway = self._gateway
        return None if gateway is None else gateway.latency

    @property
    def api(self) -> DiscordAPI:
        """As operações REST, organizadas por recurso.

        Existe desde a construção, não só depois do `start()`: REST e
        Gateway são independentes (ver `docs/decisions/0004`), e um bot
        que só quer consultar a API não precisa de WebSocket.

        Tokens vazios são rejeitados no `start()`, não aqui — `Config`
        é uma declaração de intenções, e nem toda declaração é uma
        aplicação que conecta. Um `api.me()` antes do `start()` com
        token vazio falha com a mensagem certa, que é o comportamento
        esperado.
        """
        return self._api

    @property
    def cache(self) -> ConnectionState:
        """O estado local, alimentado pelo Gateway.

        Existente desde a construção, como o `api`. É o que as pessoas
        chamam de cache, e o tipo `ConnectionState` é o nome honesto do
        que ele é: quem o bot é e o que o Discord já contou.

        Alimentado **antes** dos handlers rodarem, então dentro de um
        `@client.on("message_create")` o `cache.get_member()` já vê a
        mensagem que está sendo processada.

        Incompleto por design. `get_*` devolve `None` para entidade que
        a política não cobre, que o gateway ainda não entregou, ou que
        não existe mais — e `None` desses três é a mesma resposta para
        quem lê, mas `cache.stats` distingue. Um método REST funciona
        igual quando o cache não tem a entidade, sempre que a API
        oficial permitir a operação.

        `config.cache` é a política: começa ligada com `guilds`,
        `channels`, `roles` e `users` — `members` e `messages` são
        opt-in por serem os que crescem com o servidor.
        """
        return self._state

    def on(self, event: str) -> Callable[[EventHandler], EventHandler]:
        """Registra um handler para um evento do Discord.

        O nome aceita as duas formas — ``"MESSAGE_CREATE"`` (como o
        Discord manda) e ``"message_create"`` (snake_case, ver
        `events/names.py`). Os dois chegam ao mesmo handler, que
        recebe o payload **já interpretado**: um `Message` para
        ``MESSAGE_CREATE``, um `Ready` para ``READY``, e assim por
        diante. Eventos sem parser chegam como dict cru.

        Handler que levanta exceção é logado e ignorado — um erro num
        handler não pode derrubar a conexão que está mantendo o bot no
        ar.

        O caminho de baixo nível. O de alto nível é `@event`, que aceita
        `tags` e `once`, e **valida a aridade na importação** (`0025`
        §3). Os dois entregam o payload só (`0031`); aqui a checagem é
        em runtime, porque `client.on` é o caminho antigo e mudar a
        regra dele quebraria o que já funciona.
        """

        def decorator(handler: EventHandler) -> EventHandler:
            self._dispatcher.add(event, handler)
            return handler

        return decorator

    @property
    def commands(self) -> Any:
        """O `CommandRegistry` deste client — o mesmo que os `@command`
        encontraram (`K12`).

        Existe para quem quer inspecionar o que foi registrado, ou
        registrar imperativamente sem o decorator. Com o default
        (registry global), é o registro do processo inteiro.
        """
        return self._registry.commands

    @property
    def responders(self) -> Any:
        """O `ResponderRegistry` deste client, pelo mesmo motivo."""
        return self._registry.responders

    def run(self, token: str) -> None:
        """Sobe o bot e **bloqueia** até o `close()` (K8/K12).

        O caminho curto de um script de produção::

            client = Client(Config(intents=Intents.default()))
            client.run(os.environ["DISCORD_TOKEN"])

        `asyncio.run` por dentro, então levanta `RuntimeError` se o
        thread já tem um loop rodando — aí o caminho é
        `async with Client(...)` + `await client.start()`. A mensagem
        de erro diz isso, porque o `RuntimeError` do `asyncio.run`
        ("cannot be called from a running event loop") sozinho não
        aponta a saída.

        O token entra por aqui em vez de no `Config` porque `Config` é
        congelado — e congelado é de propósito: uma configuração que
        muda no meio do uso derruba o bot inteiro sem avisar. Preenche
        só se estiver vazio: um token já configurado não é substituído
        por acidente quando `run()` é chamado sem querer de outro lugar.

        Ctrl+C encerra **sem traceback**: o `Runner` cancela a tarefa
        principal, o `async with` de `_espera_fechamento` roda o
        shutdown completo nesse cancelamento e só depois o
        `KeyboardInterrupt` sobe daqui — ele é engolido, e o `run()`
        devolve normalmente.
        """
        if not self._config.token:
            self._config = replace(self._config, token=token)
        try:
            asyncio.run(self._espera_fechamento())
        except KeyboardInterrupt:
            log.info("Interrompido (Ctrl+C) — encerrando.")
            return
        except RuntimeError as exc:
            if "running event loop" not in str(exc):
                raise
            raise LifecycleError(
                "run() bloqueia o thread — não pode ser chamado de dentro de um "
                "loop que já existe. Use `async with Client(config)` e "
                "`await client.start()` nesse caso."
            ) from exc

    async def _espera_fechamento(self) -> None:
        """`run()` — conecta, espera o `close()`, desliga.

        O `_parar` é o que distingue isto de um `start()` solto: sem
        ele, o script terminaria no `READY`, fecharia o loop, e o bot
        morreria na primeira mensagem que chegasse. Com ele, o
        `close()` de um handler ou de um signal encerra a espera.
        """
        async with self:
            await self.start()
            await self._parar.wait()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> Any:
        """Cria uma task supervisionada pelo ciclo de vida do cliente.

        Prefira isto a `asyncio.create_task` — tarefas criadas aqui são
        canceladas e aguardadas no `close()`.
        """
        return self._lifecycle.spawn(coro, name=name)

    async def start(self) -> None:
        """Conecta e **devolve quando o `READY` chega**.

        Levanta `ValueError` se os intents privileged pedidos não foram
        habilitados, ou se o token estiver vazio — o erro aparece aqui,
        e não depois de um Identify rejeitado.

        Esperar o `READY` (e não só abrir o socket) é de propósito: um
        `start()` que devolve antes deixa o chamador achando que o bot
        está recebendo eventos quando ainda está no Identify.
        """
        if self._started:
            raise LifecycleError("Client já foi iniciado")
        if self._closed:
            raise LifecycleError("Client já foi fechado e não pode ser reiniciado")

        token = self._config.token
        if not token or not token.strip():
            raise ValueError(
                "Config.token está vazio — pegue o token do painel de "
                "desenvolvedor do Discord e passe em `Config(token=...)`. "
                "Nunca comente o token no código."
            )

        self._config.intents.validate(self._config.enabled_intents)
        self._started = True

        # Handler de exceção do loop, para o que escapa de task e de
        # callback (`0026` §10). Sem isto, um `Future got exception
        # retrieved` fica no stderr do processo em texto puro, sem
        # contexto de qual bot, qual evento — e o padrão do asyncio é
        # **imprimir e seguir**, que é como um erro some.
        loop = asyncio.get_running_loop()
        self._loop = loop
        loop.set_exception_handler(self._trata_excecao_loop)

        # Comandos que o decorator não escopou vão para o default do
        # `Config` (`0028` §2). É aqui, e não no `__init__`: no `__init__`
        # o `bootstrap` ainda não rodou, e a ordem de import passaria a
        # decidir escopo de registro.
        self._registry.commands.reescopiar(self._config.commands.guilds)

        self._gateway = self._build_gateway(token)
        log.info("Conectando ao Gateway (intents=%s)", self._config.intents.to_payload())

        # Supervisada pelo Lifecycle, mas pelo **runner**: ver abaixo.
        task = self.spawn(self._gateway_runner(), name="kryncord.gateway")
        await self._await_ready(task)

    async def _gateway_runner(self) -> None:
        """Roda o Gateway, guardando a falha em vez de propagá-la.

        Três coisas aconteceriam se `start()` fizesse `spawn(gateway.connect())`
        direto, e as três seriam ruins:

        * O `TaskGroup` do `Lifecycle` **cancela a task pai** quando uma
          filha falha (`asyncio/taskgroups.py`, `_on_task_done`). A task
          pai aqui é o `start()` de quem usa a biblioteca — ele receberia
          um `CancelledError` sem explicação, no lugar do
          `FatalGatewayError` que diz o que corrigir.
        * A mesma exceção subiria de novo no `__aexit__`, embrulhada num
          `ExceptionGroup`. O usuário veria o erro duas vezes, e a
          segunda no formato menos legível.
        * O `connect()` já trata sozinho tudo que é recuperável. O que
          sobra é fatal, e fatal é uma ocorrência **única** que o
          `start()` reporta — não um evento que o shutdown repete.

        Guardar a exceção aqui faz o runner terminar com sucesso, o
        `TaskGroup` fica tranquilo, e o `start()` escolhe quando e como
        dizer o que houve.
        """
        gateway = self._gateway
        assert gateway is not None, "runner só existe depois do gateway ser construído"
        try:
            await gateway.connect()
        except asyncio.CancelledError:
            # Cancelamento é pedido do `close()`, não uma falha do
            # Gateway. Deixar passar sem registrar evita log enganoso
            # no meio de um shutdown normal.
            raise
        except BaseException as exc:
            self._gateway_failure = exc
            log.error("Gateway encerrou por falha fatal: %r", exc)

    async def _await_ready(self, task: asyncio.Task[None]) -> None:
        """Espera o `READY`, ou o Gateway morrer tentando.

        Sem esta disputa, uma falha fatal no Identify deixaria o `start()`
        esperando um evento que nunca vem — o processo ficaria preso num
        `await` que nunca resolve, que é a forma mais cara de um bot não
        ligar.
        """
        ready = asyncio.ensure_future(self._ready.wait())
        try:
            done, _ = await asyncio.wait({task, ready}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            ready.cancel()

        if task in done:
            # O runner guarda a falha em vez de levantar: o `TaskGroup`
            # cancelaria o chamador e o erro subiria de novo no shutdown.
            if self._gateway_failure is not None:
                raise self._gateway_failure
            raise GatewayError(
                "A conexão com o Gateway terminou antes do `READY`. "
                "Veja os logs acima — o motivo costuma estar lá."
            )

    async def close(self) -> None:
        """Fecha a conexão, o pool HTTP e cancela as tarefas supervisionadas.

        Idempotente: chamar duas vezes não é erro.
        """
        if self._closed:
            return
        self._closed = True
        self._started = False
        self._ready.clear()
        self._parar.set()

        await self._shutdown(None, None, None)
        log.info("Cliente encerrado")

    async def _shutdown(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Fecha Gateway, tasks, Lifecycle e HTTP, nessa ordem.

        Gateway primeiro: sem isto, o `connect()` ficaria esperando um
        `recv()` que ninguém vai acordar, e o cancelamento viraria uma
        exceção no meio do shutdown.

        As tasks de `ctx.spawn` em seguida, e **antes** do Lifecycle:
        uma corrotina disparada por um handler pode estar no meio de um
        `await` no REST, e o cancelamento dela tem que acontecer com o
        pool ainda vivo — senão o erro que sobe é de transporte, não o
        `CancelledError` que o chamador espera.

        HTTP por último, pelo mesmo motivo.

        O `loop.set_exception_handler` é restaurado no fim: um handler
        de exceção que sobrevive ao client apontaria para um bot que já
        não existe no log do próximo handler do processo.
        """
        gateway = self._gateway
        if gateway is not None:
            await gateway.close()

        await self._tasks.cancela_todas()

        await self._lifecycle.__aexit__(exc_type, exc, tb)

        await self._rest.aclose()

        loop = self._loop
        if loop is not None:
            loop.set_exception_handler(None)
            self._loop = None

    async def wait_until_ready(self) -> None:
        """Bloqueia até o Gateway estar pronto.

        Para quem liga o bot em background e quer só esperar.
        """
        await self._ready.wait()

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
        """Puxa os membros de uma guild (op 8) — payloads crus.

        A soma dos `GUILD_MEMBERS_CHUNK` do pedido, entregue quando os
        chunks terminarem. Com uma shard só, a rota é sempre a mesma;
        quando houver várias, a shard dona da guild é
        `(guild_id >> 22) % shards` — mesma conta do discord.js.
        """
        gateway = self._gateway
        if gateway is None:
            raise LifecycleError(
                "`request_guild_members` precisa do Gateway ligado — chame `start()` antes."
            )
        return await gateway.request_guild_members(
            guild_id,
            query=query,
            limit=limit,
            presences=presences,
            user_ids=user_ids,
            nonce=nonce,
            timeout=timeout,
        )

    def _build_gateway(self, token: str) -> GatewayClient:
        return GatewayClient(
            token=token,
            intents=self._config.intents.to_payload(),
            transport_factory=self._transport_factory,
            config=self._config.gateway,
            session_store=self._session_store,
            compression=self._compression,
            on_event=self.dispatch,
        )

    def _trata_excecao_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        context: dict[str, Any],
    ) -> None:
        """Exceção que o asyncio não tinha para quem logar.

        O padrão do loop é `print` no `stderr`, fora do logging da
        biblioteca — e aí o erro aparece sem o resto do contexto do bot
        (qual sessão, qual intenção, qual handler), no texto puro do
        processo. Este handler aplica o mesmo critério de sempre: erro
        vai para o log, com a pilha.

        `context["exception"]` pode faltar (`call_soon` que levantou, por
        exemplo): aí loga só a `message`, que é o que existe.
        """
        exc = context.get("exception")
        mensagem = context.get("message", context)
        if exc is not None:
            log.error("Exceção não tratada no event loop: %s", mensagem, exc_info=exc)
        else:
            log.error("Erro no event loop: %s", mensagem)

    async def dispatch(self, name: str, data: Any) -> None:
        """Roda as cinco etapas de um dispatch, na ordem do `0025` §4.

        1. **instantânea** — lê do cache o que o updater vai sobrescrever.
           Ler depois daria `old == new` para sempre, e o handler
           imprimiria a mesma coisa duas vezes procurando a diferença.
        2. **updater** — `EventUpdater.apply`, o cache (`0008`).
        3. **ready** — destrava `start()` em `READY`/`RESUMED`.
        4. **roteamento** — `INTERACTION_CREATE` vai aos registries de
           comando e responder (`0026`), **antes** dos `@event`.
        5. **handlers** — o despacho, com os argumentos montados.

        Ordem não é detalhe: um handler que pergunta `get_member()` tem
        que ver o que este evento acabou de entregar. O contrário faria
        todo handler ler estado defasado por um evento, e é o pior tipo
        de bug: aparece só sob carga, e desaparece quando alguém para o
        bot para olhar.

        O `old` e o `estado` nascem aqui, e não no dispatcher: o
        `events/` não conhece o `state/`, e o dicionário de contexto é
        **um só por dispatch** — é o que faz a etapa 4 e os handlers de
        `@event("interaction_create")` carregarem o mesmo estado sem
        serem o mesmo objeto.

        É também o ponto de entrada público: um teste injeta
        `await client.dispatch("MESSAGE_CREATE", {...})` e o pipeline
        inteiro roda sem abrir socket.
        """
        estado: dict[str, Any] = {}
        old = instantanea(name, data, self._state)
        self._update_cache(name, data)

        if name.upper() in ("READY", "RESUMED"):
            self._ready.set()

        await self._roteia(name, data, estado)

        opcoes = self._config.events
        cadeia = (opcoes.middleware,) if opcoes.middleware is not None else ()
        await self._dispatcher.dispatch(
            name,
            data,
            old=old,
            state=estado,
            client=self,
            mode=opcoes.dispatch_mode,
            middleware=cadeia,
            on_error=opcoes.on_error,
        )

    async def _roteia(self, name: str, data: Any, estado: dict[str, Any]) -> None:
        """Etapa 4 — `INTERACTION_CREATE` aos registries, antes dos `@event`.

        Tudo que não é interação passa direto: é um `if`, e o custo é o
        de comparação. Separar em função é para a ordem do `0025` §4
        ficar visível no corpo do `dispatch`, e não aninhada dentro dele.

        O import é **adiado** porque o roteamento é o Bloco 8 (`0026`): ele
        depende de `CommandInstance.run`, que ainda não existe. Depois de
        lá, sobe para o topo — mas adiado não muda nada em runtime, e
        evita um `ImportError` num módulo que este bloco ainda não usa.
        """
        if name.upper() != "INTERACTION_CREATE":
            return
        if not isinstance(data, Mapping):
            log.debug("INTERACTION_CREATE sem objeto — ignorando roteamento")
            return

        from kryncord.interactions.dispatch import dispatch_interaction

        await dispatch_interaction(
            data,
            self._api,
            registry=self._registry,
            client=self,
            state=estado,
            cache=self._state,
            tasks=self._tasks,
            esperas=self._esperas,
            command_options=self._config.commands,
            responder_options=self._config.responders,
        )

    def _update_cache(self, name: str, data: Any) -> None:
        """Aplica o evento no cache, engolindo o erro.

        Contrato dos handlers, aplicado ao cache: exceção aqui é logada
        e o resto do dispatch segue. Um payload que não deu para
        interpretar não pode derrubar a conexão que está mantendo o bot
        no ar.

        `CancelledError` não é engolido — é `BaseException`, e sairia
        pelo `except Exception` de propósito nenhum.
        """
        try:
            self._updater.apply(name, data)
        except Exception:
            log.exception("Cache não aplicou %s; seguindo sem ele", name)

    async def __aenter__(self) -> Self:
        await self._lifecycle.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Não delegar para `close()`: ela fecha o Lifecycle com
        # (None, None, None), e a segunda chamada com a exceção real vira
        # no-op — o TaskGroup nunca veria o erro.
        if not self._closed:
            self._closed = True
            self._started = False
            await self._shutdown(exc_type, exc, tb)
            log.info("Cliente encerrado")
