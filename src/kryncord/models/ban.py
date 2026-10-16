"""Banimento de servidor.

O payload é ``{user, reason}`` — dois campos, e o `reason` pode faltar
(se o ban foi feito sem motivo, ele vem como `None`, não como ``""``,
porque "sem motivo declarado" e "motivo vazio" não são a mesma coisa).

`GET /guilds/:id/bans` não tem offset: a paginação é por ``after`` com
o ID do usuário, que é monotônico no snowflake. Quem pagina com ``limit``
só enche a primeira página se não seguir o cursor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import string
from kryncord.models.user import User


@dataclass(frozen=True, slots=True)
class Ban:
    """Um usuário banido de uma guild, com o motivo quando houver."""

    user: User
    reason: str | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Ban | None:
        """`None` se faltar o ``user`` — um ban sem usuário não é ban.

        O `User` também pode devolver `None` (payload parcial); nesse
        caso devolvemos `None` aqui, e não um `Ban` de usuário faltando.
        """
        raw = data.get("user")
        if not isinstance(raw, Mapping):
            return None
        user = User.from_payload(raw)
        if user is None:
            return None
        return cls(user=user, reason=string(data, "reason"))
