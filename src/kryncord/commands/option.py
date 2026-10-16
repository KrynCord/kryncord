"""Declaração de opção de comando.

`Option` é o parâmetro de um slash command — e não tem nada a ver com
`CommandOptions`, que é configuração do `Config`. O nome é o mesmo que
as ideias usam e o que o Discord chama; o sufixo `Options` do outro é
o que distingue.

Fica em módulo próprio porque é a parte da API que o usuário toca em
toda declaração de comando — e porque a validação (`commands/validation`)
importa dele sem puxar o registry junto.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from kryncord.errors import DefinitionError


class OptionType(IntEnum):
    """Tipos de opção, conforme a documentação do Discord."""

    SUB_COMMAND = 1
    SUB_COMMAND_GROUP = 2
    STRING = 3
    INTEGER = 4
    BOOLEAN = 5
    USER = 6
    CHANNEL = 7
    ROLE = 8
    MENTIONABLE = 9
    NUMBER = 10
    ATTACHMENT = 11


#: O que o Discord aceita como tipo de opção de usuário — os quatro que
#: carregam entidade e não valor. `SUB_COMMAND` fica de fora: ele não é
#: um tipo de valor, é estrutura.
TIPOS_DE_ENTIDADE = (OptionType.USER, OptionType.CHANNEL, OptionType.ROLE, OptionType.MENTIONABLE)

#: Máximos do payload do Discord. Estourar é 400 na requisição — e o
#: sync falharia a meio caminho, depois de já ter enviado os outros.
MAX_OPCOES = 25
MAX_CHOICES = 25
MAX_SUBCOMANDOS_POR_GRUPO = 25


@dataclass(frozen=True, slots=True)
class Option:
    """Uma opção de comando, já no formato que o Discord espera."""

    name: str
    type: OptionType
    description: str = ""
    required: bool = False
    choices: tuple[Mapping[str, Any], ...] = ()
    """Escolhas fixas. `name` e `value` são obrigatórios em cada uma;
    `name_localizations` é opcional."""
    autocomplete: bool = False
    """Se a lista de escolhas vem do `@comando.autocomplete()`.
    Mutuamente exclusivo com `choices` — o Discord recusa os dois."""
    min_value: int | float | None = None
    max_value: int | float | None = None
    channel_types: tuple[int, ...] = ()
    options: tuple[Option, ...] = ()
    """Sub-opções — só de `SUB_COMMAND` e `SUB_COMMAND_GROUP`. Uma
    opção de valor não tem opções, e uma de estrutura não tem valor;
    `commands/validation.py` é quem cobra isso."""

    def __post_init__(self) -> None:
        if not self.name:
            raise DefinitionError("Option precisa de name")
        if self.required and self.choices:
            raise DefinitionError(
                f"opção {self.name!r}: required=True e choices não combinam — "
                "escolhas fixas já decidem o valor"
            )
        if self.autocomplete and self.choices:
            raise DefinitionError(
                f"opção {self.name!r}: autocomplete=True e choices não combinam — "
                "o Discord recusa os dois juntos"
            )
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise DefinitionError(
                f"opção {self.name!r}: min_value ({self.min_value}) é maior "
                f"que max_value ({self.max_value})"
            )

    def to_payload(self) -> dict[str, Any]:
        """Payload no formato do Discord. Campos vazios ficam de fora
        — mandar `choices=[]` é diferente de não mandar, e o Discord
        reclama do primeiro."""
        payload: dict[str, Any] = {
            "name": self.name,
            "type": int(self.type),
            "description": self.description,
            "required": self.required,
        }
        if self.choices:
            payload["choices"] = [dict(c) for c in self.choices]
        if self.options:
            payload["options"] = [o.to_payload() for o in self.options]
        if self.autocomplete:
            payload["autocomplete"] = True
        if self.min_value is not None:
            payload["min_value"] = self.min_value
        if self.max_value is not None:
            payload["max_value"] = self.max_value
        if self.channel_types:
            payload["channel_types"] = list(self.channel_types)
        return payload

    # ------------------------------------------------------------------
    # Atalhos — a forma declarativa das ideias
    # ------------------------------------------------------------------

    @classmethod
    def string(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.STRING, description, **kwargs)

    @classmethod
    def integer(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.INTEGER, description, **kwargs)

    @classmethod
    def number(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.NUMBER, description, **kwargs)

    @classmethod
    def boolean(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.BOOLEAN, description, **kwargs)

    @classmethod
    def user(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.USER, description, **kwargs)

    @classmethod
    def channel(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.CHANNEL, description, **kwargs)

    @classmethod
    def role(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.ROLE, description, **kwargs)

    @classmethod
    def mentionable(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.MENTIONABLE, description, **kwargs)

    @classmethod
    def attachment(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.ATTACHMENT, description, **kwargs)

    @classmethod
    def sub_command(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.SUB_COMMAND, description, **kwargs)

    @classmethod
    def group(cls, name: str, description: str = "", **kwargs: Any) -> Option:
        return cls(name, OptionType.SUB_COMMAND_GROUP, description, **kwargs)


def choice(nome: str, valor: Any, **localizations: str) -> dict[str, Any]:
    """Uma escolha, no formato do payload.

    Aceita `localizations=` como kwargs — a forma curta de dizer
    `{"pt-BR": "Sim", "en-US": "Yes"}` sem aninhar dict.
    """
    item: dict[str, Any] = {"name": nome, "value": valor}
    if localizations:
        item["name_localizations"] = dict(localizations)
    return item
