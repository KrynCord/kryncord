"""`@responder` — registra um handler contra uma rota de `custom_id`.

    @responder("/system/confirm", types=[ResponderType.BUTTON])
    async def confirm(ctx):
        await ctx.update(components=["Confirmado"])

Todo o resto do módulo existe para que este decorator **erro na
importação**: rota inválida, handler síncrono, param que a rota não
fornece, anotação sem conversor. Erro de registro descoberto no clique
é descoberto depois de publicar o botão — quando o usuário já vê um
botão que não faz nada.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from kryncord.enums import ResponderType
from kryncord.errors import ResponderDefinitionError
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

        destino = registry if registry is not None else _global()
        destino.register(rota, fn, types=types, cache=cache, parse=parse, middleware=middleware)
        return fn

    return aplica


def _global() -> ResponderRegistry:
    from kryncord.registry import registry

    return registry.responders
