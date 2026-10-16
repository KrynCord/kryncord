"""Os campos de escolha de modal — `RadioGroup`, `CheckboxGroup`, `Checkbox`.

São os três que a ideia 15 §3 lista como filhos de `Label` e que o
layout unificado da `0015` não alojava (0024, C1). Moram juntos porque
são a mesma natureza: **escolha**, não texto.

As opções são o `SelectOption` dos selects — classe, dict ou tuple —
porque a validação 1–25 é a mesma e reimplementá-la aqui seria uma
segunda tabela para deixar divergir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kryncord.components.base import Component
from kryncord.components.selects import MAX_OPTIONS, SelectOption
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError


def _opcoes(tipo: str, bruto: tuple[Any, ...]) -> tuple[SelectOption, ...]:
    """Normaliza e valida 1–25 — a mesma régua do `StringSelectMenu`."""
    normalizadas = tuple(SelectOption.de(o) for o in bruto)
    if not normalizadas:
        raise ComponentError(f"{tipo} sem options — campo de escolha sem escolhas")
    if len(normalizadas) > MAX_OPTIONS:
        raise ComponentError(f"{tipo} com {len(normalizadas)} options, máximo {MAX_OPTIONS}")
    return normalizadas


@dataclass(frozen=True, slots=True)
class RadioGroup(Component):
    """Escolha única com botões de rádio — o select que não abre menu.

    Label("Prioridade", RadioGroup(custom_id="prio", options=[
        {"label": "Baixa", "value": "low"},
        {"label": "Alta", "value": "high"},
    ]))
    """

    type = ComponentType.RADIO_GROUP

    custom_id: str
    options: tuple[SelectOption | Any, ...] = ()
    required: bool = False

    era = "modal"

    def __post_init__(self) -> None:
        #: Normaliza aqui, não no `to_dict`: o que fica guardado é o
        #: que o `__eq__` compara — dict cru faria dois grupos iguais
        #: serem diferentes.
        object.__setattr__(self, "options", _opcoes("RadioGroup", self.options))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 21, "custom_id": self.custom_id}
        if self.required:
            payload["required"] = True
        payload["options"] = [o.to_dict() for o in self.options]
        return payload


@dataclass(frozen=True, slots=True)
class CheckboxGroup(Component):
    """Múltipla escolha — os checks que marcam juntos.

    Label("Interesses", CheckboxGroup(custom_id="tags", options=[...]))
    """

    type = ComponentType.CHECKBOX_GROUP

    custom_id: str
    options: tuple[SelectOption | Any, ...] = ()
    required: bool = False

    era = "modal"

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", _opcoes("CheckboxGroup", self.options))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 22, "custom_id": self.custom_id}
        if self.required:
            payload["required"] = True
        payload["options"] = [o.to_dict() for o in self.options]
        return payload


@dataclass(frozen=True, slots=True)
class Checkbox(Component):
    """Sim/não — um só, sem options.

    `Checkbox` **não** devolve `list[str]` como os grupos: é um só valor
    (L5), e o leitor do submit entrega `bool`.
    """

    type = ComponentType.CHECKBOX

    custom_id: str
    default: bool = False
    required: bool = False

    era = "modal"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 23, "custom_id": self.custom_id}
        if self.default:
            payload["default"] = True
        if self.required:
            payload["required"] = True
        return payload


__all__ = ["Checkbox", "CheckboxGroup", "RadioGroup"]
