"""Definição de comando — o payload que vai ao Discord.

`CommandDefinition` é **dado**. Não conhece o registry, não conhece o
handler, não faz I/O. É o que o `sync()` serializa, e é por isso que a
comparação de igualdade profunda do `0018` funciona: dois comandos
iguais são `==`, e o diff sai de graça.

O campo `scope` decide a URL: `None` é global, um inteiro é o id da
guild. Não há um terceiro caso — o `0011` fechou que `CommandScope`
value object seria só uma tradução de volta para `None | int`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.commands.option import (
    Option,
)
from kryncord.enums import ApplicationCommandType
from kryncord.permissions import Permissions


class CommandScope:
    """O destino de registro de um comando.

    `None` é o global. Não é value object: é `int | None`, que é o que
    a URL e o payload já usam. Um objeto aqui teria que ser traduzido
    de volta na hora de montar a rota — trabalho sem ganho.
    """

    __slots__ = ()

    @staticmethod
    def global_() -> None:
        """Marca o escopo global. Existe como nome, para ler bem em
        testes e na mensagem do `sync` — o valor é `None` mesmo."""
        return None


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """Definição serializável de um comando."""

    name: str
    description: str
    type: ApplicationCommandType = ApplicationCommandType.CHAT_INPUT
    scope: int | None = None
    options: tuple[Option, ...] = ()
    default_member_permissions: Permissions | None = None
    """`None` é "sem restrição", que é diferente de `Permissions(0)`."""
    dm_permission: bool | None = None
    nsfw: bool = False
    name_localizations: Mapping[str, str] | None = None
    description_localizations: Mapping[str, str] | None = None

    def to_payload(self) -> dict[str, Any]:
        """Payload do Discord. Só inclui o que foi declarado — mandar
        `dm_permission=None` é diferente de não mandar, e o Discord
        trata os dois de formas diferentes."""
        payload: dict[str, Any] = {
            "name": self.name,
            "type": int(self.type),
            "description": self.description,
        }
        if self.options:
            payload["options"] = [o.to_payload() for o in self.options]
        if self.default_member_permissions is not None:
            payload["default_member_permissions"] = str(int(self.default_member_permissions))
        if self.dm_permission is not None:
            payload["dm_permission"] = self.dm_permission
        if self.nsfw:
            payload["nsfw"] = True
        if self.name_localizations:
            payload["name_localizations"] = dict(self.name_localizations)
        if self.description_localizations:
            payload["description_localizations"] = dict(self.description_localizations)
        return payload

    @property
    def is_global(self) -> bool:
        return self.scope is None

    def com_escopo(self, scope: int | None) -> CommandDefinition:
        """Cópia apontando para outro escopo.

        É como o decorator `guild=` do `K1` materializa a definição: um
        mesmo comando declarado uma vez pode ir para várias guilds, e
        cada uma é uma entrada distinta do registry.
        """
        return CommandDefinition(
            name=self.name,
            description=self.description,
            type=self.type,
            scope=scope,
            options=self.options,
            default_member_permissions=self.default_member_permissions,
            dm_permission=self.dm_permission,
            nsfw=self.nsfw,
            name_localizations=self.name_localizations,
            description_localizations=self.description_localizations,
        )
