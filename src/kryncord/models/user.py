"""Usuário do Discord."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import boolean, cdn, default_avatar_url, integer, snowflake, string


@dataclass(frozen=True, slots=True)
class User:
    """Conta de usuário.

    ``discriminator`` ficou ``str``, não ``int``: o Discord ainda manda
    ``"0"`` para contas migradas para o sistema de username novo, e um
    ``0`` int faria ``disc == 0`` parecer uma comparação de cargo.
    """

    id: int
    username: str
    discriminator: str | None = None
    global_name: str | None = None
    avatar: str | None = None
    bot: bool = False
    system: bool = False
    public_flags: int = 0

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> User | None:
        """`None` se faltar o ``id`` — uma conta sem ID não é conta."""
        user_id = snowflake(data, "id")
        if user_id is None:
            return None
        return cls(
            id=user_id,
            username=string(data, "username") or "",
            discriminator=string(data, "discriminator"),
            global_name=string(data, "global_name"),
            avatar=string(data, "avatar"),
            bot=boolean(data, "bot"),
            system=boolean(data, "system"),
            public_flags=integer(data, "public_flags") or 0,
        )

    @property
    def display_name(self) -> str:
        """Nome exibido no chat: apelido global se houver, senão o username.

        É o que aparece ao lado da mensagem. ``username`` é o login
        único; ``global_name`` é o nome que a pessoa escolheu mostrar.
        """
        return self.global_name or self.username

    @property
    def avatar_url(self) -> str | None:
        """URL do avatar escolhido, ou `None` para quem nunca escolheu."""
        if self.avatar is None:
            return None
        return cdn(f"avatars/{self.id}/{self.avatar}.png")

    @property
    def display_avatar_url(self) -> str:
        """URL do avatar, com o genérico quando não há um escolhido.

        Este nunca é `None` — é o que se coloca num ``<img>`` sem ter
        que tratar o caso omissso.
        """
        if self.avatar is None:
            return default_avatar_url(self.discriminator_value)
        return cdn(f"avatars/{self.id}/{self.avatar}.png")

    @property
    def discriminator_value(self) -> int:
        """``discriminator`` como inteiro, para o cálculo do avatar genérico.

        ``None`` (conta nova) vira ``0``, que é exatamente o que o
        Discord usa nessas contas.
        """
        if self.discriminator is None or not self.discriminator.isdigit():
            return 0
        return int(self.discriminator)

    @property
    def mention(self) -> str:
        """Texto que menciona o usuário no chat."""
        return f"<@{self.id}>"
