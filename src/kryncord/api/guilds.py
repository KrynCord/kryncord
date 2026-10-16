"""Servidores: leitura e as operações que um bot costuma fazer.

O recorte aqui é propositalmente estreito. A API de guild tem centenas
de endpoints — convites, introspecção, regiões, audit log — e quase
nenhum é caminho crítico de bot. Entra o que se usa; o resto entra
quando um endpoint concretamente precisar, conforme a `0003`.
"""

from __future__ import annotations

from typing import Any

from kryncord.api._parse import expect_model
from kryncord.models.guild import Guild
from kryncord.rest.client import RESTClient


class GuildsAPI:
    """Operações de servidor."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def fetch(self, guild_id: int | str) -> Guild:
        """Busca uma guild.

        O que volta é menos completo que o `GUILD_CREATE` que o Gateway
        manda: sem a lista de canais, sem os membros. É o resumo, não o
        estado.
        """
        return expect_model(
            Guild,
            await self._rest.request("GET", f"/guilds/{guild_id}"),
            route="GET /guilds/:id",
        )

    async def modify(self, guild_id: int | str, **fields: Any) -> Guild:
        """Altera campos da guild e devolve o estado novo."""
        return expect_model(
            Guild,
            await self._rest.request("PATCH", f"/guilds/{guild_id}", json=fields),
            route="PATCH /guilds/:id",
        )

    async def leave(self, guild_id: int | str) -> None:
        """Faz o bot sair da guild. Devolve 204, sem corpo.

        Desfazer exige convite novo — não há endpoint de voltar.
        """
        await self._rest.request("DELETE", f"/guilds/{guild_id}/members/@me")
