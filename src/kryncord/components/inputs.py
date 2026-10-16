"""`TextInput` e `Label` — o campo e o rótulo que o protocolo novo exige.

`Label` (type 18) substitui o par deprecated `ActionRow` + `TextInput`:
um rótulo, uma descrição opcional, **um** campo. O `label` do próprio
`TextInput` está deprecated no protocolo — e não é campo aqui de
propósito: passá-lo é erro de digitação, e a exceção de "campo
inesperado" é a mensagem certa (ideia 15 §1).

`TextInputStyle` mora aqui, não no `enums.py` — é enum de **builder**,
e o `enums.py` é de protocolo recebido (L3). A mesma régua vale para
todo enum de componente que só existe na montagem.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from kryncord.components.base import Component, limita
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

MAX_LABEL = 45
MAX_DESCRIPTION = 100
MAX_TEXTO = 4000


class TextInputStyle(IntEnum):
    """SHORT é uma linha; PARAGRAPH é a caixa grande."""

    SHORT = 1
    PARAGRAPH = 2


@dataclass(frozen=True, slots=True)
class TextInput(Component):
    """Campo de texto — sempre dentro de um `Label`.

    Não há campo `label`: no sistema novo o rótulo é do `Label`, e o
    homônimo deprecated do `TextInput` não tem tradução sem quebrar o
    1 rótulo : 1 campo. Passar `label=` aqui levanta `TypeError` —
    o "erro de digitação que aparece" que a ideia 15 §1 pediu.
    """

    type = ComponentType.TEXT_INPUT

    custom_id: str
    style: TextInputStyle = TextInputStyle.SHORT
    placeholder: str | None = None
    required: bool = False
    min_length: int = 0
    max_length: int | None = None
    value: str | None = None

    #: Só existe dentro de `Label`, em modal — nunca em mensagem.
    era = "modal"

    def __post_init__(self) -> None:
        limita(self.custom_id, 100, "custom_id", onde="TextInput")
        limita(self.placeholder, 100, "placeholder", onde="TextInput")
        limita(self.value, MAX_TEXTO, "value", onde="TextInput")
        if self.min_length < 0 or self.min_length > MAX_TEXTO:
            raise ComponentError(f"TextInput: min_length={self.min_length} fora de 0..{MAX_TEXTO}")
        if self.max_length is not None and (self.max_length < 1 or self.max_length > MAX_TEXTO):
            raise ComponentError(f"TextInput: max_length={self.max_length} fora de 1..{MAX_TEXTO}")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 4, "custom_id": self.custom_id}
        if self.style is not TextInputStyle.SHORT:
            payload["style"] = int(self.style)
        if self.placeholder is not None:
            payload["placeholder"] = self.placeholder
        if self.required:
            payload["required"] = True
        if self.min_length:
            payload["min_length"] = self.min_length
        if self.max_length is not None:
            payload["max_length"] = self.max_length
        if self.value is not None:
            payload["value"] = self.value
        return payload


@dataclass(frozen=True, slots=True)
class Label(Component):
    """Rótulo + descrição + **um** campo (ideias 14 §1 e 15 §3).

    Aceita `TextInput`, os 5 selects, `FileUpload`, `RadioGroup`,
    `CheckboxGroup` e `Checkbox` — e **recusa** `TextDisplay` (L6):
    texto solto é top-level do modal, não rótulo de campo.
    """

    type = ComponentType.LABEL

    label: str
    component: Component
    description: str | None = None

    #: Só existe dentro de modal — igual `TextInput`. Herdar "both" do
    #: pai deixaria `Label` passar como componente de mensagem.
    era = "modal"

    def __post_init__(self) -> None:
        limita(self.label, MAX_LABEL, "label", onde="Label")
        limita(self.description, MAX_DESCRIPTION, "description", onde="Label")

        #: `getattr`, não `isinstance`: o campo pode ser um objeto
        #: qualquer com `type`/`custom_id` — quem validaria de verdade
        #: é o protocolo, e `isinstance` negaria ao duck typing a
        #: chance de ser um campo legítimo.
        campo = getattr(self.component, "type", None)
        if campo is None or not campo.is_campo_de_label:
            nome = type(self.component).__name__
            raise ComponentError(
                f"Label aceita TextInput, selects, FileUpload, RadioGroup, CheckboxGroup "
                f"ou Checkbox; {nome} não — TextDisplay é top-level do modal, "
                f"e ActionRow é o invólucro deprecated que o Label substitui"
            )
        if not getattr(self.component, "custom_id", None):
            raise ComponentError(
                f"Label {self.label!r} com campo sem custom_id — o submit chegaria "
                f"sem a chave com a qual o handler lê o valor"
            )

    def walk(self) -> Iterator[Component]:
        yield self
        yield self.component

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": 18,
            "label": self.label,
            "component": self.component.to_dict(),
        }
        if self.description is not None:
            payload["description"] = self.description
        return payload


def create_label(
    first: str | Mapping[str, Any],
    *rest: Any,
    description: str | None = None,
    component: Component | None = None,
) -> Label:
    """O `Label` nas três formas que já estavam escritas (ideia 15 §2).

        create_label("Nome", "Seu nome completo", campo)   # A — desc posicional
        create_label("Idade", campo)                        # B — desc é keyword
        create_label({"label": ..., "component": campo})    # C — o dict que você já tem

    A resolução é por **tipo**: na forma A, o segundo argumento só é
    `description` se for `str` — um componente ali é sempre o campo.
    É o que impede o clássico "passei dois componentes sem querer"
    de passar batido.
    """
    if isinstance(first, Mapping):
        if rest or description is not None or component is not None:
            raise ComponentError(
                "create_label(dict) não mistura com os outros argumentos — o dict "
                "já traz tudo; escolha uma forma"
            )
        return Label(
            label=str(first["label"]),
            component=first["component"],
            description=first.get("description"),
        )

    if not isinstance(first, str):
        raise ComponentError(
            f"create_label: primeiro argumento {first!r} — str (formas A/B) ou dict (forma C)"
        )

    if len(rest) == 2 and isinstance(rest[0], str) and isinstance(rest[1], Component):
        if description is not None or component is not None:
            raise ComponentError(
                "create_label: description/component veio duas vezes — posicional e keyword"
            )
        return Label(label=first, component=rest[1], description=rest[0])

    if len(rest) == 1 and isinstance(rest[0], Component):
        return Label(label=first, component=rest[0], description=description)

    raise ComponentError(
        f"create_label({first!r}, {rest!r}) não casa forma nenhuma — "
        f"(label, description, campo), (label, campo) ou dict"
    )


def create_text_input(custom_id: str, **kwargs: Any) -> TextInput:
    """Alias fino do `TextInput` — existe para simetria com a base TS
    (L4); a classe é o caminho principal."""
    return TextInput(custom_id=custom_id, **kwargs)


__all__ = [
    "MAX_DESCRIPTION",
    "MAX_LABEL",
    "Label",
    "TextInput",
    "TextInputStyle",
    "create_label",
    "create_text_input",
]
