"""`@responder` e os decorators tipados — registro contra uma rota.

    @button("/system/confirm")
    async def confirm(interaction: ButtonInteraction):
        await interaction.update(components=["Confirmado"])

Todo o resto do módulo existe para que estes decorators **erro na
importação**: rota inválida, handler síncrono, param que a rota não
fornece, anotação sem conversor, anotação que não bate com o tipo
entregue. Erro de registro descoberto no clique é descoberto depois de
publicar o botão — quando o usuário já vê um botão que não faz nada.

Os decorators tipados (`@button`, `@string_select`…) são o
`@responder` de um tipo só, e a entrega decorre daí (`0031`):
`@button` entrega `ButtonInteraction`, `@modal_submit` entrega
`ModalSubmitInteraction` — a classe vem do decorator, nunca da
anotação. A anotação é o contrato, e é conferida aqui.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from kryncord.enums import ResponderType
from kryncord.errors import ResponderDefinitionError
from kryncord.interactions.components import ComponentInteraction, classe_para
from kryncord.internal.signatures import valida_interacao
from kryncord.responders.converters import plano_de
from kryncord.responders.registry import ResponderRegistry


def responder(
    rota: str,
    *,
    types: Iterable[ResponderType],
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registra o handler contra a rota, validando tudo que dá sem clique.

    `types` é **obrigatório e sem default** de propósito: sem filtro de
    tipo, um responder casaria qualquer interação — inclusive as que
    não existem ainda. Quem quer "qualquer select" escreve
    ``ResponderType.selects()``.

    Com **um** tipo em `types`, a anotação tem que ser a classe daquele
    tipo (`@responder(..., types=[BUTTON])` → `ButtonInteraction`);
    com vários, a superfície comum `ComponentInteraction` — porque o
    payload decide qual chega, e a anotação não pode apostar num dos
    dois (`0031`).

    `cache="cached"` dispara só se a mensagem de origem está no cache —
    e com a `CachePolicy` default (`messages=0`), **nunca** dispara.
    Não tem relação com `Config.cache`; é armadilha prevista (K2).

    `registry=` é o caminho do teste: registry global entre testes é
    contaminação de estado que vaza de um teste para o outro (K12).
    """
    if cache not in ("any", "cached", "fresh"):
        raise ResponderDefinitionError(
            f"cache={cache!r} não existe — use 'any', 'cached' ou 'fresh'. "
            f"'cached' exige a mensagem no cache; 'fresh' exige que não esteja."
        )

    tipos = tuple(types)

    def aplica(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            raise ResponderDefinitionError(
                f"handler de {rota!r} não é async — handler de responder "
                f"sempre é; um sync aqui bloquearia o loop inteiro no primeiro clique"
            )

        #: Valida **antes** de registrar: plano com param que a rota não
        #: fornece, ou anotação sem conversor, derruba aqui — com o
        #: handler ainda no import, não no clique.
        plano_de(fn, rota)
        valida_interacao(
            fn,
            classe_para(tipos[0]) if len(tipos) == 1 else ComponentInteraction,
            f"handler de {rota!r}",
        )

        destino = registry if registry is not None else _global()
        destino.register(rota, fn, types=tipos, cache=cache, parse=parse, middleware=middleware)
        return fn

    return aplica


# ----------------------------------------------------------------------
# Decorators tipados — um tipo, uma classe entregue (0031)
# ----------------------------------------------------------------------


def button(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de clique em botão — entrega `ButtonInteraction`."""
    return responder(
        rota,
        types=(ResponderType.BUTTON,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def string_select(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de select de texto — entrega `StringSelectInteraction`."""
    return responder(
        rota,
        types=(ResponderType.STRING_SELECT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def user_select(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de select de usuários — entrega `UserSelectInteraction`."""
    return responder(
        rota,
        types=(ResponderType.USER_SELECT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def role_select(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de select de funções — entrega `RoleSelectInteraction`."""
    return responder(
        rota,
        types=(ResponderType.ROLE_SELECT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def mentionable_select(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de select de menções — entrega `MentionableSelectInteraction`."""
    return responder(
        rota,
        types=(ResponderType.MENTIONABLE_SELECT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def channel_select(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de select de canais — entrega `ChannelSelectInteraction`."""
    return responder(
        rota,
        types=(ResponderType.CHANNEL_SELECT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def modal_submit(
    rota: str,
    *,
    cache: str = "any",
    parse: Callable[..., Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: ResponderRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Handler de modal submetido — entrega `ModalSubmitInteraction`.

    O envio do modal é uma **interação nova**: o `custom_id` é o do
    modal, os campos vêm em `interaction.fields` (`0031`).
    """
    return responder(
        rota,
        types=(ResponderType.MODAL_SUBMIT,),
        cache=cache,
        parse=parse,
        middleware=middleware,
        registry=registry,
    )


def _global() -> ResponderRegistry:
    from kryncord.registry import registry

    return registry.responders


__all__ = [
    "button",
    "channel_select",
    "mentionable_select",
    "modal_submit",
    "responder",
    "role_select",
    "string_select",
    "user_select",
]
