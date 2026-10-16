"""`Modal` — o formulário que abre por cima do chat.

Modal não é `Component`: no payload ele é o **objeto** do callback
(`{custom_id, title, components}`), não um item da árvore. Por isso
não declara `era` — épocas são de mensagem; modal é resposta.

O sistema novo é o único caminho público (M1): `Label` + campo. O par
legado `ActionRow` + `TextInput` continua válido **para o Discord**, e
é por isso que existe `raw` — mas o builder não oferece, porque dois
caminhos para o mesmo modal são duas fontes de divergência.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from kryncord.components.base import Component, limita
from kryncord.components.displays import TextDisplay
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

MAX_TITLE = 45
MAX_TOP_LEVEL = 5


@dataclass(frozen=True, slots=True)
class Modal:
    """Um modal.

        Modal(
            custom_id="/register/form",
            title="Cadastro",
            components=[
                Label("Nome", TextInput(custom_id="name", required=True)),
                Label("Bio", TextInput(custom_id="bio", style=TextInputStyle.PARAGRAPH)),
            ],
        )

    Valida tudo o que dá para validar sem enviar (14 §6 e 15 §6):
    teto de 45/100/5, top-level só `Label`/`TextDisplay`, e
    `custom_id` duplicado — o submit com id ambíguo devolve valor
    ambíguo, e não há debug possível depois.
    """

    custom_id: str
    title: str
    components: tuple[Component, ...] = ()

    def __post_init__(self) -> None:
        limita(self.custom_id, 100, "custom_id", onde="Modal")
        limita(self.title, MAX_TITLE, "title", onde="Modal")

        filhos = tuple(self.components)
        if len(filhos) > MAX_TOP_LEVEL:
            raise ComponentError(
                f"Modal com {len(filhos)} componentes top-level, máximo {MAX_TOP_LEVEL}"
            )

        vistos: set[str] = set()
        for i, filho in enumerate(filhos):
            if filho.type not in (ComponentType.LABEL, ComponentType.TEXT_DISPLAY):
                raise ComponentError(
                    f"Modal.components[{i}] é {filho.type.name} — top-level aceita "
                    f"Label e TextDisplay; TextInput solto mora dentro de Label"
                )
            if filho.type is ComponentType.LABEL:
                id_campo = getattr(getattr(filho, "component", None), "custom_id", None)
                if id_campo in vistos:
                    raise ComponentError(
                        f"Modal com custom_id duplicado: {id_campo!r} — o submit "
                        f"devolveria valor ambíguo e não há como saber qual campo"
                    )
                vistos.add(str(id_campo))

        object.__setattr__(self, "components", filhos)

    def walk(self) -> Iterator[Component]:
        """A árvore do modal — validação de id e leitura de campos."""
        for filho in self.components:
            yield from filho.walk()

    def to_dict(self) -> dict[str, Any]:
        return {
            "custom_id": self.custom_id,
            "title": self.title,
            "components": [c.to_dict() for c in self.components],
        }


def create_modal(custom_id: str, title: str, components: Iterable[Component] = ()) -> Modal:
    """`Modal` com a mesma validação — o helper é a forma keyword das
    ideias 14 §5, a classe é o caminho principal."""
    return Modal(custom_id=custom_id, title=title, components=tuple(components))


def create_modal_fields(*fields: Any) -> tuple[Component, ...]:
    """Normaliza o top-level do modal — o `create_components` do modal.

    `str` vira `TextDisplay`, `None`/`False` filtram (condicional
    inline), e qualquer outra coisa que não seja `Label`/`TextDisplay`
    é erro **aqui** — não no envio, quando o Discord devolve genérico.
    """
    saida: list[Component] = []
    for i, item in enumerate(fields):
        if item is None or item is False:
            continue
        if isinstance(item, str):
            saida.append(TextDisplay(item))
            continue
        if isinstance(item, Component) and item.type in (
            ComponentType.LABEL,
            ComponentType.TEXT_DISPLAY,
        ):
            saida.append(item)
            continue
        tipo = type(item).__name__
        raise ComponentError(
            f"create_modal_fields: item {i} é {tipo} — top-level de modal é "
            f"Label ou TextDisplay; o campo mora dentro do Label"
        )
    if len(saida) > MAX_TOP_LEVEL:
        raise ComponentError(f"{len(saida)} campos top-level, máximo {MAX_TOP_LEVEL}")
    return tuple(saida)


__all__ = ["MAX_TITLE", "MAX_TOP_LEVEL", "Modal", "create_modal", "create_modal_fields"]
