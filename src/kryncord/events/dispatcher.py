"""Converte payload cru em objeto, e objeto em chamada de handler.

O Gateway entrega ``("MESSAGE_CREATE", {...})``. O usuário quer
``message.content``. Este módulo é o meio — e o meio é onde a maior
parte das decisões mora.

**Política de execução: sequencial, em ordem de registro.** A
alternativa — uma task por handler — daria ordem imprevisível entre
handlers do mesmo evento, e imprevisibilidade num dispatch de mensagem
é como se fabrica bug de corrida. Quem quer paralelismo usa
`Client.spawn` dentro do handler, e aí escolhe a ordem.

**Exceção é isolada.** Um handler que levanta é logado e o próximo
roda. Derrubar a conexão por causa de um ``KeyError`` num log seria
trocar um evento perdido por um bot fora do ar — e o bot fora do ar
perde *todos* os eventos.

**Cancelamento propaga.** Diferente de exceção, não é erro: cancelar um
dispatch é o `close()` mandando o bot desligar, e engolir isso deixaria
tarefa pendurada.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.errors import BlockHandlers
from kryncord.events.context import EventContext
from kryncord.events.names import normalize_event_name
from kryncord.events.payloads import monta_args, usa_parsed
from kryncord.internal.compose import block
from kryncord.logging import get_logger
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.message import Message
from kryncord.models.partial import PartialChannel, PartialGuild, PartialMessage
from kryncord.models.ready import Ready
from kryncord.models.typing import TypingStart
from kryncord.models.voice import VoiceState

log = get_logger("events")

#: Um parser: do payload cru do Discord para o modelo. `None` significa
#: "este evento chega cru, a biblioteca não o interpreta".
Parser = Callable[[Mapping[str, Any]], Any]

#: Um handler de evento. **Tem que ser `async`** — o mesmo contrato do
#: `GatewayClient`. Aceitar função síncrona seria convidar alguém a
#: bloquear o event loop dentro de um handler, e o sintoma (bot parado,
#: sem erro) é dos piores de se diagnosticar. `await` de uma função
#: síncrona ainda falha alto, com `TypeError`, que é o erro certo.
EventHandler = Callable[[Any], Awaitable[Any]]

#: Uma middleware de evento — `fn(ctx, block)`, com `block` sempre no
#: segundo lugar (`0017`). Assíncrona, obrigatoriamente.
EventMiddleware = Callable[[Any, Any], Awaitable[None]]

#: `fn(ctx, error)` — mesma ordem nos três tipos, definida pelo
#: `ErrorHandler` do `0010`. A ideia 10 §7 escrevia `(error, ctx)`; a
#: ordem que prevaleceu é a do alias que o `Config` já declara.
ErrorHandler = Callable[[Any, BaseException], Awaitable[None]]


#: O que cada evento vira antes de chegar no handler.
#: O nome é o do dispatch, em maiúsculas, como o Discord manda.
#:
#: **`REGISTRY` e `EVENT_PAYLOADS` são camadas diferentes** (`0020`):
#: este mapa decide o que o parser entrega (um objeto), a tabela de
#: `events/payloads.py` decide a tupla de argumentos do handler. Para
#: `message_delete` o parser nem entra — o argumento é o `id` do payload
#: mais o `old` do cache.
REGISTRY: dict[str, Parser | None] = {
    "READY": Ready.from_payload,
    "MESSAGE_CREATE": Message.from_payload,
    "MESSAGE_UPDATE": Message.from_payload,
    "MESSAGE_DELETE": PartialMessage.from_payload,
    "GUILD_CREATE": Guild.from_payload,
    "GUILD_UPDATE": Guild.from_payload,
    "GUILD_DELETE": PartialGuild.from_payload,
    "CHANNEL_CREATE": Channel.from_payload,
    "CHANNEL_UPDATE": Channel.from_payload,
    "CHANNEL_DELETE": PartialChannel.from_payload,
    "INTERACTION_CREATE": Interaction.from_payload,
    "TYPING_START": TypingStart.from_payload,
    "VOICE_STATE_UPDATE": VoiceState.from_payload,
}


@dataclass(frozen=True, slots=True)
class EventEntry:
    """Um handler registrado, com o que ele prometeu.

    `handler` é a função; o resto é o contrato do registro: como o
    despacho deve chamá-lo e o que a middleware pode bloquear.
    """

    handler: EventHandler

    #: Identificador humano — aparece nos logs e no `verbose`. Default:
    #: o ``__qualname__`` da função (`ideia 10` §1).
    label: str = ""

    #: Tags que a middleware de evento pode bloquear (`ideia 10` §4).
    #: Só eventos têm tags na 1.0 (`0017`).
    tags: tuple[str, ...] = ()

    #: Se o handler some depois de rodar. Forçado em `ready` (`ideia 10`
    #: §3): o anúncio de sessão acontece uma vez, e um `ready` disparando
    #: duas vezes é como um bot "conecta" duas vezes.
    once: bool = False

    #: Se recebe `EventContext` na frente dos argumentos. `@event` sim,
    #: `client.on` não (`0020`) — a única diferença entre os dois
    #: caminhos de registro.
    with_context: bool = False


def _is_async_callable(fn: Any) -> bool:
    """Se `fn` é algo que devolve coroutine quando chamado.

    `inspect.iscoroutinefunction` sozinho não cobre tudo que é legítimo:
    um objeto com `async def __call__` responde `False` nele, porque a
    assinatura está no `__call__`, e não no objeto. `functools.partial`
    de uma função assíncrona também precisa do unwrap — e o `inspect`
    já faz esse.

    O caso que não cobre (função síncrona que devolve coroutine) é raro
    o suficiente para valer o `TypeError` em vez de um `try` no
    dispatch.
    """
    if inspect.iscoroutinefunction(fn):
        return True
    try:
        return inspect.iscoroutinefunction(fn.__call__)
    except AttributeError:
        # Objeto sem `__call__` próprio — não é chamável de forma
        # assíncrona, e o `dispatch` daria `TypeError` no `await`.
        return False


class EventDispatcher:
    """Guarda handlers e entrega eventos já interpretados."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        # Chave normalizada: `on("MESSAGE_CREATE")` e
        # `on("message_create")` caem na mesma gaveta.
        self._handlers: dict[str, list[EventEntry]] = defaultdict(list)

    def add(
        self,
        event: str,
        handler: EventHandler,
        *,
        label: str = "",
        tags: Iterable[str] = (),
        once: bool = False,
        with_context: bool = False,
    ) -> None:
        """Registra um handler. Aceita ``"MESSAGE_CREATE"`` ou
        ``"message_create"`` — os dois chegam ao mesmo lugar.

        Levanta `TypeError` se o handler não for assíncrono. Validar
        aqui, uma vez, é melhor que descobrir no primeiro evento: sem
        isso o `await` falharia toda vez, o dispatcher logaria e
        ignoraria, e o sintoma (handler que nunca roda, sem erro
        visível) é dos piores de diagnosticar.
        """
        if not _is_async_callable(handler):
            raise TypeError(
                f"Handler de {event!r} tem que ser `async def`. Recebi "
                f"{handler!r}. Função síncrona bloquearia o event loop "
                "dentro do dispatch."
            )
        self._handlers[normalize_event_name(event)].append(
            EventEntry(
                handler=handler,
                label=label or getattr(handler, "__qualname__", repr(handler)),
                tags=tuple(tags),
                once=once,
                with_context=with_context,
            )
        )

    def remove(self, event: str, handler: EventHandler) -> bool:
        """Tira um handler. `False` se ele não estava registrado.

        É o caminho do `once=True` depois do primeiro dispatch, e o de
        quem quer desligar um observador sem reiniciar o bot.
        """
        chave = normalize_event_name(event)
        entradas = self._handlers.get(chave)
        if not entradas:
            return False
        for indice, entrada in enumerate(entradas):
            if entrada.handler is handler:
                del entradas[indice]
                return True
        return False

    def handlers_for(self, event: str) -> tuple[EventHandler, ...]:
        """Os handlers registrados para um evento, em ordem de registro.

        Devolve as **funções**, não as entradas: é o que quem inspeciona
        quer (`len`, comparação de identidade), e manter o formato
        preserva o que o `0006` já prometia.
        """
        return tuple(entrada.handler for entrada in self._entradas_de(event))

    @property
    def known_events(self) -> tuple[str, ...]:
        """Eventos que têm parser — os que a biblioteca interpreta."""
        return tuple(sorted(name for name, parser in REGISTRY.items() if parser is not None))

    async def dispatch(
        self,
        name: str,
        data: Any,
        *,
        old: Any = None,
        state: dict[str, Any] | None = None,
        client: Any = None,
        mode: str = "sequential",
        middleware: Iterable[EventMiddleware] = (),
        on_error: ErrorHandler | None = None,
    ) -> None:
        """Interpreta o payload, monta os argumentos e chama os handlers.

        `data` pode vir como `dict` (caso normal) ou já como modelo
        (quando o teste ou o Gateway entrega interpretado). Passar
        direto evita que o parser rode duas vezes sobre o mesmo objeto.

        `old` é a instantânea lida pelo `Client` **antes** do updater
        (`0025` §4) — este módulo não toca no cache, porque o `events/`
        não conhece o `state/`.
        """
        nome = normalize_event_name(name)
        parsed = self._parse(name, data) if usa_parsed(name) else data
        args = list(monta_args(nome, parsed, old, data))
        ctx = EventContext(nome, args, client=client, state=state)

        entradas = self._entradas_de(nome)
        if not entradas and not middleware:
            return

        vivas = await self._prepara(nome, ctx, entradas, tuple(middleware), on_error)
        if vivas is None:
            return
        if not vivas:
            return

        if mode == "concurrent":
            await self._concurrent(nome, ctx, vivas, on_error)
        else:
            await self._sequential(nome, ctx, vivas, on_error)

    # ------------------------------------------------------------------
    # Cadeia de execução
    # ------------------------------------------------------------------

    async def _prepara(
        self,
        nome: str,
        ctx: EventContext,
        entradas: tuple[EventEntry, ...],
        cadeia: tuple[EventMiddleware, ...],
        on_error: ErrorHandler | None,
    ) -> tuple[EventEntry, ...] | None:
        """Roda a middleware e devolve quem pode despachar.

        `None` é "não há o que despachar" — middleware levantou algo que
        não é `BlockHandlers`, e o `0017` manda o `on_error` rodar e a
        cadeia inteira parar. Uma tupla vazia é outra coisa: foi o
        `block()` que tirou todos, e aí o despacho termina em silêncio,
        sem erro — porque bloquear é tratamento.

        Dois caminhos, dois significados, e confundi-los faria um
        bloqueio legítimo virar "falha" no `on_error`.

        Cancelamento propaga nos dois — é o `close()` mandando desligar,
        não um erro da middleware.
        """
        bloqueio: BlockHandlers | None = None
        for item in cadeia:
            try:
                await item(ctx, block)
            except BlockHandlers as exc:
                bloqueio = exc
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._erro(on_error, ctx, exc)
                return None

        if bloqueio is None:
            return entradas
        return self._vivas_por_tag(entradas, bloqueio)

    @staticmethod
    def _vivas_por_tag(
        entradas: tuple[EventEntry, ...],
        bloqueio: BlockHandlers,
    ) -> tuple[EventEntry, ...]:
        """O que a middleware deixou de fora.

        `block()` sem argumentos tira todos; `block("morning")` tira só
        os que tenham **alguma** daquelas tags. Handlers **sem tag
        nenhuma** passam sempre — é o que a ideia 10 §4 escreve, e o que
        torna as tags úteis: quem rotulou é quem aceitou ser filtrado.
        """
        if not bloqueio.tags:
            return ()
        bloqueadas = set(bloqueio.tags)
        return tuple(entrada for entrada in entradas if not (bloqueadas & set(entrada.tags)))

    async def _sequential(
        self,
        nome: str,
        ctx: EventContext,
        entradas: tuple[EventEntry, ...],
        on_error: ErrorHandler | None,
    ) -> None:
        """Um `await` por vez, na ordem de registro.

        A mutação de `ctx.args` propaga porque o `*ctx.args` é lido a
        cada chamada, e a lista é a mesma — é o recurso documentado da
        ideia 10 §8, e a razão de o `sequential` ser o default.
        """
        for entrada in entradas:
            try:
                await self._chama(entrada, ctx)
            except BlockHandlers:
                # `block()` chamado **dentro** de um handler: aborta os
                # que faltam, como em middleware. `on_error` não roda
                # pela mesma razão do `0017` — é tratamento.
                log.debug("Handler %s bloqueou os seguintes de %s", entrada.label, nome)
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._erro(on_error, ctx, exc)

    async def _concurrent(
        self,
        nome: str,
        ctx: EventContext,
        entradas: tuple[EventEntry, ...],
        on_error: ErrorHandler | None,
    ) -> None:
        """Um `TaskGroup` por dispatch, **esperando todos**.

        A ideia 10 §5 dizia "o dispatcher não espera"; o `0025` §8
        decidiu o contrário, e a razão é o cancelamento: um `TaskGroup`
        é filho do dispatch, que é filho do `Client`, então o `close()`
        alcança as tasks sem código novo.

        Quem não quer esperar usa `ctx.spawn` — que é o que o `TaskGroup`
        do `0012` existe para não ser.
        """
        async with asyncio.TaskGroup() as grupo:
            for entrada in entradas:
                # Cada task engole a própria exceção. Uma deixando
                # escapar cancelaria o pai — é como o `TaskGroup` do
                # CPython funciona, e um log de um handler nunca pode
                # derrubar o bot (`0006`).
                grupo.create_task(self._guardada(entrada, ctx, on_error))

    async def _guardada(
        self,
        entrada: EventEntry,
        ctx: EventContext,
        on_error: ErrorHandler | None,
    ) -> None:
        """Uma task do modo `concurrent` — exceção vai para o `on_error`."""
        try:
            await self._chama(entrada, ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._erro(on_error, ctx, exc)

    async def _chama(self, entrada: EventEntry, ctx: EventContext) -> None:
        """Chama um handler com o que ele prometeu no registro.

        `*ctx.args` lê a **lista viva** neste momento — é o que faz a
        mutação da middleware ter efeito nos handlers seguintes.

        `once=True` é consumido **aqui**, depois do `await` bem sucedido:
        é o único lugar onde "rodou" é um fato, e não uma intenção. Um
        handler que levantou não rodou — ele falhou — e tirá-lo da lista
        transformaria um `on_error` transitório num handler morto para
        sempre, sem ninguém ter visto o erro duas vezes.
        """
        if entrada.with_context:
            await entrada.handler(ctx, *ctx.args)
        else:
            await entrada.handler(*ctx.args)
        if entrada.once:
            self.remove(ctx.name, entrada.handler)

    async def _erro(
        self,
        on_error: ErrorHandler | None,
        ctx: EventContext,
        exc: BaseException,
    ) -> None:
        """O `on_error` do evento, ou o log quando não há um.

        `on_error` que também falha é logado e engolido: nunca uma
        exceção sem tratador no meio de um despacho (`0017`).
        """
        if on_error is None:
            log.error("Erro no handler do evento %s", ctx.name, exc_info=exc)
            return
        try:
            await on_error(ctx, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("on_error do evento %s também falhou", ctx.name)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _entradas_de(self, event: str) -> tuple[EventEntry, ...]:
        """As entradas de um evento, em ordem de registro.

        Cópia de propósito: um handler que registra outro durante o
        dispatch não muda a lista que está sendo percorrida.
        """
        return tuple(self._handlers.get(normalize_event_name(event), ()))

    def _parse(self, name: str, data: Any) -> Any:
        """Interpreta o payload, ou devolve cru se não houver parser.

        Tolerante de propósito. Três caminhos entregam o payload cru,
        e nenhum deles é exceção:

        * O evento não tem parser — a biblioteca não finge que entende
          o que ainda não interpretou.
        * O parser devolve `None` — o payload não tinha o campo sem o
          qual o objeto não significa nada (o ``id`` de um `Message`).
          Entregar cru é mais honesto que entregar um objeto inútil.
        * O parser levantou — anomalia do Discord, e punir o evento
          inteiro por isso perderia os handlers que só querem o dict.

        O payload cru entra na **posição** do modelo, nunca em mais ou
        menos argumentos (`0025` §7): aridade que muda no meio do
        dispatch vira `TypeError` mascarando o erro verdadeiro.
        """
        parser = REGISTRY.get(name.upper())
        if parser is None or data is None:
            return data
        if not isinstance(data, Mapping):
            log.debug("Payload de %s não é objeto: %r", name, type(data).__name__)
            return data
        try:
            parsed = parser(data)
        except Exception:
            log.exception("Falha ao interpretar payload de %s — entregando cru", name)
            return data
        if parsed is None:
            log.debug("Payload de %s sem o campo essencial — entregando cru", name)
            return data
        return parsed
