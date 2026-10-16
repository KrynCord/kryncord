"""Autocomplete — o `AutocompleteContext` e a normalização de escolhas.

A ordem de resolução é a da `0021`: B (função registrada no comando)
antes de A (função na `Option`), genérica por último, resposta vazia
de fallback — o Discord mostra "nenhum resultado" e não reclama.
Exceção aqui fecharia a janela de autocomplete com erro, que é o
pior resultado possível para uma **sugestão**.

`focused` é o **nome** da opção em foco; `focused_value` é o que o
usuário digitou até agora (`0021`). A ideia 06 usava `ctx.focused`
como valor — correção registrada na decisão, e o exemplo da própria
06 (`ctx.focused.lower()`) passa a ser `ctx.focused_value.lower()`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kryncord.commands.context import OptionsAccessor
from kryncord.commands.instance import CommandInstance
from kryncord.enums import InteractionType
from kryncord.logging import get_logger
from kryncord.models.interaction import Interaction

_log = get_logger(__name__)

#: O Discord mostra no máximo 25 — corta as primeiras e loga, não erro.
MAX_ESCOLHAS = 25


@dataclass(frozen=True, slots=True)
class AutocompleteContext:
    """Contexto de um autocomplete.

    **Não tem `reply`** — autocomplete aceita **um** tipo de resposta
    (`respond(choices)`), e misturar `reply` aqui faria o usuário
    mandar a resposta errada com a mensagem de erro do Discord vindo
    depois (0012, ajuste pedido pelo juiz).

    `frozen` é o contrato da `0021`; `responded` muda, e muda pelo
    `object.__setattr__` num campo declarado — o `0016` registrou que
    atributo não declarado em dataclass com `slots` levanta
    `AttributeError`, e campo declarado é o caminho.
    """

    focused: str
    """Nome da opção em foco — dado, não computação (0021)."""
    focused_value: Any = None
    """O que o usuário digitou até agora."""
    interaction: Interaction | None = None
    options: OptionsAccessor | None = None
    client: Any = None
    guild: Any = None
    channel: Any = None
    user: Any = None
    api: Any = field(default=None, repr=False, compare=False)
    """O `InteractionsAPI` — `respond` delega. Não é dado do usuário."""
    responded: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def state(self) -> dict[str, Any]:
        """Espaço por dispatch, igual ao dos outros contextos (0012)."""
        return {}

    def is_responded(self) -> bool:
        return self.responded

    async def respond(self, choices: Any) -> None:
        """Responde com as escolhas, já normalizadas.

        Aceita o que é cômodo escrever: tuplas `(nome, valor)`, dicts
        `{"name": ..., "value": ...}` e `Choice`. O corte em 25 e o
        truncamento em 100 caracteres são daqui — deixar para o
        Discord seria deixar para quem não loga.
        """
        if self.responded:
            from kryncord.errors import InteractionStateError

            raise InteractionStateError(
                "respond() já chamado neste autocomplete — a interação aceita uma "
                "sugestão só. Monte a lista inteira e mande uma vez."
            )
        if self.api is None or self.interaction is None:
            raise RuntimeError(
                "AutocompleteContext sem api/interaction não responde — contexto "
                "montado à mão em teste: passe api= e interaction=."
            )
        await self.api.autocomplete(self.interaction, normalize_choices(choices))
        object.__setattr__(self, "responded", True)

    def spawn(self, coro: Any, *, nome: str = "") -> Any:
        """Delegado ao registry de tasks do client (0012)."""
        tasks = getattr(self.client, "_tasks", None)
        if tasks is None:
            raise RuntimeError("spawn() precisa de um TaskRegistry — o Client fornece um no boot.")
        return tasks.spawn(coro, nome=nome)


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

    ctx = AutocompleteContext(
        focused=nome_opcao,
        focused_value=valor,
        interaction=interaction,
        options=OptionsAccessor(interaction),
        client=client,
        api=api,
    )

    if handler is None:
        #: Forma A (função na `Option`) e genérica de comando entram
        #: no bloco 10, com o registro na `Option`. Aqui o vazio é o
        #: fallback da ordem completa.
        await _responde_vazio(interaction, api)
        return False

    resultado = handler(ctx)
    if hasattr(resultado, "__await__"):
        resultado = await resultado

    if not ctx.is_responded():
        await ctx.respond(resultado or [])
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
    "AutocompleteContext",
    "dispatch_autocomplete",
    "foco_de",
    "normalize_choices",
]
