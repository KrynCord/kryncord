"""Validação estrutural — a camada que o `__post_init__` não alcança.

O `__post_init__` de cada componente valida o **local**: limite de
string, style × campo, `Label` 1:1. Esta camada valida o que só existe
**entre** componentes: o teto de 40 na árvore, os 4000 caracteres
somados, os 5 rows da mensagem V1 — e a tabela de convivência V1 × V2,
que é o único lugar do código que conhece os dois sistemas.

`ComponentError` com **caminho** em tudo: `rows[2].components[3]` num
painel de 5 rows é a diferença entre achar o bug em dez segundos e
reduzir por eliminação.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from kryncord.components.base import Component
from kryncord.components.displays import MAX_FILHOS, MAX_TEXTO_TOTAL
from kryncord.enums import ComponentType, MessageFlags
from kryncord.errors import ComponentError

if TYPE_CHECKING:
    from kryncord.components.modals import Modal
    from kryncord.components.rows import ActionRow

#: Rows por mensagem V1 — regra da **mensagem**, não da row, então é
#: daqui: é a camada estrutural quem conhece o teto do todo (0015).
MAX_ROWS = 5


def validate_components(arvore: Iterable[Component]) -> None:
    """Os dois tetos que o Discord aplica em silêncio (ideia 13 §3).

    - **40 componentes somando a árvore inteira** — aninhados contam;
    - **4000 caracteres somados de `TextDisplay`**.

    Cortar é a decisão que a V3 rejeitou: layout cortado é layout
    errado. Validar aqui é o que move o erro do render (onde ninguém
    está olhando) para a montagem (onde o autor está).
    """
    total = 0
    caracteres = 0
    for componente in arvore:
        for no in componente.walk():
            total += 1
            if no.type is ComponentType.TEXT_DISPLAY:
                caracteres += len(no.content)  # type: ignore[attr-defined]
    if total > MAX_FILHOS:
        raise ComponentError(
            f"{total} componentes na árvore, máximo {MAX_FILHOS} (aninhados contam) — "
            f"o Discord não renderiza o resto, e 'sumiu sem erro' é pior que erro"
        )
    if caracteres > MAX_TEXTO_TOTAL:
        raise ComponentError(
            f"{caracteres} caracteres de TextDisplay, máximo {MAX_TEXTO_TOTAL} "
            f"somados — o corte viria sem aviso no meio do parágrafo"
        )


def validate_rows(rows: Iterable[ActionRow]) -> None:
    """O teto de 5 rows da mensagem V1 (ideia 17 §5).

    O conteúdo de cada row é do `ActionRow.__post_init__`; aqui é só o
    teto da mensagem — validado de novo porque a lista pode chegar de
    qualquer lugar, não só de `create_components_rows`.
    """
    lista = tuple(rows)
    if len(lista) > MAX_ROWS:
        raise ComponentError(f"{len(lista)} rows, máximo {MAX_ROWS} por mensagem")


def parse_flags(flags: MessageFlags | int | Iterable[MessageFlags | int] | None) -> int | None:
    """Qualquer forma aceita → inteiro pronto pro payload.

    - `MessageFlags.EPHEMERAL | MessageFlags.IS_COMPONENTS_V2`
    - `[MessageFlags.EPHEMERAL]` — a lista que as ideias escrevem
    - `64` / `None`

    `IntFlag` de propósito: o Discord recebe o OU de várias.
    """
    if flags is None:
        return None
    if isinstance(flags, int):
        #: `IntFlag` **é** int — a instância de `MessageFlags` cai
        #: aqui, e `int()` devolve o valor dela. O ramo separado por
        #: `isinstance(MessageFlags)` seria morto: o teste de int vem
        #: primeiro na cadeia de herança.
        return int(flags)
    acumulado = 0
    for item in flags:
        if isinstance(item, int):
            acumulado |= int(item)
        else:
            raise ComponentError(
                f"flag {item!r} não é MessageFlags nem int — nomes aceitos: "
                f"{[m.name for m in MessageFlags]}"
            )
    return acumulado or None


def tem_v2(components: Iterable[Component]) -> bool:
    """Se há componente de mensagem V2 na lista.

    Top-level de V1 é **só** `ActionRow`; qualquer outra coisa na base
    é árvore V2. É a detecção da tabela da ideia 18 §4, e é por `era`
    (X2) — não por lista de nomes espalhada.

    A checagem é por `ComponentType.ACTION_ROW`, não por `isinstance`:
    importar `rows` aqui fecharia o ciclo `rows → validation → rows`.
    """
    return any(c.type is not ComponentType.ACTION_ROW for c in components)


def validate_message(
    *,
    content: str | None = None,
    embeds: Iterable[object] = (),
    components: Iterable[Component] = (),
    flags: int | MessageFlags | Iterable[MessageFlags | int] | None = None,
) -> None:
    """A tabela de convivência V1 × V2 — a ideia 18 §4 inteira.

    | Combinação | Resultado |
    |---|---|
    | `content`/`embeds` + flag V2 | `ComponentError` — o Discord **ignora em silêncio** |
    | componentes V2 sem flag | `ComponentError` — o Discord rejeitaria genérico |
    | flag sem componentes | `ComponentError` — flag órfã |
    | `era="modal"` em mensagem | `ComponentError` — campo de modal vazou |
    | V1 completo, sem flag | válido |
    | V2 completo, com flag | válido |

    Regra de bolso da detecção: top-level de V1 é só `ActionRow`.
    Qualquer outra coisa na base é árvore V2.
    """
    tem_conteudo = bool(content) or bool(tuple(embeds))
    lista = tuple(components)
    inteiro = parse_flags(flags)
    com_flag = inteiro is not None and bool(inteiro & int(MessageFlags.IS_COMPONENTS_V2))

    for i, componente in enumerate(lista):
        era = getattr(componente, "era", "both")
        if era == "modal":
            raise ComponentError(
                f"components[{i}] é {type(componente).__name__} — campo de modal "
                f"não existe em mensagem; ele mora dentro de Label, em Modal"
            )

    if com_flag:
        if tem_conteudo:
            raise ComponentError(
                "content/embeds com IS_COMPONENTS_V2 — o Discord **ignora em silêncio** "
                "nessa combinação; texto vira TextDisplay e card vira Container"
            )
        if not lista:
            raise ComponentError(
                "flag IS_COMPONENTS_V2 sem components — V2 sem componente é flag órfã"
            )
        for i, componente in enumerate(lista):
            if getattr(componente, "era", "both") == "v1":
                raise ComponentError(
                    f"components[{i}] é da geração V1 com flag V2 — os dois sistemas "
                    f"não compartilham mensagem"
                )
        validate_components(lista)
    elif tem_v2(lista):
        raise ComponentError(
            "componentes V2 sem a flag IS_COMPONENTS_V2 — o Discord rejeitaria; "
            "passe flags=[MessageFlags.IS_COMPONENTS_V2] ou v2=True na resposta"
        )
    else:
        validate_rows(cast("Iterable[ActionRow]", lista))


def validate_modal(modal: Modal) -> None:
    """Revalida a árvore de um modal já construído.

    Existe para quem monta `Modal` via `raw` e quer a mesma garantia do
    builder — o caminho legado (M1) continua aceito pelo Discord, e sem
    isto quem o usasse ficaria sem rede de segurança nenhuma.
    """
    vistos: set[str] = set()
    for no in modal.walk():
        if no.type is ComponentType.LABEL:
            id_campo = str(getattr(getattr(no, "component", None), "custom_id", ""))
            if id_campo in vistos:
                raise ComponentError(f"custom_id duplicado no modal: {id_campo!r} — submit ambíguo")
            vistos.add(id_campo)


__all__ = [
    "parse_flags",
    "tem_v2",
    "validate_components",
    "validate_message",
    "validate_modal",
    "validate_rows",
]
