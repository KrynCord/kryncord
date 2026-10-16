"""Webhook.

Um webhook é o caso em que o objeto **muda dependendo de quem pediu**:
`GET /webhooks/:id` devolve o webhook sem o ``token``, e
`GET /webhooks/:id/:token` devolve com ele. O token é um segredo —
quem o tem executa o webhook sem autenticação nenhuma —, então o
Discord só o entrega quando a requisição é autenticada e o bot tem
permissão.

Isso significa `token: str | None`, e não `token: str = ""`. Um token
ausente e um token vazio não são a mesma coisa: o primeiro não foi
entregue, o segundo seria um token que não serve para nada.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import integer, snowflake, string


@dataclass(frozen=True, slots=True)
class Webhook:
    """Webhook de canal, com o token só quando entregue."""

    id: int
    type: int
    channel_id: int | None = None
    guild_id: int | None = None
    name: str | None = None
    avatar: str | None = None
    token: str | None = None
    application_id: int | None = None
    source_guild_id: int | None = None
    source_channel_id: int | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Webhook | None:
        """`None` se faltar o ``id`` — um webhook sem ID não se busca."""
        webhook_id = snowflake(data, "id")
        if webhook_id is None:
            return None
        source_guild = data.get("source_guild")
        source_channel = data.get("source_channel")
        return cls(
            id=webhook_id,
            type=integer(data, "type") or 0,
            channel_id=snowflake(data, "channel_id"),
            guild_id=snowflake(data, "guild_id"),
            name=string(data, "name"),
            avatar=string(data, "avatar"),
            # Só entra se for string — um token numérico viraria int e
            # perderia zeros à esquerda na concatenação da URL.
            token=string(data, "token"),
            application_id=snowflake(data, "application_id"),
            source_guild_id=snowflake(source_guild, "id")
            if isinstance(source_guild, Mapping)
            else None,
            source_channel_id=snowflake(source_channel, "id")
            if isinstance(source_channel, Mapping)
            else None,
        )

    @property
    def execute_url(self) -> str | None:
        """URL de execução do webhook, ou `None` sem token.

        Com token, esta URL aceita `POST` sem header de autenticação
        nenhum — é por isso que ela não pode vazar num log.
        """
        if self.token is None:
            return None
        return f"https://discord.com/api/webhooks/{self.id}/{self.token}"

    @property
    def is_slack_compatible(self) -> bool:
        """Se aceita payload no formato Slack (`type == 1`).

        O tipo ``0`` é o formato próprio do Discord; ``1`` é o do
        Slack. Quem monta o corpo precisa saber qual é.
        """
        return self.type == 1
