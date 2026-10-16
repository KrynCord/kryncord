"""Membro de servidor — o usuário *dentro* de uma guild.

A separação é do Discord, não nossa: um `User` é a conta (vale em todo
lugar), um `Member` é a aparência e os papéis dela *num servidor
específico*. A mesma pessoa tem um `User` e um `Member` por guild em que
entra, e os dois mudam independentemente.

Por isso `Member.user` é obrigatório: sem a conta, um membro não é
ninguém.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kryncord.models.base import sequence, string, timestamp
from kryncord.models.user import User


@dataclass(frozen=True, slots=True)
class Member:
    """Presença de um usuário dentro de uma guild."""

    user: User
    nick: str | None = None
    roles: tuple[int, ...] = ()
    joined_at: datetime | None = None
    premium_since: datetime | None = None
    deaf: bool = False
    mute: bool = False
    pending: bool = False

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Member | None:
        """`None` se o payload não trouxer o usuário.

        Um ``MESSAGE_CREATE`` sem ``member.user`` não dá para atribuir
        a ninguém, e devolver um `Member` com usuário inventado seria
        pior que devolver nada. Vale também para ``user`` sem ``id`` —
        `User.from_payload` devolve `None` nesse caso.
        """
        user_payload = data.get("user")
        if not isinstance(user_payload, Mapping):
            return None
        user = User.from_payload(user_payload)
        if user is None:
            return None
        return cls(
            user=user,
            nick=string(data, "nick"),
            roles=_role_ids(data),
            joined_at=timestamp(data, "joined_at"),
            premium_since=timestamp(data, "premium_since"),
            deaf=data.get("deaf") is True,
            mute=data.get("mute") is True,
            pending=data.get("pending") is True,
        )

    @property
    def display_name(self) -> str:
        """Apelido da guild se houver, senão o nome exibido do usuário."""
        return self.nick or self.user.display_name


def _role_ids(data: Mapping[str, Any]) -> tuple[int, ...]:
    """IDs dos papéis do membro, convertendo as strings do JSON em int.

    O Discord manda ``roles`` como lista de strings de snowflake.
    Guardar ``int`` mantém o mesmo tipo de todo o resto da biblioteca —
    e comparar ``"123" == 123`` é como se ganha bug silencioso.
    """
    ids: list[int] = []
    for role in sequence(data, "roles"):
        if isinstance(role, str) and role.isdigit():
            ids.append(int(role))
        elif isinstance(role, int) and not isinstance(role, bool):
            ids.append(role)
    return tuple(ids)
