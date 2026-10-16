"""Servidor (guild).

`Guild` vem em dois tamanhos diferentes, e a diferença importa. O
``READY`` manda só ``id`` e ``unavailable``; o ``GUILD_CREATE`` — que
chega logo depois, quando o bot entra de verdade — manda tudo. O mesmo
`Guild` representa os dois, e os campos que só existem no segundo ficam
em `None`.

É por isso que nenhum campo aqui é obrigatório além do ``id``: um bot
que assume que ``name`` sempre veio vai quebrar no primeiro payload
parcial, e o Discord manda parcial o tempo todo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kryncord.models.base import boolean, cdn, integer, sequence, snowflake, string, timestamp


@dataclass(frozen=True, slots=True)
class Guild:
    """Um servidor, completo ou só referenciado."""

    id: int
    name: str | None = None
    icon: str | None = None
    owner_id: int | None = None
    region: str | None = None
    afk_channel_id: int | None = None
    afk_timeout: int | None = None
    verification_level: int | None = None
    default_message_notifications: int | None = None
    explicit_content_filter: int | None = None
    roles: tuple[int, ...] = ()
    emojis: tuple[int, ...] = ()
    features: tuple[str, ...] = ()
    mfa_level: int | None = None
    application_id: int | None = None
    system_channel_id: int | None = None
    system_channel_flags: int | None = None
    rules_channel_id: int | None = None
    member_count: int | None = None
    vanity_url_code: str | None = None
    description: str | None = None
    banner: str | None = None
    premium_tier: int | None = None
    premium_subscription_count: int | None = None
    preferred_locale: str | None = None
    nsfw_level: int | None = None
    unavailable: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Guild | None:
        """Monta a partir do payload cru, completo ou parcial.

        `None` quando falta o ``id`` — uma guild sem ID não é guild.
        """
        guild_id = snowflake(data, "id")
        if guild_id is None:
            return None
        return cls(
            id=guild_id,
            name=string(data, "name"),
            icon=string(data, "icon"),
            owner_id=snowflake(data, "owner_id"),
            region=string(data, "region"),
            afk_channel_id=snowflake(data, "afk_channel_id"),
            afk_timeout=integer(data, "afk_timeout"),
            verification_level=integer(data, "verification_level"),
            default_message_notifications=integer(data, "default_message_notifications"),
            explicit_content_filter=integer(data, "explicit_content_filter"),
            roles=_ids_of(data, "roles"),
            emojis=_ids_of(data, "emojis"),
            features=tuple(f for f in sequence(data, "features") if isinstance(f, str)),
            mfa_level=integer(data, "mfa_level"),
            application_id=snowflake(data, "application_id"),
            system_channel_id=snowflake(data, "system_channel_id"),
            system_channel_flags=integer(data, "system_channel_flags"),
            rules_channel_id=snowflake(data, "rules_channel_id"),
            member_count=integer(data, "member_count"),
            vanity_url_code=string(data, "vanity_url_code"),
            description=string(data, "description"),
            banner=string(data, "banner"),
            premium_tier=integer(data, "premium_tier"),
            premium_subscription_count=integer(data, "premium_subscription_count"),
            preferred_locale=string(data, "preferred_locale"),
            nsfw_level=integer(data, "nsfw_level"),
            unavailable=boolean(data, "unavailable"),
            created_at=timestamp(data, "created_at"),
        )

    @property
    def icon_url(self) -> str | None:
        """URL do ícone, ou `None` se a guild nunca escolheu um."""
        if self.icon is None:
            return None
        return cdn(f"icons/{self.id}/{self.icon}.png")

    @property
    def banner_url(self) -> str | None:
        """URL do banner de fundo, ou `None`."""
        if self.banner is None:
            return None
        return cdn(f"banners/{self.id}/{self.banner}.png")


def _ids_of(data: Mapping[str, Any], key: str) -> tuple[int, ...]:
    """IDs de uma lista de objetos aninhados (roles, emojis).

    Guardamos só os IDs. Cada role da guild vem inteira no payload, e
    um `Guild` com vinte roles de vinte campos cada seria um objeto
    pesado que ninguém pediu — o cargo completo se busca quando se
    precisa dele.
    """
    ids: list[int] = []
    for item in sequence(data, key):
        if isinstance(item, Mapping):
            found = snowflake(item, "id")
            if found is not None:
                ids.append(found)
    return tuple(ids)
