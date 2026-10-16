"""Objetos que o Discord entrega incompletos, de propósito.

O nome é o argumento. Um ``MESSAGE_DELETE`` manda ``id``, ``channel_id``
e (às vezes) ``guild_id`` — e mais nada. Se a gente montasse um
`Message` com tudo em ``None``, ``message.content`` devolveria ``None``
e pareceria que a mensagem não tinha texto. Teria: o payload não veio.

`PartialMessage` resolve isso não *tendo* o campo. ``partial.content``
não existe, e o ``AttributeError`` é a resposta honesta — o objeto nunca
viu aquele dado, e fingir que viu é como nasce cache corrompido.

É a mesma distinção que `models/base.py` faz entre ausência e default,
levada até a forma do objeto.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import snowflake


@dataclass(frozen=True, slots=True)
class PartialMessage:
    """Referência a uma mensagem que não veio inteira."""

    id: int
    channel_id: int
    guild_id: int | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> PartialMessage | None:
        """`None` se faltar o ``id``: sem ele não há mensagem a
        referenciar, e entregar objeto com ID inventado faria o
        chamador perseguir algo que não existe."""
        message_id = snowflake(data, "id")
        if message_id is None:
            return None
        return cls(
            id=message_id,
            channel_id=snowflake(data, "channel_id") or 0,
            guild_id=snowflake(data, "guild_id"),
        )


@dataclass(frozen=True, slots=True)
class PartialChannel:
    """Canal identificado, sem garantia de ter sido carregado."""

    id: int
    guild_id: int | None = None
    type: int | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> PartialChannel | None:
        channel_id = snowflake(data, "id")
        if channel_id is None:
            return None
        channel_type = data.get("type")
        return cls(
            id=channel_id,
            guild_id=snowflake(data, "guild_id"),
            type=channel_type
            if isinstance(channel_type, int) and not isinstance(channel_type, bool)
            else None,
        )


@dataclass(frozen=True, slots=True)
class PartialGuild:
    """Servidor que o Discord reporta só para dizer que existe.

    É o que vem no array ``guilds`` do ``READY``: ``{"id": ...,
    "unavailable": true}``. A guild completa chega depois, no
    ``GUILD_CREATE``, quando o bot entrou nela de verdade.
    """

    id: int
    unavailable: bool = False

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> PartialGuild | None:
        guild_id = snowflake(data, "id")
        if guild_id is None:
            return None
        return cls(
            id=guild_id,
            unavailable=data.get("unavailable", False) is True,
        )
