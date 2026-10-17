"""Autocomplete — o despacho e a resposta vazia de fallback.

A ordem de resolução é a da `0021`: B (função registrada no comando)
antes de A (função na `Option`), genérica por último, resposta vazia
de fallback — o Discord mostra "nenhum resultado" e não reclama.
Exceção aqui fecharia a janela de autocomplete com erro, que é o
pior resultado possível para uma **sugestão**.

O objeto entregue ao handler é a `AutocompleteInteraction` (`0031`):
sem `respond()`, sem `open_modal()` — a única resposta possível é
`autocomplete(choices)`, e a classe é quem diz isso.

`focused` é o **nome** da opção em foco; `focused_value` é o que o
usuário digitou até agora (`0021`). A ideia 06 usava `ctx.focused`
como valor — correção registrada na decisão, e o exemplo da própria
06 (`interaction.focused.lower()`) passa a ser
`interaction.focused_value.lower()`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kryncord.commands.instance import CommandInstance
from kryncord.enums import InteractionType
from kryncord.interactions.autocomplete import (
    MAX_ESCOLHAS,
    AutocompleteInteraction,
    normalize_choices,
)
from kryncord.interactions.response import InteractionContext
from kryncord.logging import get_logger
from kryncord.models.interaction import Interaction

_log = get_logger(__name__)


def foco_de(interaction: Interaction) -> tuple[str, Any] | None:
    """`(nome_da_opção, valor_digitado)` do payload de autocomplete.

    `None` se o payload não traz opção em foco — payload malformado
    não derruba a janela, só não sugere nada.
    """
    if interaction.type != InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE:
        return None
    bruto = interaction.data or {}
    for opcao in bruto.get("options") or []:
        if isinstance(opcao, Mapping) and opcao.get("focused"):
            return str(opcao.get("name")), opcao.get("value")
    return None


async def dispatch_autocomplete(
    interaction: Interaction,
    api: Any,
    instance: CommandInstance | None,
    *,
    client: Any = None,
) -> bool:
    """Roteia um autocomplete: B → genérica → resposta vazia (0021).

    `True` se um handler atendeu. Sem handler, responde vazio — o
    fallback legítimo — e devolve `False` para o chamador saber.
    """
    foco = foco_de(interaction)
    if foco is None or instance is None:
        await _responde_vazio(interaction, api)
        return False

    nome_opcao, valor = foco
    handlers = instance.autocomplete_handlers
    handler = handlers.get(nome_opcao) or handlers.get("*")

    inter = AutocompleteInteraction(
        InteractionContext(interaction, api),
        focused=nome_opcao,
        focused_value=valor,
        client=client,
        api=api,
    )

    if handler is None:
        #: Forma A (função na `Option`) e genérica de comando entram
        #: no bloco 10, com o registro na `Option`. Aqui o vazio é o
        #: fallback da ordem completa.
        await _responde_vazio(interaction, api)
        return False

    resultado = handler(inter)
    if hasattr(resultado, "__await__"):
        resultado = await resultado

    if not inter.is_responded():
        await inter.autocomplete(resultado or [])
    return True


async def _responde_vazio(interaction: Interaction, api: Any) -> None:
    """Lista vazia é legal — significa "nada a sugerir" (0021)."""
    try:
        await api.autocomplete(interaction, [])
    except Exception:
        #: A janela pode já ter fechado (usuário seguiu em frente).
        #: Sugestão é cortesia; logar o erro de rede dela esconderia
        #: o problema real se o handler principal falhasse depois.
        _log.debug("autocomplete: resposta vazia falhou (janela fechada?)", exc_info=True)


__all__ = [
    "MAX_ESCOLHAS",
    "AutocompleteInteraction",
    "dispatch_autocomplete",
    "foco_de",
    "normalize_choices",
]
