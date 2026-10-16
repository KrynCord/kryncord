"""Payload do ``TYPING_START`` — alguém está digitando.

Evento barato e frequente: o Discord manda um por tecla pressionada
(emissão limitada a um a cada 5 segundos por canal). Dois campos
importam para quem escreve um bot:

- ``user_id`` — quem digitou. Em guild vem do payload **e** do
  ``member``; em DM vem só do ``user_id``. O fallback de um para o outro
  é o que faz o modelo funcionar nos dois casos sem `None` na metade
  das vezes.
- ``timestamp`` — é **unix float**, não ISO8601. É o único ``timestamp``
  do Discord que vem assim, e tratar com o helper ISO devolveria `None`
  em silêncio.

``member`` é o membro completo, enviado só em guild — quem quer o cargo
ou o apelido lê dele, sem ir ao cache.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kryncord.models.base import snowflake, timestamp
from kryncord.models.member import Member


@dataclass(frozen=True, slots=True)
class TypingStart:
    """Alguém começou a digitar num canal."""

    channel_id: int
    user_id: int | None
    guild_id: int | None = None
    timestamp: datetime | None = None
    member: Member | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> TypingStart | None:
        """`None` sem ``channel_id`` — digitar em lugar nenhum não é evento.

        Os outros campos têm fallback (``user_id`` vem do ``member``),
        mas o canal é o que dá sentido ao payload: sem ele o objeto não
        diz onde alguém está digitando.
        """
        channel_id = snowflake(data, "channel_id")
        if channel_id is None:
            return None

        member_payload = data.get("member")
        member = (
            Member.from_payload(member_payload) if isinstance(member_payload, Mapping) else None
        )
        user_id = snowflake(data, "user_id")
        if user_id is None and member is not None:
            user_id = member.user.id

        return cls(
            channel_id=channel_id,
            user_id=user_id,
            guild_id=snowflake(data, "guild_id"),
            timestamp=_unix_ou_iso(data),
            member=member,
        )

    @property
    def in_guild(self) -> bool:
        """`True` em guild. Em DM ``guild_id`` não existe."""
        return self.guild_id is not None

    @property
    def author_name(self) -> str | None:
        """Apelido de quem digitou, sem ir ao cache.

        `None` fora de guild — em DM o payload não traz nome, e inventar
        um faria o handler imprimir "None" como se fosse gente.
        """
        if self.member is not None:
            return self.member.display_name
        return None


def _unix_ou_iso(data: Mapping[str, Any]) -> datetime | None:
    """``timestamp`` de typing vem como unix float; aceita ISO por garantia.

    Duas formas no mesmo campo porque o Discord já mudou o formato de
    timestamps entre versões da API. Um `float` vira `datetime` direto;
    uma string passa pelo helper ISO. Qualquer outra coisa: `None`, sem
    levantar — payload estranho não derruba o bot (`0003`).
    """
    bruto = data.get("timestamp")
    if isinstance(bruto, (int, float)) and not isinstance(bruto, bool):
        return datetime.fromtimestamp(bruto, tz=UTC)
    if isinstance(bruto, str):
        return timestamp(data, "timestamp")
    return None
