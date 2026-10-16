"""Comando de aplicação — slash command, comando de contexto, mensagem.

Um `ApplicationCommand` é a **definição** registrada no Discord, não a
execução. Registrar é ida e volta: `POST` cria e devolve o objeto com
``version`` e ``id`` gerados; `PUT` substitui a lista inteira, que é a
forma segura de sincronizar — criar um a um deixa comandos órfãos
quando alguém apaga um do código.

`options` fica cru (`tuple[Mapping, ...]`), não vira modelo. As opções
de comando têm sete tipos com campos mutuamente exclusivos (string,
inteiro, user, channel, role, mentionable, attachment), e parser cada
um seria uma árvore de herança que muda a cada atualização do Discord.
Quem lê uma opção lê o dict — é o payload, sem tradução a manter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import boolean, integer, sequence, snowflake, string


@dataclass(frozen=True, slots=True)
class ApplicationCommand:
    """Definição de comando registrada no Discord."""

    id: int
    application_id: int
    name: str
    description: str
    type: int = 1
    """``1`` CHAT_INPUT (slash), ``2`` USER (contexto de usuário),
    ``3`` MESSAGE (contexto de mensagem)."""
    guild_id: int | None = None
    options: tuple[Mapping[str, Any], ...] = ()
    default_member_permissions: str | None = None
    dm_permission: bool | None = None
    nsfw: bool = False
    version: int | None = None
    name_localizations: Mapping[str, str] | None = None
    description_localizations: Mapping[str, str] | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> ApplicationCommand | None:
        """`None` se faltar ``id`` ou ``name`` — sem ID não se edita,
        sem nome não se invoca."""
        command_id = snowflake(data, "id")
        name = string(data, "name")
        if command_id is None or name is None:
            return None
        raw_options = sequence(data, "options")
        dm_permission = data.get("dm_permission")
        permissions = string(data, "default_member_permissions")
        return cls(
            id=command_id,
            application_id=snowflake(data, "application_id") or 0,
            name=name,
            # Descrição vazia é legal para comando de contexto (tipo 2/3),
            # que o Discord exige sem descrição. ``""`` e ausente viram
            # a mesma coisa aqui, e é a única exceção: o campo é
            # obrigatório por spec, então ausente não significa nada.
            description=string(data, "description") or "",
            type=integer(data, "type") or 1,
            guild_id=snowflake(data, "guild_id"),
            options=tuple(o for o in raw_options if isinstance(o, Mapping)),
            default_member_permissions=permissions,
            dm_permission=dm_permission if isinstance(dm_permission, bool) else None,
            nsfw=boolean(data, "nsfw"),
            version=snowflake(data, "version"),
            name_localizations=_localizations(data, "name_localizations"),
            description_localizations=_localizations(data, "description_localizations"),
        )

    @property
    def is_chat_input(self) -> bool:
        """Se é um slash command (``/``)."""
        return self.type == 1

    @property
    def is_context_menu(self) -> bool:
        """Se é comando de contexto — clique direito em usuário ou mensagem."""
        return self.type in (2, 3)

    @property
    def mention(self) -> str:
        """Texto que invoca o comando no chat — `</nome:id>`.

        Só funciona para comando já registrado. Um recém-criado ainda
        não tem `version` aceita pelo Discord, e a menção some do chat
        sem explicar por quê.
        """
        return f"</{self.name}:{self.id}>"


def _localizations(data: Mapping[str, Any], key: str) -> Mapping[str, str] | None:
    """Mapa de locale → texto, só com as entradas cujo valor é string.

    O Discord manda ``null`` em alguns locales; manter ``None`` como
    valor interno distingue "não há traduções" de "há, mas o mapa é
    vazio".
    """
    raw = data.get(key)
    if not isinstance(raw, Mapping):
        return None
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
