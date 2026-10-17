"""`AutocompleteInteraction` — a interação cuja única resposta é sugestão.

Autocomplete não tem `respond()`: aceita **um** tipo de resposta, a
lista de escolhas (`autocomplete(choices)`), e misturar as duas faria
o usuário mandar a resposta errada com o erro do Discord vindo depois
(`0021`, `0031`). Por isso ela herda só o `InteractionBase` — dados, sem
o ciclo de resposta comum.

`focused` é o **nome** da opção em foco; `focused_value` é o que o
usuário digitou até agora. A ideia 06 usava `focused` como valor —
correção registrada na decisão.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kryncord.errors import InvalidInteractionState
from kryncord.interactions.base import InteractionBase
from kryncord.interactions.commands import OptionsAccessor
from kryncord.logging import get_logger

_log = get_logger(__name__)

#: O Discord mostra no máximo 25 — corta as primeiras e loga, não erro.
MAX_ESCOLHAS = 25


class AutocompleteInteraction(InteractionBase):
    """Uma interação de autocomplete em andamento."""

    __slots__ = ("_api", "_focused", "_focused_value", "_responded")

    def __init__(
        self,
        interaction_ctx: Any,
        *,
        focused: str,
        focused_value: Any = None,
        client: Any = None,
        api: Any = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(interaction_ctx, client=client, state=state)
        self._focused = focused
        self._focused_value = focused_value
        self._api = api
        self._responded = False

    @property
    def focused(self) -> str:
        """Nome da opção em foco — dado, não computação (0021)."""
        return self._focused

    @property
    def focused_value(self) -> Any:
        """O que o usuário digitou até agora."""
        return self._focused_value

    @property
    def options(self) -> OptionsAccessor:
        """As opções já preenchidas — as que **não** estão em foco."""
        return OptionsAccessor(self.interaction)

    def is_responded(self) -> bool:
        """Se já mandamos sugestões — aceita uma só."""
        return self._responded

    async def autocomplete(self, choices: Any) -> None:
        """Responde com as sugestões, já normalizadas.

        Aceita o que é cômodo escrever: tuplas `(nome, valor)`, dicts
        `{"name": ..., "value": ...}` e `Choice`. O corte em 25 e o
        truncamento em 100 caracteres são daqui — deixar para o Discord
        seria deixar para quem não loga.
        """
        if self._responded:
            raise InvalidInteractionState(
                "autocomplete() já chamado neste autocomplete — a interação aceita uma "
                "sugestão só. Monte a lista inteira e mande uma vez."
            )
        if self._api is None:
            raise RuntimeError(
                "AutocompleteInteraction sem api não responde — interação "
                "montada à mão em teste: passe api=."
            )
        await self._api.autocomplete(self.interaction, normalize_choices(choices))
        self._responded = True


def normalize_choices(choices: Any) -> list[dict[str, Any]]:
    """De tuple/dict/`Choice` para o payload do Discord.

    Truncamento e corte **logam em DEBUG** (0021) — corte silencioso
    esconde bug de quem chamou; erro aqui derrubaria a janela de
    sugestão, que é o lugar mais hostil do mundo para um traceback.
    """
    if choices is None:
        return []
    itens: list[Any] = list(choices) if isinstance(choices, (list, tuple)) else [choices]

    saida: list[dict[str, Any]] = []
    for item in itens:
        normalizado = _um_choice(item)
        if normalizado is None:
            continue
        nome, valor = normalizado
        #: O limite de nome é o mesmo dos `Choice` de `Option` — 100.
        #: O Discord recusaria na criação; aqui é corte e log, porque
        #: derrubar a janela por um nome comprido é desproporcional.
        if len(nome) > 100:
            _log.debug("autocomplete: nome %r cortado em 100 caracteres", nome)
            nome = nome[:100]
        saida.append({"name": nome, "value": valor})

    if len(saida) > MAX_ESCOLHAS:
        _log.debug(
            "autocomplete: %d escolhas cortadas em %d — o Discord só mostra %d",
            len(saida),
            MAX_ESCOLHAS,
            MAX_ESCOLHAS,
        )
        saida = saida[:MAX_ESCOLHAS]
    return saida


def _um_choice(item: Any) -> tuple[str, Any] | None:
    """Uma escolha em `(nome, valor)`, nas três formas que existem."""
    if isinstance(item, Mapping):
        nome = item.get("name")
        return (str(nome), item.get("value")) if nome is not None else None
    if isinstance(item, (list, tuple)) and len(item) == 2:
        return str(item[0]), item[1]
    nome = getattr(item, "name", None)
    if nome is not None:
        return str(nome), getattr(item, "value", nome)
    _log.debug("autocomplete: item inválido ignorado: %r", item)
    return None


__all__ = [
    "MAX_ESCOLHAS",
    "AutocompleteInteraction",
    "normalize_choices",
]
