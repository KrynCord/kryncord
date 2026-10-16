"""`ActionRow` e as fachadas que montam a mensagem.

Três construtores, três propósitos:

- `create_row(*botões_ou_1_select)` — uma row. O único invólucro de
  botão/select nas duas gerações.
- `create_components_rows(*rows)` — a lista V1: top-level é ActionRow,
  teto de 5, filtro de condicional inline.
- `create_components(*children)` — a árvore V2: `str` vira `TextDisplay`,
  botão/select ganham row, `Attachment` vira galeria — e os limites de
  40 componentes e 4000 caracteres são **aqui**, validando a árvore
  inteira via `walk()` (ideia 13 §3: na montagem, nunca corte).

A regra "botão **ou** select" é do protocolo — o Discord rejeita a
mistura com erro genérico. `create_row` valida e devolve `ComponentError`
com o índice do item conflitante (ideia 17 §1).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from kryncord.components.base import Component
from kryncord.components.displays import (
    MediaGallery,
    TextDisplay,
)
from kryncord.components.validation import MAX_ROWS, validate_components
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

MAX_BOTOES = 5


@dataclass(frozen=True, slots=True)
class ActionRow(Component):
    """Botões (1–5) **ou** exatamente um select — nunca os dois.

    `era = "both"`: é o mesmo componente nas duas gerações, e é isso
    que deixa `Button` e os selects sem duplicar builder.
    """

    type = ComponentType.ACTION_ROW

    components: tuple[Component, ...] = ()

    def __post_init__(self) -> None:
        filhos = tuple(self.components)
        if not filhos:
            raise ComponentError("ActionRow vazia — row sem conteúdo não renderiza")

        selects = [c for c in filhos if c.type.is_select]
        if selects:
            if len(filhos) > 1:
                raise ComponentError(
                    f"ActionRow com select e mais {len(filhos) - 1} componente(s) — "
                    f"select ocupa a row inteira; {len(filhos) - 1} solto(s) no índice "
                    f"{[i for i, c in enumerate(filhos) if not c.type.is_select]}"
                )
        else:
            if len(filhos) > MAX_BOTOES:
                raise ComponentError(
                    f"ActionRow com {len(filhos)} componentes, máximo {MAX_BOTOES}"
                )
            estranho = next(
                (i for i, c in enumerate(filhos) if c.type is not ComponentType.BUTTON), None
            )
            if estranho is not None:
                raise ComponentError(
                    f"ActionRow.components[{estranho}] é {filhos[estranho].type.name} — "
                    f"row de botão só aceita botão; select mora sozinho"
                )
        object.__setattr__(self, "components", filhos)

    def walk(self) -> Iterator[Component]:
        yield self
        for filho in self.components:
            yield from filho.walk()

    def to_dict(self) -> dict[str, Any]:
        return {"type": 1, "components": [c.to_dict() for c in self.components]}


def create_row(*itens: Any) -> ActionRow:
    """Monta uma row, filtrando condicionais.

    | Entrada | Vira |
    |---|---|
    | `Button` / select | passa |
    | `None` / `False` | filtrado — `cond and Button(...)` some junto com a condição |
    | `str` | `ComponentError` — não existe texto dentro de row, em geração nenhuma |
    | `True` / `int` / objeto desconhecido | `ComponentError` com o tipo e o índice |
    """
    filtrados: list[Component] = []
    for i, item in enumerate(itens):
        if item is None or item is False:
            continue
        if isinstance(item, Component):
            if not (item.type is ComponentType.BUTTON or item.type.is_select):
                raise ComponentError(
                    f"create_row: item {i} é {item.type.name} — row aceita botão e "
                    f"select; texto mora em TextDisplay, não em row"
                )
            filtrados.append(item)
            continue
        if isinstance(item, (bool, int)):
            raise ComponentError(
                f"create_row: item {i} é {type(item).__name__} — quase sempre condicional "
                f"que devolveu verdadeiro onde devia devolver componente"
            )
        if isinstance(item, str):
            raise ComponentError(
                f"create_row: item {i} é str — texto na row não existe; use TextDisplay "
                f"(V2) ou content= (V1)"
            )
        raise ComponentError(
            f"create_row: item {i} é {type(item).__name__}, não componente — "
            f"True/int na lista é condicional que vazou"
        )
    if not filtrados:
        raise ComponentError(
            "create_row: tudo filtrado — row vazia depois do filtro de condicional "
            "é um `if` que ninguém percebeu"
        )
    return ActionRow(components=tuple(filtrados))


def create_components_rows(*rows: Any) -> tuple[ActionRow, ...]:
    """A lista V1: cada item uma row, teto de 5 (ideia 17 §6).

    Aceita `ActionRow` pronta ou botão/select solto (que ganha a row).
    `None`/`False` filtram — é o irmão direto do `create_components`,
    mesma convenção de condicional inline.
    """
    saida: list[ActionRow] = []
    for i, item in enumerate(rows):
        if item is None or item is False:
            continue
        if isinstance(item, ActionRow):
            saida.append(item)
            continue
        if isinstance(item, Component):
            saida.append(create_row(item))
            continue
        raise ComponentError(
            f"create_components_rows: item {i} é {type(item).__name__} — "
            f"esperado ActionRow, botão ou select"
        )
    if len(saida) > MAX_ROWS:
        raise ComponentError(
            f"{len(saida)} rows, máximo {MAX_ROWS} por mensagem — as que sobraram não renderizam"
        )
    return tuple(saida)


def create_components(*children: Any) -> tuple[Component, ...]:
    """A árvore V2, normalizada e validada (ideia 13 §6).

    | Entrada | Vira |
    |---|---|
    | `str` | `TextDisplay` |
    | componente V2 (`Container`, `Section`, …) | passa |
    | `Button` / select | envolvido em `ActionRow` |
    | `ActionRow` | passa |
    | `Attachment` | `MediaGallery` com a URL do anexo |
    | `None` / `False` | **filtrado** — condicional inline |
    | `True` / `int` / desconhecido | `ComponentError` com tipo e índice |

    Depois de normalizar, valida os dois tetos que o Discord aplica em
    silêncio: **40** componentes somando a árvore inteira e **4000**
    caracteres somados de `TextDisplay` — cortar layout é a decisão
    que a V3 rejeitou.
    """
    normalizados: list[Component] = []
    for i, item in enumerate(children):
        if item is None or item is False:
            continue
        if isinstance(item, str):
            normalizados.append(TextDisplay(item))
            continue
        if isinstance(item, ActionRow):
            normalizados.append(item)
            continue
        if isinstance(item, Component):
            if item.type is ComponentType.BUTTON or item.type.is_select:
                normalizados.append(create_row(item))
                continue
            normalizados.append(item)
            continue
        if hasattr(item, "url"):
            normalizados.append(MediaGallery(item.url))
            continue
        tipo = type(item).__name__
        raise ComponentError(
            f"create_components: item {i} é {tipo} — True/int na lista é condicional "
            f"que vazou; str vira TextDisplay, Attachment vira galeria"
        )

    arvore = tuple(normalizados)
    validate_components(arvore)
    return arvore


__all__ = [
    "MAX_BOTOES",
    "MAX_ROWS",
    "ActionRow",
    "create_components",
    "create_components_rows",
    "create_row",
]
