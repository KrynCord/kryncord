"""Cargo de servidor.

Um `Role` carrega permissão, cor e posição — e é o objeto mais
consultado de uma guild depois do membro. Duas coisas dele confundem
quem vem de outra biblioteca:

**`permissions` é string, não int.** O Discord manda o acumulado das
permissões como string de bits de 64, porque JavaScript perde precisão
acima de ``2**53``. Guardar `int` daria comparação direta; guardar
`str` mentiria sobre o tipo. `Permissions` (a partir de `enums.py`)
converte quando precisar.

**`color` é int, e `colors` é a lista nova.** O Discord migrou de uma
cor só para uma gradiente; os dois campos coexistem no payload. Ler só
o antigo funcionaria até o dia em que parar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import boolean, integer, snowflake, string

#: Posição inválida. O Discord usa ``-1`` para "sem posição", que aparece
#: em cargos gerenciados por integração.
NO_POSITION = -1


@dataclass(frozen=True, slots=True)
class Role:
    """Um cargo de servidor."""

    id: int
    name: str
    color: int = 0
    hoist: bool = False
    position: int = 0
    permissions: str = "0"
    managed: bool = False
    mentionable: bool = False
    flags: int = 0
    icon: str | None = None
    unicode_emoji: str | None = None
    positions_new: int | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Role | None:
        """`None` se faltar o ``id`` ou o ``name`` — um cargo sem esses
        dois não identifica nada, e `name` é obrigatório no payload
        real do Discord."""
        role_id = snowflake(data, "id")
        name = string(data, "name")
        if role_id is None or name is None:
            return None
        positions_new = data.get("positions")
        return cls(
            id=role_id,
            name=name,
            color=integer(data, "color") or 0,
            hoist=boolean(data, "hoist"),
            position=integer(data, "position") or 0,
            permissions=string(data, "permissions") or "0",
            managed=boolean(data, "managed"),
            mentionable=boolean(data, "mentionable"),
            flags=integer(data, "flags") or 0,
            icon=string(data, "icon"),
            unicode_emoji=string(data, "unicode_emoji"),
            positions_new=positions_new if isinstance(positions_new, int) else None,
        )

    @property
    def color_rgb(self) -> tuple[int, int, int]:
        """Cor como triplo RGB.

        O Discord manda um inteiro de 24 bits (``0xRRGGBB``). Um `int`
        cru não serve para montar CSS nem para comparar com outra cor
        construída à mão.
        """
        return ((self.color >> 16) & 0xFF, (self.color >> 8) & 0xFF, self.color & 0xFF)

    @property
    def is_default(self) -> bool:
        """Se é o cargo "@everyone".

        É o único cargo que todo membro tem, que não pode ser apagado,
        e cujo ID é o mesmo da guild. Handlers de permissão perguntam
        isso com frequência.
        """
        return self.permissions == "0" or "@everyone" in self.name

    @property
    def mention(self) -> str:
        """Texto que menciona o cargo no chat.

        Só funciona se o cargo for mencionável — senão o Discord envia
        o texto sem pingar ninguém, e sem dizer por quê.
        """
        return f"<@&{self.id}>"

    @property
    def icon_url(self) -> str | None:
        """URL do ícone do cargo, ou `None` se usar emoji unicode."""
        if self.icon is None:
            return None
        from kryncord.models.base import cdn

        return cdn(f"role-icons/{self.id}/{self.icon}.png")
