"""Despacho de responders — do clique ao handler, com tudo no meio.

A ordem é a da ideia 07 §7: achar pelo roteador, aplicar a política de
cache, rodar middleware, injetar params convertidos, executar. Middleware
que chama ``block()`` para tudo — inclusive o `on_not_found` (0017
decidiu; a ideia 11 §"regra importante" dizia o contrário e foi
sobrescrita).

`emit_responder` é o mesmo caminho, sem gateway: roteador (0013 — sem
lookup exato paralelo), com dois guardas da ideia 09 — profundidade e
re-emissão.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from typing import Any

from kryncord.enums import ResponderType
from kryncord.errors import BlockHandlers, DispatchError
from kryncord.interactions.response import InteractionContext
from kryncord.internal.compose import block, compose
from kryncord.logging import get_logger
from kryncord.models.interaction import Interaction
from kryncord.responders.context import ResponderContext
from kryncord.responders.converters import converte, plano_de, recebe_params_dict
from kryncord.responders.params import Params

_log = get_logger(__name__)

#: Quantos `emit_responder` aninhados um dispatch suporta (ideia 09 §5).
#: Acima disso é loop — e loop aqui é loop infinito de verdade.
MAX_PROFUNDIDADE = 5


#: A cadeia de middleware é compartilhada pelos três despachos, então
#: `block` e `compose` vivem em `internal/compose.py`. Este módulo
#: continua exportando-os — é por aqui que a raiz os entrega, e trocar o
#: caminho de import quebraria quem já importa daqui.
__all__ = [
    "MAX_PROFUNDIDADE",
    "Esperas",
    "block",
    "compose",
    "dispatch_responder",
    "emit_responder",
]


class Esperas:
    """As esperas de `await_responder` — single-shot, por `custom_id`.

    Não é collector: quem espera, espera **um** id, uma vez. O
    `@responder` correspondente roda normal — a espera observa o
    resultado em vez de consumir o dispatch (0023, R3).
    """

    __slots__ = ("_futuros",)

    def __init__(self) -> None:
        self._futuros: dict[str, list[asyncio.Future[Any]]] = {}

    def registra(self, custom_id: str, *, timeout: float = 300.0) -> asyncio.Future[Any]:
        futuro: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._futuros.setdefault(custom_id, []).append(futuro)
        return futuro

    def resolve(self, custom_id: str, valor: Any) -> bool:
        """Entrega o resultado às esperas deste id. `False` se ninguém esperava."""
        pendentes = self._futuros.pop(custom_id, [])
        if not pendentes:
            return False
        for futuro in pendentes:
            if not futuro.done():
                futuro.set_result(valor)
        return True

    async def cancela_todas(self) -> None:
        """O `aclose` do client chama — espera órfã é task órfã."""
        for pendentes in self._futuros.values():
            for futuro in pendentes:
                if not futuro.done():
                    futuro.cancel()
        self._futuros.clear()


# ----------------------------------------------------------------------
# Despacho
# ----------------------------------------------------------------------


async def dispatch_responder(
    interaction: Interaction,
    api: Any,
    *,
    registry: Any,
    client: Any = None,
    tasks: Any = None,
    esperas: Esperas | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    on_not_found: Callable[..., Any] | None = None,
    on_error: Callable[..., Any] | None = None,
    state: dict[str, Any] | None = None,
) -> bool:
    """Roteia uma interação de componente/modal ao responder.

    `True` se um responder atendeu (middleware incluída); `False` se
    ninguém — e aí o `on_not_found` já rodou, se existir.

    O tipo de resposta certo quando ninguém atende é o `on_not_found`
    decidir — inclusive não responder. Um "isso não foi configurado"
    automático na cara do usuário piora o bot que está no meio de um
    deploy.
    """
    interaction_ctx = InteractionContext(interaction, api)
    custom_id = interaction.custom_id
    tipo = _tipo_de(interaction)

    if custom_id is None or tipo is None:
        return False

    achado = registry.match(custom_id, tipo)
    if achado is None or not _cache_permite(achado.entrada.cache, interaction, client):
        if on_not_found is not None:
            # O mesmo `state` do handler que não existiu: middleware que
            # rodou antes já pode ter escrito nele, e o `on_not_found`
            # tem que enxergar o que a cadeia anterior deixou (`0026` §D6).
            ctx = ResponderContext(
                interaction_ctx,
                client=client,
                tasks=tasks,
                esperas=esperas,
                state=state,
            )
            await _chama(on_not_found, ctx)
        return False

    ctx = ResponderContext(
        interaction_ctx,
        params=achado.params,
        client=client,
        tasks=tasks,
        esperas=esperas,
        state=state,
    )
    cademia = (*middleware, *achado.entrada.middleware)

    try:
        for m in cademia:
            await m(ctx, block)
        resultado = await _invoca(achado.entrada.handler, achado.entrada, ctx, achado.params)
    except BlockHandlers:
        #: Middleware respondeu e parou — o clique foi atendido.
        return True
    except Exception as exc:
        await _erro(exc, ctx, on_error)
        return True

    if esperas is not None:
        esperas.resolve(custom_id, resultado)
    return True


async def emit_responder(
    custom_id: str,
    ctx: ResponderContext,
    *,
    registry: Any = None,
    params: Mapping[str, str] | None = None,
    force: bool = False,
) -> bool:
    """Dispara um responder programaticamente. `False` se ninguém atende.

    Mesmo roteador do dispatch (0013) — id literal casa como rota sem
    params, e lookup exato paralelo seria um segundo caminho para
    testar.

    Dois guardas da ideia 09, ambos `DispatchError`:

    - **re-emissão**: o mesmo `custom_id` na mesma interação, a menos
      que `force=True`. Re-emitir sem querer é loop à primeira vista;
    - **profundidade**: mais de `MAX_PROFUNDIDADE` aninhados é loop de
      verdade, e o `force=True` não abre — abrir seria o próprio loop.

    Não chama `on_not_found`: chamada programática não é "isso não foi
    configurado ainda", e mostrar aviso de usuário final por id que
    veio do nosso código é expor erro que não é erro (K10).
    """
    reg = registry if registry is not None else _registry_global()
    dono = ctx.interaction_context

    if not force and custom_id in dono.emitidos:
        raise DispatchError(
            f"{custom_id!r} já emitido nesta interação — re-emitir sem querer é "
            f"loop. Se quer rodar de novo de propósito, use force=True."
        )

    tipo = _tipo_de(ctx.interaction)
    achado = reg.match(custom_id, tipo) if tipo is not None else None
    if achado is None:
        _log.debug("emit_responder: ninguém atende %r", custom_id)
        return False

    dono.emitidos.add(custom_id)
    dono.profundidade += 1
    if dono.profundidade > MAX_PROFUNDIDADE:
        dono.profundidade -= 1
        raise DispatchError(
            f"emit_responder aninhado além de {MAX_PROFUNDIDADE} — um responder "
            f"emitindo a si mesmo (ou uma cadeia que fecha em círculo). O guard "
            f"existe porque isso aqui não terminaria nunca."
        )

    _log.debug("emit_responder: %s (origem: código)", custom_id)
    novo = ResponderContext(
        ctx.interaction_context,
        params=params if params is not None else achado.params,
        client=ctx.client,
        tasks=ctx._tasks,
        esperas=ctx._esperas,
    )
    try:
        for m in achado.entrada.middleware:
            await m(novo, block)
        #: O retorno é "encontrei e executei" (ideia 09 §2) — o que o
        #: handler devolveu é do chamador, não daqui. `bool(retorno)`
        #: aqui transformaria `return None` em "ninguém atendeu".
        await _invoca(achado.entrada.handler, achado.entrada, novo, novo.params)
        return True
    finally:
        dono.profundidade -= 1


# ----------------------------------------------------------------------
# Interno
# ----------------------------------------------------------------------


def _tipo_de(interaction: Interaction) -> ResponderType | None:
    try:
        data = interaction.data or {}
        return ResponderType.de_interacao(interaction.type, data.get("component_type"))
    except ValueError:
        return None


def _cache_permite(politica: str, interaction: Interaction, client: Any) -> bool:
    """`cache="cached"`/`"fresh"` contra o cache de mensagens.

    Sem `client`, `cached` nunca dispara e `fresh` sempre — é a leitura
    honesta de um cache que não existe: "está no cache" é falso.
    """
    if politica == "any":
        return True
    bruto = (interaction.raw or {}).get("message")
    mensagem_id = bruto.get("id") if isinstance(bruto, Mapping) else None
    cache = getattr(client, "cache", None) if client is not None else None
    if cache is None or mensagem_id is None:
        return politica == "fresh"
    no_cache = cache.get_message(mensagem_id) is not None
    return no_cache if politica == "cached" else not no_cache


async def _invoca(
    handler: Callable[..., Any],
    entrada: Any,
    ctx: ResponderContext,
    raw: Mapping[str, str],
) -> Any:
    """Chama o handler com params convertidos, na forma que ele pediu.

    Três formas, uma chamada:

    - ``fn(ctx, *args)`` — recebe só o contexto (K9);
    - ``fn(ctx, params)`` — o dict cru;
    - ``fn(ctx, a: T, b: U)`` — convertidos pela anotação, com `parse=`
      vencendo por cima (0014).
    """
    if recebe_params_dict(handler, entrada.rota):
        return await _chama(handler, ctx, params=Params(raw))

    kwargs: dict[str, Any] = {}
    for nome, conversor, _opcional, tem_default in plano_de(handler, entrada.rota):
        if nome not in raw:
            if tem_default:
                continue
            #: Sem default e sem valor: o param era opcional na rota
            #: (`?:`) e o segmento não veio. `None` é o que a anotação
            #: `T | None` promete.
            kwargs[nome] = None
            continue
        kwargs[nome] = await converte(conversor, raw[nome], ctx, nome)

    if entrada.parse is not None:
        transformado = entrada.parse(raw, ctx)
        if inspect.iscoroutine(transformado):
            transformado = await transformado
        if isinstance(transformado, Mapping):
            #: `parse=` vence o valor convertido; o que ele não toca,
            #: fica convertido como estava (0014).
            kwargs.update(transformado)

    return await _chama(handler, ctx, **kwargs)


async def _chama(fn: Callable[..., Any], ctx: ResponderContext, **kwargs: Any) -> Any:
    if not inspect.iscoroutinefunction(fn):
        raise DispatchError(
            f"handler {getattr(fn, '__name__', fn)!r} não é async — handler de "
            f"responder sempre é; o que ele chama pode bloquear a rede inteira"
        )
    return await fn(ctx, **kwargs)


async def _erro(exc: BaseException, ctx: ResponderContext, on_error: Any) -> None:
    """`on_error` decide; o default loga e responde efêmera (0017)."""
    if on_error is not None:
        await on_error(ctx, exc)
        return

    _log.exception("responder falhou em %r: %r", ctx.custom_id, exc)
    if not ctx.is_responded():
        #: A resposta pode falhar porque o token já era (15 min) — o log
        #: acima já levou o erro real; a resposta é cortesia, não contrato.
        with suppress(Exception):
            await ctx.reply(
                "Algo deu errado ao processar isso — tente novamente mais tarde.",
                ephemeral=True,
            )


def _registry_global() -> Any:
    #: Lazy de propósito: importar `kryncord.registry` no topo custaria
    #: ciclo na inicialização do pacote (registry importa os dois
    #: registries, que importam os modelos).
    from kryncord.registry import registry

    return registry.responders
