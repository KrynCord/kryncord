"""Selects — os cinco menus, com `SelectOption` normalizado.

Quatro dos cinco são preenchidos pelo Discord (usuário, cargo, menção,
canal); só o `StringSelect` traz as próprias opções — e é por isso que
ele é o único com campo `options` e o único que valida 1–25.

`SelectOption` aceita dict e tuple além da classe: as ideias escrevem
`options=[{"label": "Maçã", "value": "apple", "emoji": "🍎"}]` nas
três — e fazer a classe aceitar a forma que já está escrita é mais
barato que obrigar conversão.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from kryncord.components.base import Component, limita
from kryncord.enums import ChannelType, ComponentType
from kryncord.errors import ComponentError

MAX_PLACEHOLDER = 150
MAX_OPTIONS = 25
MAX_VALORES = 25
MAX_OPCAO_TEXTO = 100


@dataclass(frozen=True, slots=True)
class SelectOption:
    """Uma opção de `StringSelectMenu` (e de `RadioGroup`/`CheckboxGroup`).

    `de(bruto)` normaliza as três formas — classe, dict, tuple
    `("Label", "value")` — porque o que muda entre elas é verbosidade,
    não significado.
    """

    label: str
    value: str
    description: str | None = None
    emoji: str | Mapping[str, Any] | None = None
    default: bool = False

    def __post_init__(self) -> None:
        limita(self.label, MAX_OPCAO_TEXTO, "label", onde="SelectOption")
        limita(self.value, MAX_OPCAO_TEXTO, "value", onde="SelectOption")
        limita(self.description, MAX_OPCAO_TEXTO, "description", onde="SelectOption")

    @classmethod
    def de(cls, bruto: SelectOption | Mapping[str, Any] | Sequence[Any]) -> SelectOption:
        if isinstance(bruto, cls):
            return bruto
        if isinstance(bruto, Mapping):
            if "label" not in bruto or "value" not in bruto:
                raise ComponentError(
                    f"opção {bruto!r} sem label/value — são os dois campos sem os "
                    f"quais o Discord não sabe o que mostrar nem o que devolver"
                )
            return cls(
                label=str(bruto["label"]),
                value=str(bruto["value"]),
                description=bruto.get("description"),
                emoji=bruto.get("emoji"),
                default=bool(bruto.get("default", False)),
            )
        if isinstance(bruto, Sequence) and len(bruto) == 2:
            return cls(label=str(bruto[0]), value=str(bruto[1]))
        raise ComponentError(f"opção {bruto!r} não é SelectOption, dict nem tuple (label, value)")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"label": self.label, "value": self.value}
        if self.description is not None:
            payload["description"] = self.description
        if self.emoji is not None:
            payload["emoji"] = (
                dict(self.emoji) if isinstance(self.emoji, Mapping) else {"name": self.emoji}
            )
        if self.default:
            payload["default"] = True
        return payload


def _opcoes(bruto: Iterable[Any], onde: str) -> tuple[SelectOption, ...]:
    """Normaliza e valida 1–25 — o 0 é o que mais escapa.

    Select sem opção renderiza vazio e o clique devolve nada; exigir
    uma é o mesmo critério do botão sem label: o que não tem como ser
    usado não deveria existir.
    """
    normalizadas = tuple(SelectOption.de(o) for o in bruto)
    if not normalizadas:
        raise ComponentError(f"{onde} sem options — select vazio não tem o que escolher")
    if len(normalizadas) > MAX_OPTIONS:
        raise ComponentError(
            f"{onde} com {len(normalizadas)} options, máximo {MAX_OPTIONS} — "
            f"cortar mudaria o que o usuário pode escolher"
        )
    return normalizadas


def _comum(self: _SelectBase) -> None:
    limita(self.custom_id, 100, "custom_id", onde=type(self).__name__)
    limita(self.placeholder, MAX_PLACEHOLDER, "placeholder", onde=type(self).__name__)
    if self.min_values < 0 or self.min_values > MAX_VALORES:
        raise ComponentError(
            f"{type(self).__name__}: min_values={self.min_values} fora de 0..{MAX_VALORES}"
        )
    if self.max_values < 1 or self.max_values > MAX_VALORES:
        raise ComponentError(
            f"{type(self).__name__}: max_values={self.max_values} fora de 1..{MAX_VALORES}"
        )
    if self.min_values > self.max_values:
        raise ComponentError(
            f"{type(self).__name__}: min_values={self.min_values} > max_values={self.max_values} "
            f"— o mínimo não pode passar do máximo"
        )


@dataclass(frozen=True, slots=True)
class _SelectBase(Component):
    """O que os cinco têm em comum. Não se instancia — ver os filhos."""

    custom_id: str
    placeholder: str | None = None
    min_values: int = 1
    max_values: int = 1
    disabled: bool = False

    def _payload_comum(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"custom_id": self.custom_id}
        if self.placeholder is not None:
            payload["placeholder"] = self.placeholder
        if self.min_values != 1:
            payload["min_values"] = self.min_values
        if self.max_values != 1:
            payload["max_values"] = self.max_values
        if self.disabled:
            payload["disabled"] = True
        return payload


@dataclass(frozen=True, slots=True)
class StringSelectMenu(_SelectBase):
    """Menu de texto — as opções são suas (1–25)."""

    type = ComponentType.STRING_SELECT

    options: tuple[SelectOption | Mapping[str, Any] | Sequence[Any], ...] = ()

    def __post_init__(self) -> None:
        _comum(self)
        #: Normaliza aqui, e não no `to_dict`: o que fica guardado é o
        #: que o `__eq__` compara — deixar dict cru faria dois menus
        #: iguais serem diferentes.
        object.__setattr__(self, "options", _opcoes(self.options, "StringSelectMenu"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": 3,
            **self._payload_comum(),
            "options": [o.to_dict() for o in cast("tuple[SelectOption, ...]", self.options)],
        }


@dataclass(frozen=True, slots=True)
class UserSelectMenu(_SelectBase):
    """Menu de usuários — o Discord preenche as opções."""

    type = ComponentType.USER_SELECT

    def __post_init__(self) -> None:
        _comum(self)

    def to_dict(self) -> dict[str, Any]:
        return {"type": 5, **self._payload_comum()}


@dataclass(frozen=True, slots=True)
class RoleSelectMenu(_SelectBase):
    """Menu de cargos."""

    type = ComponentType.ROLE_SELECT

    def __post_init__(self) -> None:
        _comum(self)

    def to_dict(self) -> dict[str, Any]:
        return {"type": 6, **self._payload_comum()}


@dataclass(frozen=True, slots=True)
class MentionableSelectMenu(_SelectBase):
    """Menu de usuários e cargos juntos."""

    type = ComponentType.MENTIONABLE_SELECT

    def __post_init__(self) -> None:
        _comum(self)

    def to_dict(self) -> dict[str, Any]:
        return {"type": 7, **self._payload_comum()}


@dataclass(frozen=True, slots=True)
class ChannelSelectMenu(_SelectBase):
    """Menu de canais, filtrável por tipo."""

    type = ComponentType.CHANNEL_SELECT

    channel_types: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _comum(self)
        object.__setattr__(self, "channel_types", tuple(int(t) for t in self.channel_types))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 8, **self._payload_comum()}
        if self.channel_types:
            payload["channel_types"] = list(self.channel_types)
        return payload


def create_string_select(
    custom_id: str = "", *, options: Iterable[Any] = (), **kwargs: Any
) -> StringSelectMenu:
    if not custom_id:
        raise ComponentError("select sem custom_id — o submit chegaria sem com o que casar")
    return StringSelectMenu(custom_id=custom_id, options=tuple(options), **kwargs)


def create_user_select(custom_id: str = "", **kwargs: Any) -> UserSelectMenu:
    if not custom_id:
        raise ComponentError("select sem custom_id — o submit chegaria sem com o que casar")
    return UserSelectMenu(custom_id=custom_id, **kwargs)


def create_role_select(custom_id: str = "", **kwargs: Any) -> RoleSelectMenu:
    if not custom_id:
        raise ComponentError("select sem custom_id — o submit chegaria sem com o que casar")
    return RoleSelectMenu(custom_id=custom_id, **kwargs)


def create_mentionable_select(custom_id: str = "", **kwargs: Any) -> MentionableSelectMenu:
    if not custom_id:
        raise ComponentError("select sem custom_id — o submit chegaria sem com o que casar")
    return MentionableSelectMenu(custom_id=custom_id, **kwargs)


def create_channel_select(
    custom_id: str = "", *, channel_types: Iterable[ChannelType | int] = (), **kwargs: Any
) -> ChannelSelectMenu:
    if not custom_id:
        raise ComponentError("select sem custom_id — o submit chegaria sem com o que casar")
    return ChannelSelectMenu(
        custom_id=custom_id, channel_types=tuple(int(t) for t in channel_types), **kwargs
    )


__all__ = [
    "MAX_OPTIONS",
    "ChannelSelectMenu",
    "MentionableSelectMenu",
    "RoleSelectMenu",
    "SelectOption",
    "StringSelectMenu",
    "UserSelectMenu",
    "create_channel_select",
    "create_mentionable_select",
    "create_role_select",
    "create_string_select",
    "create_user_select",
]
